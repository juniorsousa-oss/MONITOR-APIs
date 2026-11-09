"""Testes da homologação API MES sem usar dados reais ou efetuar publicação."""
import gzip
import json
import os
import unittest
from unittest.mock import patch

from mes_general_report_validation import (
    _download_limited, _table_mes, comparar_documentos, coletar_e_comparar,
    MAX_MES_BYTES,
)


def mes(**kw):
    r = {
        "OP": "23040102007", "Code": "00000441",
        "LastRequest": "2026-08-11T15:46:19.714Z",
        "NecessaryQuantity": 5, "AttendedQuantity": 2,
        "Description": "MATERIAL DE TESTE",
        "SeparationUser": "", "SeparationDate": "",
        "ConferenceResponse": "", "ConferenceDate": "",
    }
    r.update(kw)
    return r


def pack(*rows):
    return {
        "format": "SETTA_SOURCE_V1", "source_key": "relatorio_geral",
        "sheets": [
            {"name": "Geral", "rows": [
                ["Projeto", "Código", "Descrição", "Última solicitação",
                 "Qtd. necessária", "Qtd. atendida"],
                *rows,
            ]},
        ],
    }


def excel_row(*, codigo="00000441", necessidade=5, atendido=2, data="11/08/2026"):
    return ["23040102007", codigo, "MATERIAL DE TESTE", data, necessidade, atendido]


class FakeResponse:
    def __init__(self, body=b'[]', status=200, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {"Content-Length": str(len(body))}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class HomologacaoTests(unittest.TestCase):
    def test_mes_igual_excel_por_op_codigo(self):
        x = comparar_documentos([mes()], pack(excel_row()))
        self.assertTrue(x["iguais_no_criterio_comparado"])
        self.assertEqual(x["comparativo"]["quantidades_diferentes"], 0)
        self.assertEqual(x["api"]["pendencia"], 3)
        self.assertNotIn("23040102007", str(x))
        self.assertNotIn("MATERIAL DE TESTE", str(x))

    def test_lotes_repetem_necessidade_mas_atendimento_soma(self):
        api = [
            mes(AttendedQuantity=1, Batch="L1"),
            mes(AttendedQuantity=1, Batch="L2"),
        ]
        x = comparar_documentos(api, pack(excel_row(atendido=1), excel_row(atendido=1)))
        self.assertTrue(x["iguais_no_criterio_comparado"])
        self.assertEqual(x["api"]["necessidade"], 5)
        self.assertEqual(x["api"]["atendimento"], 2)

    def test_parcial_e_divergencia_de_quantidade(self):
        x = comparar_documentos([mes(AttendedQuantity=1)], pack(excel_row()))
        self.assertFalse(x["iguais_no_criterio_comparado"])
        self.assertEqual(x["comparativo"]["quantidades_diferentes"], 1)

    def test_somente_api_e_somente_excel(self):
        x = comparar_documentos([mes(Code="00000555")], pack(excel_row()))
        self.assertFalse(x["iguais_no_criterio_comparado"])
        self.assertEqual(x["comparativo"]["somente_api"], 1)
        self.assertEqual(x["comparativo"]["somente_excel"], 1)

    def test_necessidades_divergentes_mesmo_dia_bloqueiam_aprovacao(self):
        x = comparar_documentos(
            [mes(NecessaryQuantity=5), mes(NecessaryQuantity=7)],
            pack(excel_row(necessidade=5))
        )
        self.assertEqual(x["api"]["solicitacoes_divergentes"], 1)
        self.assertFalse(x["iguais_no_criterio_comparado"])

    def test_datas_utc_no_fuso_brasileiro(self):
        api = [mes(LastRequest="2026-08-12T01:00:00Z")]
        x = comparar_documentos(api, pack(excel_row(data="11/08/2026")))
        self.assertTrue(x["iguais_no_criterio_comparado"])

    def test_data_excel_iso_sem_fuso_nao_muda_de_dia(self):
        api = [mes(LastRequest="2026-08-12T02:30:00")]
        x = comparar_documentos(api, pack(excel_row(data="12/08/2026")))
        self.assertTrue(x["iguais_no_criterio_comparado"])

    def test_falta_campo_critico_ou_quantidade_negativa(self):
        for dado in ([{"Code": "00000441"}], [mes(AttendedQuantity=-1)]):
            with self.subTest(dado=dado):
                with self.assertRaises(ValueError):
                    _table_mes(dado)

    def test_resposta_com_limite_estrito(self):
        ses = FakeSession(FakeResponse(body=b"x" * 10))
        with self.assertRaisesRegex(ValueError, "tamanho máximo"):
            _download_limited("https://dominio.exemplo/", session=ses, limit=5)
        self.assertTrue(ses.response.closed)

    def test_coleta_integral_somente_comparacao_sem_upload(self):
        mes_body = json.dumps([mes()]).encode()
        current_body = gzip.compress(json.dumps(pack(excel_row())).encode())
        src_mes = FakeSession(FakeResponse(mes_body))
        src_central = FakeSession(FakeResponse(current_body))
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "token-ficticio"}), \
             patch("mes_general_report_validation.store.central_api_call",
                   return_value={"data": {"signed_url": "https://cuixazpxkvniqldmmnth.supabase.co/storage/v1/object/sign/setta-data/test?token=ficticio"}}) as central_call:
            result = coletar_e_comparar(mes_session=src_mes, central_session=src_central)
        self.assertTrue(result["iguais_no_criterio_comparado"])
        self.assertEqual(len(src_mes.calls), 1)
        self.assertEqual(len(src_central.calls), 1)
        self.assertEqual(src_mes.calls[0][1]["headers"]["Authorization"], "Bearer token-ficticio")
        self.assertNotIn("token-ficticio", str(result))
        self.assertNotIn("23040102007", str(result))
        self.assertEqual(central_call.call_args.args[0], "source_normalized_download")

    def test_sem_token_nao_baixa(self):
        ses = FakeSession(FakeResponse())
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": ""}):
            with self.assertRaisesRegex(ValueError, "Token"):
                coletar_e_comparar(mes_session=ses)
        self.assertFalse(ses.calls)


if __name__ == "__main__":
    unittest.main()
