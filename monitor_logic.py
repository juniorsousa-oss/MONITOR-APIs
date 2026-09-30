from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import data_store as store

TZ = ZoneInfo("America/Sao_Paulo")

# Chave anon/publica já utilizada pelos aplicativos SETTA neste projeto.
GESTAO_ENTREGAS_ANON_KEY = (
    os.getenv("GESTAO_ENTREGAS_SUPABASE_ANON_KEY", "").strip()
    or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1aXhhenB4a3ZuaXFsZG1tbnRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTYwNTMsImV4cCI6MjEwMzA5MjA1M30.jNFaIG1FcDYnMAoVaI23UYMuRL1BpZmuqu_LPEYb88E"
)


def _headers_from_secret(secret_ref: str) -> dict[str, str]:
    ref = str(secret_ref or "").strip()
    if ref == "__GESTAO_ENTREGAS_ANON__":
        return {
            "Authorization": f"Bearer {GESTAO_ENTREGAS_ANON_KEY}",
            "apikey": GESTAO_ENTREGAS_ANON_KEY,
            "Content-Type": "application/json",
        }
    if not ref:
        return {}

    raw = os.getenv(ref, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except Exception:
        pass
    return {"Authorization": f"Bearer {raw}"}


def _nf_materials_status(response: requests.Response, latency: float, api: dict) -> dict:
    expected = int(api.get("expected_status") or 200)
    valid_http = response.status_code == expected

    try:
        payload = response.json()
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    service_ok = payload.get("ok") is True
    available = payload.get("disponivel") is True
    warning_latency = max(1, int(api.get("warning_latency_ms") or 1500))

    if not valid_http or not service_ok:
        status = "OFFLINE"
    elif not available or latency >= warning_latency:
        status = "ATENÇÃO"
    else:
        status = "ONLINE"

    success = bool(valid_http and service_ok and available)
    details = {
        "carga_id": payload.get("carga_id"),
        "status_carga": payload.get("status"),
        "filtro": payload.get("filtro"),
        "origem": payload.get("origem"),
        "total_itens": payload.get("total_itens"),
        "total_produtos": payload.get("total_produtos"),
        "total_origem": payload.get("total_origem"),
        "total_validos": payload.get("total_validos"),
        "ultima_verificacao_em": payload.get("ultima_verificacao_em"),
        "ultima_verificacao_label": store.format_dt(
            payload.get("ultima_verificacao_em")
        ),
    }

    error = ""
    if not valid_http:
        error = f"HTTP {response.status_code}; esperado {expected}."
    elif not service_ok:
        error = str(payload.get("error") or "A API não confirmou o estado da integração.")
    elif not available:
        error = "Integração acessível, porém sem carga ativa."

    return {
        "status": status,
        "success": success,
        "http_status": int(response.status_code),
        "latency_ms": latency,
        "error_message": error,
        "integration_meta": details,
    }


def check_api(api: dict) -> dict:
    checked_at = store.now_iso()
    endpoint = str(api.get("endpoint") or "").strip()
    if not endpoint:
        return {
            "checked_at": checked_at,
            "status": "OFFLINE",
            "success": False,
            "http_status": None,
            "latency_ms": None,
            "error_message": "Endpoint não informado.",
        }

    method = str(api.get("method") or "GET").upper()
    timeout = max(1, int(api.get("timeout_seconds") or 10))
    expected = int(api.get("expected_status") or 200)
    warning_latency = max(1, int(api.get("warning_latency_ms") or 1000))
    headers = _headers_from_secret(str(api.get("secret_ref") or ""))

    start = time.perf_counter()
    try:
        response = requests.request(
            method=method,
            url=endpoint,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        latency = round((time.perf_counter() - start) * 1000, 2)

        if str(api.get("health_mode") or "") == "NF_MATERIAIS_STATUS":
            result = _nf_materials_status(response, latency, api)
            return {"checked_at": checked_at, **result}

        valid_status = response.status_code == expected
        if not valid_status:
            status = "OFFLINE"
        elif latency >= warning_latency:
            status = "ATENÇÃO"
        else:
            status = "ONLINE"
        return {
            "checked_at": checked_at,
            "status": status,
            "success": valid_status,
            "http_status": int(response.status_code),
            "latency_ms": latency,
            "error_message": (
                "" if valid_status
                else f"HTTP {response.status_code}; esperado {expected}."
            ),
        }
    except requests.RequestException as exc:
        latency = round((time.perf_counter() - start) * 1000, 2)
        return {
            "checked_at": checked_at,
            "status": "OFFLINE",
            "success": False,
            "http_status": None,
            "latency_ms": latency,
            "error_message": f"{type(exc).__name__}: {exc}",
        }


def run_check(api: dict) -> dict:
    api_id = str(api.get("id") or "")
    if not api_id:
        return api

    result = check_api(api)

    # Integrações de sistema são consultadas diretamente na origem.
    # Não dependem das tabelas internas do Monitor para aparecerem na tela.
    if api_id.startswith("system-"):
        return {
            **api,
            **result,
            "last_check_at": result.get("checked_at"),
            "last_success_at": (
                result.get("checked_at") if result.get("success") else None
            ),
            "last_check_label": store.format_dt(result.get("checked_at")),
            "last_success_label": (
                store.format_dt(result.get("checked_at"))
                if result.get("success")
                else "—"
            ),
            "consecutive_failures": 0 if result.get("success") else 1,
            "latency_history": (
                [result.get("latency_ms")]
                if result.get("latency_ms") is not None
                else []
            ),
        }

    store.save_check(api_id, result)

    previous_failures = int(api.get("consecutive_failures") or 0)
    success = bool(result["success"])
    runtime = {
        "status": result["status"],
        "last_check_at": result["checked_at"],
        "last_http_status": result.get("http_status"),
        "last_latency_ms": result.get("latency_ms"),
        "consecutive_failures": 0 if success else previous_failures + 1,
    }

    if success:
        runtime["last_success_at"] = result["checked_at"]
        store.resolve_incidents(api_id)
        if result["status"] == "ATENÇÃO":
            store.open_incident(
                api_id,
                str(api.get("name") or "API"),
                "LATÊNCIA",
                f"Latência elevada: {result.get('latency_ms')} ms.",
            )
    else:
        runtime["last_failure_at"] = result["checked_at"]
        store.open_incident(
            api_id,
            str(api.get("name") or "API"),
            "INDISPONIBILIDADE",
            result.get("error_message") or "Falha de comunicação.",
        )

    store.update_api_runtime(api_id, runtime)
    return {**api, **runtime, **result}


def run_all_checks() -> list[dict]:
    results = []
    for api in store.list_apis(include_demo=False):
        if not bool(api.get("active", True)):
            continue
        results.append(run_check(api))
    return results


def hydrate_api(api: dict) -> dict:
    api_id = str(api.get("id") or "")
    if api_id.startswith("system-"):
        return run_check(api)

    checks = store.list_checks(api_id, limit=160)
    recent_24h = []
    cutoff = datetime.now(TZ) - timedelta(hours=24)
    for check in checks:
        dt = store.parse_dt(check.get("checked_at"))
        if dt and dt >= cutoff:
            recent_24h.append(check)

    if recent_24h:
        successes = sum(1 for x in recent_24h if bool(x.get("success")))
        uptime = (successes / len(recent_24h)) * 100
    else:
        uptime = None

    history = [
        float(x.get("latency_ms"))
        for x in reversed(checks[:12])
        if x.get("latency_ms") is not None
    ]
    return {
        **api,
        "status": (
            "DESATIVADA"
            if not bool(api.get("active", True))
            else str(api.get("status") or "SEM DADOS")
        ),
        "latency_ms": api.get("last_latency_ms"),
        "http_status": api.get("last_http_status"),
        "uptime_24h": uptime,
        "latency_history": history,
        "last_check_label": store.format_dt(api.get("last_check_at")),
        "last_success_label": store.format_dt(api.get("last_success_at")),
    }


def hydrate_all(apis: list[dict]) -> list[dict]:
    return [hydrate_api(dict(api)) for api in apis]
