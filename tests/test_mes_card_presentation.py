"""Regressão do cartão Relatório Geral e botão visível no próprio cartão."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from ui import mes_source_display

ROOT = Path(__file__).resolve().parents[1]


class MesCardTests(unittest.TestCase):
    def test_origem_legacy_mes_com_prova_http200_e_api_integrada(self):
        source = {
            "origin": "MES", "last_file_name": "RelatorioGeral-10-11-2026.xlsx",
            "api_active": False,
        }
        api = {"active": True, "status": "ONLINE", "last_success_at": "2026-11-10T12:00:00Z"}
        state = mes_source_display(source, api)
        self.assertEqual(state["badge"], "API INTEGRADA")
        self.assertTrue(state["connected"])
        self.assertFalse(state["published"])
        self.assertIn("PRIMEIRA CARGA", state["sync_label"])

    def test_publicacao_mes_e_reconhecida_pelo_nome_da_carga(self):
        state = mes_source_display({
            "origin": "MES", "last_file_name": "RelatorioGeral_MES.xlsx",
        }, {"status": "OFFLINE", "active": False})
        self.assertTrue(state["published"])
        self.assertEqual(state["badge"], "API INTEGRADA")
        self.assertEqual(state["mode"], "API AUTOMÁTICA · 07:20")

    def test_sem_conexao_nunca_afirma_primeira_carga_concluida(self):
        state = mes_source_display({
            "origin": "MES", "last_file_name": "RelatorioGeral-10-11-2026.xlsx",
        }, {"active": False})
        self.assertFalse(state["connected"])
        self.assertEqual(state["badge"], "API CONFIGURADA")
        self.assertFalse(state["published"])

    def test_banco_consulta_status_real_da_api_em_vez_de_catalogo(self):
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        database = next(
            fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
            and fn.name == "render_database"
        )
        db_source = ast.get_source_segment(source, database)
        self.assertIn(
            "monitor.hydrate_all(store.list_apis(include_demo=False))",
            db_source,
        )
        self.assertNotIn(
            "monitor.hydrate_all(store.system_apis())",
            db_source,
        )

    def test_mes_usa_a_mesma_estrutura_visual_dos_outros_cards(self):
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        card = next(
            fn for fn in tree.body
            if isinstance(fn, ast.FunctionDef)
            and fn.name == "_render_mes_report_card"
        )
        card_code = ast.get_source_segment(source, card)
        # Mesmo cabeçalho, chips e divisor do rodapé de source_card().
        for selector in (
            'class="source-top"',
            'class="source-name"',
            'class="source-meta"',
            'class="source-badge"',
            'class="source-origin"',
            'class="source-apps mes-source-footer"',
        ):
            self.assertIn(selector, card_code)
        self.assertNotIn("top, status_col = st.columns", card_code)
        self.assertNotIn("info, action = st.columns", card_code)
        self.assertIn('with st.popover(', card_code)

    def test_estilo_ancora_botao_no_rodape_sem_deslocar_conteudo(self):
        css = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn(".st-key-mes_general_source_card .mes-source-footer", css)
        self.assertIn('[data-testid="stPopover"]', css)
        self.assertIn("position:absolute!important", css)
        self.assertIn("@media(max-width:600px)", css)

    def test_acao_e_renderizada_na_mesma_unidade_visual(self):
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        card = next(
            fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
            and fn.name == "_render_mes_report_card"
        )
        database = next(
            fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
            and fn.name == "render_database"
        )
        card_code = ast.get_source_segment(source, card)
        database_code = ast.get_source_segment(source, database)
        self.assertIn("with st.container(border=True, key=\"mes_general_source_card\")", card_code)
        self.assertIn("with st.popover(", card_code)
        self.assertIn("CONFIRMAR REPROCESSAMENTO", card_code)
        self.assertIn("_render_mes_report_card(source, mes_receptor)", database_code)
        self.assertNotIn("RELATÓRIO GERAL · API MES", database_code)
        self.assertNotIn("mes_atualizar_agora", database_code)


if __name__ == "__main__":
    unittest.main()
