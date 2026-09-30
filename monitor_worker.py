from __future__ import annotations

import argparse
import time

import monitor_logic as monitor


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker 24/7 do Monitor de APIs SETTA")
    parser.add_argument("--loop", action="store_true", help="Executa continuamente.")
    parser.add_argument("--interval", type=int, default=60, help="Intervalo entre ciclos em segundos.")
    args = parser.parse_args()

    if not args.loop:
        results = monitor.run_all_checks()
        print(f"Ciclo concluído: {len(results)} API(s) verificadas.")
        return

    interval = max(30, int(args.interval))
    print(f"Monitor SETTA iniciado. Intervalo: {interval}s.")
    while True:
        started = time.time()
        try:
            results = monitor.run_all_checks()
            print(f"Ciclo concluído: {len(results)} API(s) verificadas.")
        except Exception as exc:
            print(f"Falha no ciclo do monitor: {type(exc).__name__}: {exc}")
        elapsed = time.time() - started
        time.sleep(max(1, interval - elapsed))


if __name__ == "__main__":
    main()
