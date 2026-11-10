"""Reconciliação da API MES com exportação Excel e exceção de Code."""
from io import BytesIO
import unittest
from unittest.mock import patch
import json
import gzip
import os

import pandas as pd

from mes_general_report_reconciliation import (
    _registros_excel, pacote_do_excel_manual, comparar_com_quarentena,
)
from mes_general_report_validation import coletar_e_comparar


def mes(code="00000441", *, descricao="CABO", qtd=1, atend=0):
    return {
        "OP": "26028901001", "Code": code, "Description": descricao,
        "LastRequest": "2026-10-20T15:00:00Z",
        "NecessaryQuantity": qtd, "AttendedQuantity": atend,
    }


def excel_pack(*linhas):
    return {
        "format": "SETTA_SOURCE_V1", "source_key": "relatorio_geral",
        "sheets": [{"name": "Geral", "rows": [
            ["Projeto", "Código", "Descrição", "Última solicitação",
             "Qtd. necessária", "Qtd. atendida"],
            *linhas,
        ]}],
    }


def row(code="00000441", descricao="CABO", qtd=1, atend=0):
    return ["26028901001", code, descricao, "20/10/2026", qtd, atend]


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.status_code = 200
        self.headers = {"Content-Length": str(len(body))}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i+chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ReconciliacaoTests(unittest.TestCase):
    def test_excecao_identica_nas_duas_origens_compara_validos(self):
        api = [
            mes(), mes(None, descricao="BASCULANTE", qtd=1),
        ]
        x = comparar_com_quarentena(
            api,
            excel_pack(row(), row(None, "BASCULANTE", 1)),
            referencia="Excel manual",
        )
        self.assertTrue(x["excecoes_correspondentes"])
        self.assertEqual(x["api"]["linhas"], 1)
        self.assertEqual(x["excel"]["linhas"], 1)
        self.assertEqual(x["auditoria"]["registros_pendentes"], 1)
        self.assertEqual(x["auditoria_excel"]["registros_pendentes"], 1)
        self.assertTrue(x["coincidem_registros_validos"])
        self.assertTrue(x["homologacao_bloqueada"])
        self.assertFalse(x["iguais_no_criterio_comparado"])
        self.assertEqual(x["auditoria_excel"]["exemplos"][0]["Linha Excel"], 3)
        self.assertNotIn("26028901001", str(x))
        self.assertNotIn("BASCULANTE", str(x))

    def test_excecao_presente_so_na_api_gera_alerta_de_incompatibilidade(self):
        x = comparar_com_quarentena(
            [mes(), mes(None, descricao="BASCULANTE")],
            excel_pack(row()),
            referencia="Excel manual",
        )
        self.assertFalse(x["excecoes_correspondentes"])
        self.assertTrue(x["homologacao_bloqueada"])

    def test_diferencas_entre_validos_sao_exibidas_mas_nao_homologadas(self):
        x = comparar_com_quarentena(
            [mes(qtd=3), mes(None, descricao="BASCULANTE")],
            excel_pack(row(qtd=4), row(None, "BASCULANTE")),
            referencia="Excel manual",
        )
        self.assertEqual(x["comparativo"]["quantidades_diferentes"], 1)
        self.assertFalse(x["coincidem_registros_validos"])
        self.assertTrue(x["homologacao_bloqueada"])

    def test_sem_excecoes_pode_igualar_dados(self):
        x = comparar_com_quarentena([mes()], excel_pack(row()), referencia="Central")
        self.assertTrue(x["iguais_no_criterio_comparado"])
        self.assertFalse(x["homologacao_bloqueada"])
        self.assertFalse(x["comparacao_parcial"])

    def test_excel_manual_mantem_codigo_textual_zeros_e_detecta_linha_vazia(self):
        df = pd.DataFrame([
            row(), row(None, "BASCULANTE"),
        ], columns=["Projeto", "Código", "Descrição",
                    "Última solicitação", "Qtd. necessária", "Qtd. atendida"])
        with BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Geral", index=False)
            excel_bytes = buffer.getvalue()
        pacote = pacote_do_excel_manual(excel_bytes)
        rows = _registros_excel(pacote)
        self.assertEqual(rows[0]["Code"], "00000441")
        self.assertIsNone(rows[1]["Code"])

    def test_modo_excel_faz_uma_consulta_mes_sem_atualizar_central(self):
        df = pd.DataFrame([
            row(), row(None, "BASCULANTE"),
        ], columns=["Projeto", "Código", "Descrição",
                    "Última solicitação", "Qtd. necessária", "Qtd. atendida"])
        with BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Geral", index=False)
            excel_bytes = buffer.getvalue()
        api = [mes(), mes(None, descricao="BASCULANTE")]
        response = FakeResponse(json.dumps(api).encode())
        src = FakeSession(response)
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_general_report_validation.store.central_api_call") as central:
            result = coletar_e_comparar(mes_session=src, excel_manual_bytes=excel_bytes)
            central.assert_not_called()
        self.assertTrue(result["homologacao_bloqueada"])
        self.assertTrue(result["excecoes_correspondentes"])
        self.assertEqual(len(src.calls), 1)
        self.assertTrue(response.closed)
        self.assertNotIn("ficticio", str(result))

    def test_rejeita_formato_incorreto(self):
        with self.assertRaises(ValueError):
            pacote_do_excel_manual(b"nao-e-excel")

    def test_estrutura_com_lote_e_atendimento_nao_perde_quantidade(self):
        api = [
            mes(qtd=5, atend=1),
            mes(qtd=5, atend=2),
            mes(code=None, descricao="BASCULANTE"),
        ]
        ref = excel_pack(
            row(qtd=5, atend=1),
            row(qtd=5, atend=2),
            row(None, "BASCULANTE"),
        )
        x = comparar_com_quarentena(api, ref, referencia="Excel manual")
        self.assertEqual(x["api"]["necessidade"], 5)
        self.assertEqual(x["api"]["atendimento"], 3)
        self.assertEqual(x["api"]["pendencia"], 2)
        self.assertEqual(x["comparativo"]["quantidades_diferentes"], 0)


if __name__ == "__main__":
    unittest.main()
