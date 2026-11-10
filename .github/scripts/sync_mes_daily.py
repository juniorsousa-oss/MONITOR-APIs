"""Executor diário da API MES — 07:20 America/Sao_Paulo (10:20 UTC)."""
from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mes_source_sync import sincronizar_api_mes  # noqa: E402


def main() -> int:
    if not os.getenv("SETTA_MES_GENERAL_REPORT_TOKEN", "").strip():
        print(
            "CONFIGURAÇÃO PENDENTE: cadastrar SETTA_MES_GENERAL_REPORT_TOKEN "
            "em GitHub Actions Secrets do repositório MONITOR-APIs."
        )
        return 2
    try:
        resultado = sincronizar_api_mes(forcar=False)
    except Exception as exc:
        # Evitar detalhes de HTTP, conteúdo MES, código de material ou tokens.
        print(
            "ERRO: sincronização MES não concluída; Central deve manter a última "
            f"base normalizada. Tipo: {type(exc).__name__}."
        )
        return 1
    print(
        f"MES {resultado['status']}: {resultado['registros']} válidos, "
        f"{resultado['quarentena']} em quarentena, "
        f"fonte publicada={resultado['publicado']}, "
        f"versão={resultado['versao']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
