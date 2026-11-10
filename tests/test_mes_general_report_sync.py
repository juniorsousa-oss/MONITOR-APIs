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
        self.assertEqual(out["linhas_fonte"], 201)
        self.assertEqual(out["linhas_excecao"], 1)
        self.assertIsInstance(out["arquivo"], bytes)
        self.assertGreater(len(out["arquivo"]), 100)
        import pandas as pd
        from io import BytesIO
        df = pd.read_excel(BytesIO(out["arquivo"]), sheet_name="Geral")
        quarantined = df[df["Código"].isna()]
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined.iloc[0]["Descrição"], "BASCULANTE")
        self.assertEqual(quarantined.iloc[0]["Qtd. necessária"], 1)
        faults = pd.read_excel(BytesIO(out["arquivo"]), sheet_name="Inconsistencias MES")
        self.assertEqual(len(faults), 1)

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
