"""Controle de sincronização MES: uma consulta e acompanhamento do tratado.

Nenhum segredo ou dado fiscal é armazenado neste módulo.
"""
from __future__ import annotations

from datetime import datetime, time
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
BUSINESS_CUTOFF = time(7, 20)


def cron_deve_atualizar(source: dict, *, now: datetime | None = None) -> tuple[bool, str]:
    """Cron redundante: processar só depois das 07:20 e uma vez por dia.

    Eventuais atrasos do scheduler não geram novas versões por repetição;
    uma fonte sem normalização concluída sempre pode ser recuperada.
    """
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    now = now.astimezone(TZ)
    if now.time() < BUSINESS_CUTOFF:
        return False, "ANTES_DA_JANELA_0720"
    if source.get("normalized_available"):
        raw = source.get("last_received_at") or source.get("last_update_at")
        if raw:
            try:
                received = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if received.tzinfo is None:
                    received = received.replace(tzinfo=TZ)
                received = received.astimezone(TZ)
                if (received.date() == now.date()
                        and received.time() >= BUSINESS_CUTOFF):
                    return False, "JA_CONFERIDO_HOJE"
            except (TypeError, ValueError):
                pass
    return True, "ATUALIZAR"


def estado_relatorio_tratado(
    source_version: int,
    derived: dict,
) -> tuple[str, int]:
    """Separa publicação da fonte de conclusão do Conversor MRP."""
    used = derived.get("source_versions") or {}
    try:
        processed = int(used.get("relatorio_geral") or 0)
    except (ValueError, TypeError, AttributeError):
        processed = 0
    if int(source_version or 0) <= 0:
        return "AGUARDANDO_FONTE", processed
    if (processed >= int(source_version)
            and str(derived.get("status") or "").upper() == "ATUALIZADO"):
        return "CONCLUIDO", processed
    if str(derived.get("stored_status") or "").upper() in {"ERRO", "FALHA"}:
        return "ERRO_CONVERSOR", processed
    return "PROCESSANDO", processed


class ManualRefreshGuard:
    """Limita consultas caras MES por processo, sem PIN adicional.

    Usar via st.cache_resource() para compartilhar entre sessões da instância.
    Outras instâncias devem manter proteção própria na Central/API.
    """
    def __init__(self, cooldown_seconds: int = 120):
        self._lock = Lock()
        self._last_success_at: float | None = None
        self._cooldown = max(30, cooldown_seconds)

    def begin(self) -> tuple[bool, str]:
        if not self._lock.acquire(blocking=False):
            return False, "EM_EXECUCAO"
        if (self._last_success_at is not None
                and monotonic() - self._last_success_at < self._cooldown):
            self._lock.release()
            return False, "CONFERENCIA_RECENTE"
        return True, "INICIAR"

    def finish(self, *, success: bool) -> None:
        try:
            if success:
                self._last_success_at = monotonic()
        finally:
            self._lock.release()
