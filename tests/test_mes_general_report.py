"""Monitor MES: a credencial jamais deve ser publicada ou gravada em logs."""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

import data_store
import monitor_logic
from mes_general_report import check_general_report, TOKEN_ENV, AUTH_SCHEME_ENV
from zoneinfo import ZoneInfo


class FakeResponse:
    def __init__(self, status=200, ct="application/json", body=b'[{"ok":true}]'):
        self.status_code = status
        self.headers = {"Content-Type": ct}
        self.body = body
        self.closed = False

    def iter_content(self, chunk_size=1024):
        if self.body:
            yield self.body[:chunk_size]

    def close(self):
        self.closed = True


class FakeRequester:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class MesGeneralReportTests(unittest.TestCase):
    def test_fonte_cadastrada_inativa_sem_liberacao(self):
        with patch.dict(os.environ, {"SETTA_MES_GENERAL_REPORT_ENABLED": "0"}):
            entries = [r for r in data_store.system_apis() if r.get("health_mode") == "MES_GENERAL_REPORT"]
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["active"])
        self.assertEqual(entries[0]["secret_ref"], TOKEN_ENV)
        self.assertEqual(entries[0]["method"], "GET")
        self.assertNotIn("Authorization", entries[0])

    def test_sem_token_nao_faz_requisicao(self):
        requester = FakeRequester(FakeResponse())
        with patch.dict(os.environ, {TOKEN_ENV: ""}):
            value = check_general_report(session=requester)
        self.assertFalse(value["success"])
        self.assertEqual(value["incident_kind"], "CONFIGURAÇÃO")
        self.assertEqual(requester.calls, [])

    def test_bearer_em_header_e_credencial_ausente_do_resultado(self):
        requester = FakeRequester(FakeResponse())
        with patch.dict(os.environ, {TOKEN_ENV: "teste-somente-local"}):
            value = check_general_report(session=requester)
        self.assertTrue(value["success"])
        self.assertIn(value["status"], ("ONLINE", "ATENÇÃO"))
        self.assertTrue(requester.response.closed)
        _, options = requester.calls[0]
        self.assertEqual(options["headers"]["Authorization"], "Bearer teste-somente-local")
        self.assertTrue(options["stream"])
        self.assertFalse(options["allow_redirects"])
        self.assertNotIn("teste-somente-local", str(value))

    def test_esquema_legado_basic_nao_sobrescreve_bearer_confirmado(self):
        requester = FakeRequester(FakeResponse())
        with patch.dict(os.environ, {TOKEN_ENV: "token-ficticio", AUTH_SCHEME_ENV: "Basic"}):
            result = check_general_report(session=requester)
        self.assertTrue(result["success"])
        self.assertEqual(requester.calls[0][1]["headers"]["Authorization"], "Bearer token-ficticio")
        self.assertEqual(requester.calls[0][1]["headers"]["Accept"], "*/*")
        self.assertNotIn("token-ficticio", str(result))

    def test_tempos_suportam_execucao_de_30_segundos(self):
        requester = FakeRequester(FakeResponse())
        with patch.dict(os.environ, {TOKEN_ENV: "token-ficticio"}):
            result = check_general_report(timeout_seconds=25, session=requester)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(requester.calls[0][1]["timeout"][1], 60)
        assert len(requester.calls) == 1


    def test_http_500_nao_expoe_o_conteudo_do_servidor(self):
        requester = FakeRequester(FakeResponse(status=500, body=b"internal trace, secret info"))
        with patch.dict(os.environ, {TOKEN_ENV: "token-ficticio", AUTH_SCHEME_ENV: "Bearer"}):
            result = check_general_report(session=requester)
        self.assertFalse(result["success"])
        self.assertEqual(result["http_status"], 500)
        self.assertIn("HTTP 500", result["error_message"])
        self.assertIn("application/json", result["error_message"])
        self.assertNotIn("internal trace", str(result))
        self.assertNotIn("token-ficticio", str(result))

    def test_http_500_retorna_request_id_somente_quando_seguro(self):
        response = FakeResponse(status=500)
        response.headers["X-Request-ID"] = "trace-abc-123"
        requester = FakeRequester(response)
        with patch.dict(os.environ, {TOKEN_ENV: "token-ficticio"}):
            result = check_general_report(session=requester)
        self.assertEqual(result["http_status"], 500)
        self.assertIn("trace-abc-123", result["error_message"])
        self.assertNotIn("token-ficticio", str(result))

    def test_reiniciar_mes_uma_unica_vez(self):
        api = {"id": "teste-mes", "health_mode": "MES_GENERAL_REPORT"}
        with patch.object(monitor_logic, "run_check", return_value={"success": False, "status": "OFFLINE"}) as mocked:
            result = monitor_logic.restart_api(api, attempts=3, pause_seconds=0)
        self.assertEqual(result["restart_attempts"], 1)
        mocked.assert_called_once()

    def test_redirect_nao_e_seguido(self):
        requester = FakeRequester(FakeResponse(302))
        with patch.dict(os.environ, {TOKEN_ENV: "somente-teste"}):
            result = check_general_report(session=requester)
        self.assertFalse(result["success"])
        self.assertTrue(requester.response.closed)
        self.assertEqual(result["http_status"], 302)

    def test_200_html_nao_valida_relatorio(self):
        requester = FakeRequester(FakeResponse(ct="text/html", body=b"<html>login</html>"))
        with patch.dict(os.environ, {TOKEN_ENV: "somente-teste"}):
            result = check_general_report(session=requester)
        self.assertFalse(result["success"])
        self.assertEqual(result["incident_kind"], "FORMATO INVÁLIDO")

    def test_200_vazio_nao_valida_relatorio(self):
        requester = FakeRequester(FakeResponse(body=b""))
        with patch.dict(os.environ, {TOKEN_ENV: "somente-teste"}):
            result = check_general_report(session=requester)
        self.assertFalse(result["success"])
        self.assertEqual(result["incident_kind"], "RESPOSTA VAZIA")

    def test_reutiliza_status_sem_nova_consulta_ate_30_minutos(self):
        api = {
            "id": "teste-mes", "active": True,
            "health_mode": "MES_GENERAL_REPORT",
            "last_check_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
        }
        with patch.object(monitor_logic.store, "list_apis", return_value=[api]), \
             patch.object(monitor_logic, "run_check") as mocked:
            self.assertEqual(monitor_logic.run_all_checks(), [])
            mocked.assert_not_called()

    def test_health_mode_usa_probe_especifico(self):
        with patch("mes_general_report.check_general_report", return_value={"status": "ONLINE", "success": True}) as mocked:
            result = monitor_logic.check_api({
                "id": "teste-mes", "health_mode": "MES_GENERAL_REPORT",
                "endpoint": "https://mes.settadigital.com/rest/v1/GeneralReport?Company=01&Branch=0201",
                "timeout_seconds": 25, "warning_latency_ms": 2500,
            })
        self.assertEqual(result["status"], "ONLINE")
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertGreaterEqual(kwargs["timeout_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
