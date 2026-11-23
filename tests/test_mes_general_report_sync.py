"""Testes da carga MES 07h20. Sem acesso à API real e sem publicar no Supabase."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from mes_general_report_sync import (
    preparar_carga_mes, sincronizar_relatorio_geral, ORIGIN,
)


def registro(**updates):
    r = {
        "OP": "26028901001",
        "Code": "00000441",
        "Description": "CABO",
        "LastRequest": "2026-10-20T15:00:00Z",
        "NecessaryQuantity": 1,
        "AttendedQuantity": 0,
        "SeparationUser": "",
        "SeparationDate": "",
        "ConferenceResponse": "",
        "ConferenceDate": "",
    }
    r.update(updates)
    return r


class FakeResponse:
    status_code = 200
    closed = False

    def __init__(self, body: bytes):
        self.body = body
        self.headers = {"Content-Length": str(len(body))}

    def iter_content(self, chunk_size=65536):
        yield self.body

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, data):
        self.response = FakeResponse(json.dumps(data).encode())
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class IngestaoTests(unittest.TestCase):
    def test_quarentena_da_linha_bascuIante_nao_trava_os_demais(self):
        sample = [registro() for _ in range(200)]
        sample.append(registro(Code=None, Description="BASCULANTE",
                               NecessaryQuantity=1, AttendedQuantity=0))
        out = preparar_carga_mes(sample, referencia=201)
        self.assertEqual(out["status"], "PROCESSAR_COM_RESSALVAS")
        self.assertEqual(out["linhas_fonte"], 200)
        self.assertEqual(out["linhas_excecao"], 1)
        self.assertIsInstance(out["arquivo"], bytes)
        self.assertGreater(len(out["arquivo"]), 100)
        import pandas as pd
        from io import BytesIO
        df = pd.read_excel(BytesIO(out["arquivo"]), sheet_name="Geral")
        quarantined = df[df["Código"].isna()]
        self.assertEqual(len(quarantined), 0)  # material inválido fora da demanda
        self.assertEqual(len(df), 200)
        faults = pd.read_excel(BytesIO(out["arquivo"]), sheet_name="Inconsistencias MES")
        self.assertEqual(len(faults), 1)

    def test_api_batch_gera_coluna_lote_sem_perder_zeros_iniciais(self):
        from io import BytesIO
        import pandas as pd
        sample = [
            registro(Code="00000441", Batch="061638"),
            registro(Code="00000442", Batch="000000000"),
            registro(Code="00000443", Batch=None),
        ]
        out = preparar_carga_mes(sample, referencia=3)
        self.assertEqual(out["status"], "PROCESSAR")
        df = pd.read_excel(
            BytesIO(out["arquivo"]), sheet_name="Geral", dtype={"Lote": str},
        )
        self.assertEqual(df["Lote"].iloc[0], "061638")
        self.assertEqual(df["Lote"].iloc[1], "000000000")
        self.assertTrue(pd.isna(df["Lote"].iloc[2]))
        self.assertEqual(len(df), 3)
        self.assertIn("Data de conferência", df.columns)
        self.assertEqual(df.columns[-1], "Lote")

    def test_bloqueia_normalizado_sem_lote_antes_da_publicacao(self):
        with patch(
            "mes_general_report_sync.store.build_normalized_source",
            return_value=(b"pacote_sem_cabecalho", 1),
        ), patch("mes_general_report_sync.store.save_report") as save:
            with self.assertRaisesRegex(
                RuntimeError, "normalizado ilegível",
            ):
                preparar_carga_mes([registro(Batch="000001")], referencia=1)
            save.assert_not_called()

    def test_normalizado_possui_a_mesma_coluna_lote_da_planilha(self):
        import gzip
        from io import BytesIO
        import pandas as pd
        import json
        from mes_general_report_sync import store
        out = preparar_carga_mes(
            [registro(Batch="000001"), registro(Code="00000442", Batch="061638")],
            referencia=2,
        )
        normalized, total = store.build_normalized_source(
            "relatorio_geral", "RelatorioGeral_MES.xlsx", out["arquivo"],
        )
        pack = json.loads(gzip.decompress(normalized).decode("utf-8"))
        geral = next(x for x in pack["sheets"] if x["name"] == "Geral")
        self.assertEqual(geral["rows"][0][-1], "Lote")
        self.assertEqual(geral["rows"][1][-1], "000001")
        self.assertEqual(geral["rows"][2][-1], "061638")
        self.assertEqual(total, out["linhas_fonte"] + 2)

    def test_data_de_conferencia_invalida_entra_quarentena_sem_travar(self):
        sample = [registro() for _ in range(200)]
        sample.append(registro(ConferenceDate="data inválida"))
        out = preparar_carga_mes(sample, referencia=201)
        self.assertEqual(out["status"], "PROCESSAR_COM_RESSALVAS")
        self.assertEqual(out["linhas_excecao"], 1)
        self.assertEqual(out["linhas_fonte"], 200)

    def test_protecao_contra_fonte_aparentemente_truncada(self):
        out = preparar_carga_mes([registro()], referencia=1000)
        self.assertEqual(out["status"], "PROTEGER_BASE")
        self.assertIsNone(out["arquivo"])

    def test_sem_token_nao_chama_api_nem_publica(self):
        sample = FakeSession([registro()])
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": ""}), \
             patch("mes_general_report_sync.store.save_report") as save:
            with self.assertRaises(RuntimeError):
                sincronizar_relatorio_geral(session=sample)
            save.assert_not_called()
            self.assertFalse(sample.calls)

    def test_modo_dry_run_nunca_publica(self):
        sample = FakeSession([registro()])
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_general_report_sync._source_status", return_value={
                 "rows_count": 1, "content_sha256": "", "normalized_available": True,
             }), \
             patch("mes_general_report_sync.store.save_report") as save:
            result = sincronizar_relatorio_geral(session=sample, dry_run=True)
            self.assertFalse(result["publicado"])
            save.assert_not_called()
        self.assertEqual(len(sample.calls), 1)
        self.assertEqual(
            sample.calls[0][1]["headers"]["Authorization"], "Bearer ficticio"
        )
        self.assertNotIn("ficticio", str(result))

    def test_publica_uma_vez_se_validado(self):
        sample = FakeSession([registro()])
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_general_report_sync._source_status", return_value={
                 "rows_count": 1, "content_sha256": "", "normalized_available": True,
             }), \
             patch("mes_general_report_sync.store.save_report", return_value={
                 "version": 100, "normalized": {"available": True},
             }) as save:
            result = sincronizar_relatorio_geral(session=sample)
        self.assertTrue(result["publicado"])
        self.assertEqual(result["versao"], 100)
        self.assertEqual(save.call_args.kwargs["origin"], ORIGIN)
        self.assertEqual(save.call_args.args[0], "relatorio_geral")
        self.assertEqual(save.call_args.kwargs["rows_count"], 1)

    def test_agendamento_da_mes_nao_repete_fonte_já_conferida(self):
        session = FakeSession([registro()])
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_general_report_sync._source_status", return_value={
                 "rows_count": 1, "version": 68, "normalized_available": True,
                 "last_received_at": "2026-11-23T10:43:05+00:00",
             }), \
             patch("mes_general_report_sync.cron_deve_atualizar",
                   return_value=(False, "JA_CONFERIDO_HOJE")), \
             patch("mes_general_report_sync.store.save_report") as save:
            out = sincronizar_relatorio_geral(session=session, scheduled=True)
        self.assertEqual(out["status"], "JA_CONFERIDO_HOJE")
        self.assertEqual(out["versao"], 68)
        self.assertFalse(out["publicado"])
        self.assertFalse(session.calls)
        save.assert_not_called()

    def test_recupera_normalizacao_da_mesma_versao_sem_segundo_get(self):
        session = FakeSession([registro()])
        prepared = {
            "status": "PROCESSAR",
            "auditoria": {"total_recebido": 1, "registros_validos": 1,
                          "registros_pendentes": 0},
            "politica": {"motivos_protecao": []},
            "arquivo": b"excel-fixture", "sha256": "hash-atual",
            "linhas_fonte": 1, "pendencias_api": 0,
        }
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_general_report_sync.preparar_carga_mes",
                   return_value=prepared), \
             patch("mes_general_report_sync._source_status", side_effect=[
                 {"rows_count": 1, "version": 67, "content_sha256": "antigo",
                  "normalized_available": True},
                 {"rows_count": 1, "version": 68,
                  "content_sha256": "hash-atual",
                  "normalized_available": False},
             ]), \
             patch("mes_general_report_sync.store.save_report",
                   side_effect=RuntimeError("bruto salvo, normalização pendente")) as save, \
             patch("mes_general_report_sync.store.backfill_normalized_source") as backfill:
            out = sincronizar_relatorio_geral(session=session)
        self.assertTrue(out["publicado"])
        self.assertTrue(out["normalizado"])
        self.assertTrue(out["normalizacao_recuperada"])
        self.assertEqual(out["versao"], 68)
        self.assertEqual(len(session.calls), 1)
        save.assert_called_once()
        backfill.assert_called_once_with("relatorio_geral")

    def test_falha_estrutural_nao_publica(self):
        sample = FakeSession([registro(Code=None)] * 100)
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_TOKEN": "ficticio"}), \
             patch("mes_general_report_sync._source_status", return_value={
                 "rows_count": 100, "normalized_available": True,
             }), \
             patch("mes_general_report_sync.store.save_report") as save:
            result = sincronizar_relatorio_geral(session=sample)
            self.assertEqual(result["status"], "PROTEGER_BASE")
            self.assertFalse(result["publicado"])
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
