"""Retornos seguros no reprocessamento manual da MES."""
import unittest

from mes_sync_diagnostics import diagnosticar_erro_mes


class MesDiagnosticTests(unittest.TestCase):
    def test_ambiente_streamlit_sem_credencial_mes(self):
        item = diagnosticar_erro_mes(RuntimeError("Token MES ausente no ambiente executor."))
        self.assertEqual(item["codigo"], "MES_CREDENCIAL_STREAMLIT")

    def test_http_recusado(self):
        item = diagnosticar_erro_mes(ValueError("Consulta retornou HTTP 503."))
        self.assertEqual(item["codigo"], "MES_HTTP_503")

    def test_erro_generico_nao_reproduz_dado_sensivel(self):
        item = diagnosticar_erro_mes(RuntimeError("Bearer 123 senha secreta"))
        self.assertIn("MES_INESPERADO", item["codigo"])
        self.assertNotIn("senha", str(item))
        self.assertNotIn("123", str(item))

    def test_limite_resposta(self):
        item = diagnosticar_erro_mes(ValueError("Relatório excede o tamanho máximo autorizado."))
        self.assertEqual(item["codigo"], "MES_TAMANHO_LIMITE")


if __name__ == "__main__":
    unittest.main()
