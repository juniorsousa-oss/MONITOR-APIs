"""Agendamento redundante, proteção do botão e estado da base tratada.

Não consulta MES, Supabase ou GitHub; todas as datas são simuladas.
"""
from __future__ import annotations

from datetime import datetime
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from mes_refresh_flow import (
    ManualRefreshGuard,
    cron_deve_atualizar,
    estado_relatorio_tratado,
)


TZ = ZoneInfo("America/Sao_Paulo")


class ScheduledMesTests(TestCase):
    def test_agendamento_antes_das_0720_nao_busca_mes(self):
        allowed, label = cron_deve_atualizar(
            {}, now=datetime(2026, 11, 23, 7, 19, tzinfo=TZ),
        )
        self.assertFalse(allowed)
        self.assertEqual(label, "ANTES_DA_JANELA_0720")

    def test_agendamento_apos_0720_baixa_se_sem_conferencia_do_dia(self):
        source = {
            "normalized_available": True,
            "last_received_at": "2026-11-22T18:00:00Z",
        }
        allowed, label = cron_deve_atualizar(
            source, now=datetime(2026, 11, 23, 7, 21, tzinfo=TZ),
        )
        self.assertTrue(allowed)
        self.assertEqual(label, "ATUALIZAR")

    def test_nao_reprocessa_mes_no_mesmo_dia_apos_sucesso(self):
        source = {
            "normalized_available": True,
            "last_received_at": "2026-11-23T10:43:05+00:00",
            "version": 68,
        }
        allowed, label = cron_deve_atualizar(
            source, now=datetime(2026, 11, 23, 11, 20, tzinfo=TZ),
        )
        self.assertFalse(allowed)
        self.assertEqual(label, "JA_CONFERIDO_HOJE")

    def test_recibo_das_0600_evitaria_segunda_consulta_as_0720(self):
        for receipt in ("2026-11-23T09:00:00Z", "2026-11-23T06:18:00-03:00"):
            with self.subTest(receipt=receipt):
                result = cron_deve_atualizar(
                    {"normalized_available": True, "last_received_at": receipt,
                     "last_update_at": "2026-11-22T09:00:00Z"},
                    now=datetime(2026, 11, 23, 7, 20, tzinfo=TZ),
                )
                self.assertEqual(result, (False, "JA_CONFERIDO_HOJE"))

    def test_recibos_antes_da_rotina_ou_do_futuro_nao_bloqueiam_recuperacao(self):
        for receipt in ("2026-11-23T08:59:59Z", "2026-11-23T10:20:01Z"):
            with self.subTest(receipt=receipt):
                result = cron_deve_atualizar(
                    {"normalized_available": True, "last_received_at": receipt},
                    now=datetime(2026, 11, 23, 7, 20, tzinfo=TZ),
                )
                self.assertEqual(result, (True, "ATUALIZAR"))

    def test_arquivo_bruto_sem_normalizacao_exige_recuperacao(self):
        source = {
            "normalized_available": False,
            "last_received_at": "2026-11-23T10:43:05Z",
        }
        allowed, _ = cron_deve_atualizar(
            source, now=datetime(2026, 11, 23, 9, 20, tzinfo=TZ),
        )
        self.assertTrue(allowed)

    def test_agendamento_ignora_execucao_noturna_atrasada_sem_trocar_dia(self):
        source = {
            "normalized_available": True,
            "last_received_at": "2026-11-22T23:59:00-03:00",
        }
        allowed, _ = cron_deve_atualizar(
            source, now=datetime(2026, 11, 23, 7, 45, tzinfo=TZ),
        )
        self.assertTrue(allowed)


class BaseTratadaTests(TestCase):
    def test_fonte_publicada_nao_significa_tratado_publicado(self):
        stage, treated_version = estado_relatorio_tratado(
            68,
            {"status": "DESATUALIZADO",
             "source_versions": {"relatorio_geral": 67}},
        )
        self.assertEqual(stage, "PROCESSANDO")
        self.assertEqual(treated_version, 67)

    def test_so_conclui_quando_tratado_atinge_versao_alvo(self):
        stage, treated_version = estado_relatorio_tratado(
            68,
            {"status": "ATUALIZADO",
             "source_versions": {"relatorio_geral": 68}},
        )
        self.assertEqual(stage, "CONCLUIDO")
        self.assertEqual(treated_version, 68)

    def test_erro_do_conversor_nao_dispara_novo_get_mes(self):
        stage, _ = estado_relatorio_tratado(
            68,
            {"status": "ERRO", "stored_status": "ERRO",
             "source_versions": {"relatorio_geral": 67}},
        )
        self.assertEqual(stage, "ERRO_CONVERSOR")


class ManualRefreshGuardTests(TestCase):
    def test_bloqueia_segunda_consulta_durante_execucao_e_depois(self):
        guard = ManualRefreshGuard(cooldown_seconds=120)
        with patch("mes_refresh_flow.monotonic", return_value=1000):
            self.assertEqual(guard.begin(), (True, "INICIAR"))
            self.assertEqual(guard.begin(), (False, "EM_EXECUCAO"))
            guard.finish(success=True)
        with patch("mes_refresh_flow.monotonic", return_value=1010):
            self.assertEqual(guard.begin(), (False, "CONFERENCIA_RECENTE"))
        with patch("mes_refresh_flow.monotonic", return_value=1200):
            self.assertEqual(guard.begin(), (True, "INICIAR"))
            guard.finish(success=False)

    def test_erro_desbloqueia_execucao(self):
        guard = ManualRefreshGuard(cooldown_seconds=30)
        self.assertTrue(guard.begin()[0])
        guard.finish(success=False)
        self.assertTrue(guard.begin()[0])
        guard.finish(success=False)
