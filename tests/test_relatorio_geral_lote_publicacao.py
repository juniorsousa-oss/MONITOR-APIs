"""Regressão: nenhuma versão sem Batch/Lote substitui a fonte do Fechamento."""
from __future__ import annotations

import gzip
import json
import unittest
from unittest.mock import patch

import data_store as store


def pack(*, header, sheet="Geral"):
    value = {
        "format": "SETTA_SOURCE_V1",
        "source_key": "relatorio_geral",
        "sheets": [
            {"name": sheet, "rows": [header, ["26028901001", "00000441", "061638"]]}
        ],
    }
    return gzip.compress(json.dumps(value).encode("utf-8"))


class PublicacaoLoteTests(unittest.TestCase):
    def test_bloqueia_relatorio_sem_coluna_lote(self):
        with self.assertRaisesRegex(ValueError, "sem coluna Lote"):
            store._validar_lote_relatorio_geral(
                pack(header=["Projeto", "Código", "Descrição"])
            )

    def test_aceita_lote_e_batch(self):
        store._validar_lote_relatorio_geral(
            pack(header=["Projeto", "Código", "Lote"])
        )
        store._validar_lote_relatorio_geral(
            pack(header=["Projeto", "Código", "Batch"])
        )

    def test_cabecalho_pode_estar_na_segunda_linha(self):
        value = {
            "sheets": [{"name": "Relatório Geral", "rows": [
                ["Relatório MES"], ["Projeto", "Código", "Lote"]
            ]}],
        }
        normalized = gzip.compress(json.dumps(value).encode("utf-8"))
        store._validar_lote_relatorio_geral(normalized)

    def test_impede_commit_do_geral_sem_lote(self):
        normalized = pack(header=["Projeto", "Código", "Descrição"])
        with patch.object(
            store, "build_normalized_source", return_value=(normalized, 2)
        ), patch.object(store, "central_api_call") as api:
            with self.assertRaisesRegex(ValueError, "sem coluna Lote"):
                store.save_report(
                    "relatorio_geral", "RelatorioGeral_MES.xlsx", b"arquivo-teste",
                    rows_count=1,
                )
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
