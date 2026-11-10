"""Regras da integração automática MES -> Central (sem rede/dados reais)."""
from __future__ import annotations

from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch

import pandas as pd

from mes_source_sync import preparar_fonte, _xlsx, sincronizar_api_mes


def item(**kwargs):
    row = {
        "OP": "26028901001", "Code": "00000441",
        "Description": "MATERIAL DE TESTE",
        "LastRequest": "2026-10-20T15:00:00Z",
        "NecessaryQuantity": 2,
        "AttendedQuantity": 1,
        "SeparationUser": "", "SeparationDate": "",
        "ConferenceResponse": "", "ConferenceDate": "",
    }
    row.update(kwargs)
    return row


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data
        self.status_code = 200
        self.headers = {"Content-Length": str(len(data))}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, **kwargs):
        return self.response


class MesSourceSyncTests(unittest.TestCase):
    def test_excecao_1_entre_201_segue_para_auditoria(self):
        data = [item() for _ in range(200)] + [
            item(Code=None, Description="BASCULANTE",
                 NecessaryQuantity=1, AttendedQuantity=0),
        ]
        p = preparar_fonte(data, linhas_referencia=201)
        self.assertEqual(p["politica"]["status"], "PROCESSAR_COM_RESSALVAS")
        self.assertEqual(len(p["validas"]), 200)
        self.assertEqual(len(p["excecoes"]), 1)
        self.assertEqual(p["excecoes"][0][2], "")
        self.assertEqual(p["excecoes"][0][3], "BASCULANTE")
        self.assertEqual(p["excecoes"][0][6], 1.0)
        self.assertIn("Code", p["excecoes"][0][8])
        self.assertTrue(p["arquivo"].startswith("API_MES_"))

    def test_arquivo_contém_geral_e_quarentena_sem_linha_perdida(self):
        data = [item() for _ in range(200)] + [item(Code="")]
        xlsx = _xlsx(preparar_fonte(data, linhas_referencia=201))
        excel = pd.ExcelFile(BytesIO(xlsx))
        self.assertEqual(excel.sheet_names, ["Geral", "API_INCONSISTENCIAS"])
        valido = pd.read_excel(BytesIO(xlsx), sheet_name="Geral", dtype={"Código": str})
        auditado = pd.read_excel(BytesIO(xlsx), sheet_name="API_INCONSISTENCIAS")
        self.assertEqual(len(valido), 200)
        self.assertEqual(len(auditado), 1)
        self.assertEqual(valido.iloc[0]["Código"], "00000441")
        self.assertEqual(auditado.iloc[0]["Linha de origem"], 202)

    def test_fonte_maciçamente_inconsistente_não_pode_substituir_base(self):
        data = [item() for _ in range(50)] + [item(Code=None) for _ in range(50)]
        with self.assertRaisesRegex(ValueError, "PROTEGER_BASE"):
            preparar_fonte(data, linhas_referencia=100)

    def test_payload_reduzido_não_substitui_base(self):
        with self.assertRaisesRegex(ValueError, "Volume"):
            preparar_fonte([item()], linhas_referencia=1000)

    def test_assinatura_independe_do_tempo_de_geração_do_xlsx(self):
        registros = [item() for _ in range(20)]
        p1 = preparar_fonte(registros)
        p2 = preparar_fonte(registros)
        self.assertEqual(p1["assinatura"], p2["assinatura"])
        self.assertEqual(p1["arquivo"], p2["arquivo"])

    def test_sem_token_não_altera_central(self):
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": ""}), \
             patch("mes_source_sync.store.central_api_call") as central:
            with self.assertRaisesRegex(ValueError, "Credencial MES"):
                sincronizar_api_mes()
        central.assert_not_called()

    def test_uma_chamada_publica_somente_se_passar_na_validação(self):
        raw = json.dumps([item()] * 200 + [item(Code=None)]).encode()
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_source_sync.store.central_api_call",
                   return_value={"data": [{"source_key": "relatorio_geral",
                                           "rows_count": 201,
                                           "last_file_name": "manual.xlsx",
                                           "version": 35}]}), \
             patch("mes_source_sync.store.save_report",
                   return_value={"version": 36}) as saved:
            result = sincronizar_api_mes(
                session=FakeSession(FakeResponse(raw)),
            )
        self.assertEqual(result["status"], "PROCESSAR_COM_RESSALVAS")
        self.assertEqual(result["quarentena"], 1)
        self.assertTrue(result["publicado"])
        args = saved.call_args.args
        self.assertEqual(args[0], "relatorio_geral")
        self.assertEqual(args[3], 200)

    def test_resposta_igual_não_gera_nova_versão(self):
        raw_records = [item()] * 200 + [item(Code=None)]
        nome = preparar_fonte(raw_records)["arquivo"]
        raw = json.dumps(raw_records).encode()
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_source_sync.store.central_api_call",
                   return_value={"data": [{"source_key": "relatorio_geral",
                                           "rows_count": 200,
                                           "last_file_name": nome,
                                           "version": 36}]}), \
             patch("mes_source_sync.store.touch_source") as touched, \
             patch("mes_source_sync.store.save_report") as saved:
            result = sincronizar_api_mes(
                session=FakeSession(FakeResponse(raw)),
            )
        self.assertFalse(result["publicado"])
        self.assertEqual(result["status"], "SEM ALTERAÇÃO")
        touched.assert_called_once()
        saved.assert_not_called()

    def test_reprocessamento_manual_força_nova_versão(self):
        raw_records = [item()] * 200 + [item(Code=None)]
        nome = preparar_fonte(raw_records)["arquivo"]
        raw = json.dumps(raw_records).encode()
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_source_sync.store.central_api_call",
                   return_value={"data": [{"source_key": "relatorio_geral",
                                           "rows_count": 200,
                                           "last_file_name": nome,
                                           "version": 36}]}), \
             patch("mes_source_sync.store.save_report",
                   return_value={"version": 37}) as saved:
            result = sincronizar_api_mes(
                session=FakeSession(FakeResponse(raw)), forcar=True,
            )
        self.assertTrue(result["publicado"])
        saved.assert_called_once()

    def test_invalid_date_em_quarentena(self):
        data = [item() for _ in range(200)] + [
            item(LastRequest="NAO É DATA"),
        ]
        p = preparar_fonte(data)
        self.assertEqual(len(p["excecoes"]), 1)
        self.assertEqual(len(p["validas"]), 200)


if __name__ == "__main__":
    unittest.main()
