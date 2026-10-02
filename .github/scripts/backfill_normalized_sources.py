from __future__ import annotations

import sys

import data_store as store


def main() -> int:
    sources = store.list_sources()
    pending = [
        item
        for item in sources
        if bool(item.get("available"))
        and not bool(item.get("normalized_available"))
    ]

    if not pending:
        print("Todas as fontes disponíveis já estão normalizadas.")
        return 0

    failures: list[tuple[str, str]] = []
    for index, source in enumerate(pending, start=1):
        key = str(source.get("source_key") or "")
        name = str(source.get("name") or key)
        print(f"[{index}/{len(pending)}] Normalizando {name} ({key})...")
        try:
            result = store.backfill_normalized_source(key)
            print(
                f"OK {key} · versão {result.get('source_version')} · "
                f"{result.get('rows_count')} linhas"
            )
        except Exception as exc:
            failures.append((key, str(exc)))
            print(f"ERRO {key}: {exc}")

    if failures:
        print("\nFalhas:")
        for key, error in failures:
            print(f"- {key}: {error}")
        return 1

    print(f"Concluído: {len(pending)} fonte(s) normalizada(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
