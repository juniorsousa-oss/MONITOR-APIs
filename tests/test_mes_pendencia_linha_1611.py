"""Contrato de 16/11: necessidade-atendimento=pendencia por linha/lote.

Todos os testes usam JSON sintetico; nao chamam MES nem publicam no Supabase.
"""
from __future__ import annotations

import gzip
import json
from io import BytesIO
import unittest

import pandas as pd

from mes_general_report_sync import preparar_carga_mes
from mes_general_report_validation import auditar_registros_mes
from mes_general_report_sync import store


def registro(**alteracoes):
    linha = {
        "OP": "23040102007",
        "Code": "00060140",
        "Description": "MATERIAL TESTE",
        "LastRequest": "2026-11-13T10:00:00Z",
        "NecessaryQuantity": 2,
        "AttendedQuantity": 2,
        "Batch": "062088",
        "SeparationUser": "",
        "SeparationDate": "",
        "ConferenceResponse": "",
        "ConferenceDate": "",
    }
    linha.update(alteracoes)
    return linha


class ContratoPendenciaLinhaTests(unittest.TestCase):
    def test_multi_lote_necessidades_sao_parcelas_e_nao_saldo_acumulado(self):
        linhas = [
            registro(NecessaryQuantity=2, AttendedQuantity=2, Batch="062088"),
            registro(NecessaryQuantity=1, AttendedQuantity=1, Batch="062136"),
        ]
        out = preparar_carga_mes(linhas, referencia=2)
        self.assertEqual(out["status"], "PROCESSAR")
        self.assertEqual(out["pendencias_calculadas"], 2)
        frame = pd.read_excel(BytesIO(out["arquivo"]), sheet_name="Geral",
                              dtype={"Código": str, "Lote": str})
        self.assertEqual(frame["Qtd. necessária"].sum(), 3)
        self.assertEqual(frame["Qtd. atendida"].sum(), 3)
        self.assertEqual(frame["Qtd. pendências"].sum(), 0)
        self.assertEqual(frame["Lote"].tolist(), ["062088", "062136"])

    def test_multi_lote_pendencia_soma_ambas_as_parcelas(self):
        linhas = [
            registro(NecessaryQuantity=5, AttendedQuantity=2, Batch="062088"),
            registro(NecessaryQuantity=3, AttendedQuantity=0, Batch="062136"),
        ]
        out = preparar_carga_mes(linhas, referencia=2)
        frame = pd.read_excel(BytesIO(out["arquivo"]), sheet_name="Geral")
        self.assertEqual(frame["Qtd. necessária"].tolist(), [5, 3])
        self.assertEqual(frame["Qtd. pendências"].tolist(), [3, 3])
        self.assertEqual(frame["Qtd. pendências"].sum(), 6)

    def test_pendencia_explicita_mes_e_preservada_quando_confere(self):
        out = preparar_carga_mes([
            registro(PendingQuantity=1, NecessaryQuantity=3, AttendedQuantity=2)
        ], referencia=1)
        self.assertEqual(out["pendencias_api"], 1)
        self.assertEqual(out["pendencias_calculadas"], 0)
        df = pd.read_excel(BytesIO(out["arquivo"]), sheet_name="Geral")
        self.assertEqual(df.iloc[0]["Qtd. pendências"], 1)

    def test_pendencia_mes_divergente_e_quarentenada(self):
        linhas = [registro(Batch="062088") for _ in range(199)]
        linhas.append(registro(PendingQuantity=2, NecessaryQuantity=3,
                              AttendedQuantity=2, Batch="062136"))
        audit, validos = auditar_registros_mes(linhas)
        self.assertEqual(len(validos), 199)
        self.assertEqual(audit["motivos"]["PENDENCIA_DIVERGENTE"], 1)
        out = preparar_carga_mes(linhas, referencia=200)
        self.assertEqual(out["status"], "PROCESSAR_COM_RESSALVAS")
        self.assertEqual(out["linhas_fonte"], 199)
        self.assertEqual(out["linhas_excecao"], 1)

    def test_sobre_atendimento_impede_publicar_resposta_inconsistente(self):
        audit, validos = auditar_registros_mes([
            registro(NecessaryQuantity=1, AttendedQuantity=2)
        ])
        self.assertEqual(len(validos), 0)
        self.assertEqual(audit["motivos"]["ATENDIMENTO_SUPERIOR_NECESSIDADE"], 1)
        out = preparar_carga_mes([
            registro(NecessaryQuantity=1, AttendedQuantity=2)
        ], referencia=1)
        self.assertEqual(out["status"], "PROTEGER_BASE")
        self.assertIsNone(out["arquivo"])

    def test_normalizado_contem_pendencias_e_lote_sem_perda(self):
        out = preparar_carga_mes([
            registro(NecessaryQuantity=2, AttendedQuantity=1,
                     PendingQuantity=1, Batch="000000008")
        ], referencia=1)
        compressed, _ = store.build_normalized_source(
            "relatorio_geral", "RelatorioGeral_MES.xlsx", out["arquivo"]
        )
        pack = json.loads(gzip.decompress(compressed).decode("utf-8"))
        geral = next(x for x in pack["sheets"] if x["name"] == "Geral")
        cols = geral["rows"][0]
        self.assertEqual(cols[-2:], ["Qtd. pendências", "Lote"])
        self.assertEqual(geral["rows"][1][-1], "000000008")
        self.assertEqual(float(geral["rows"][1][-2]), 1)


if __name__ == "__main__":
    unittest.main()
