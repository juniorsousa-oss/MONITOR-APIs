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


def _central_action_status(response: requests.Response, latency: float, api: dict) -> dict:
    expected = int(api.get("expected_status") or 200)
    valid_http = response.status_code == expected
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    service_ok = payload.get("ok") is True
    warning_latency = max(1, int(api.get("warning_latency_ms") or 1000))
    if not valid_http or not service_ok:
        status = "OFFLINE"
    elif latency >= warning_latency:
        status = "ATENÇÃO"
    else:
        status = "ONLINE"
    error = ""
    if not valid_http:
        error = f"HTTP {response.status_code}; esperado {expected}."
    elif not service_ok:
        error = str(payload.get("error") or "A Central não confirmou a operação.")
    return {
        "status": status,
        "success": bool(valid_http and service_ok),
        "http_status": int(response.status_code),
        "latency_ms": latency,
        "error_message": error,
    }


def _central_derived_download_status(
    response: requests.Response,
    start: float,
    api: dict,
) -> dict:
    base_result = _central_action_status(
        response,
        round((time.perf_counter() - start) * 1000, 2),
        api,
    )
    if not base_result["success"]:
        return base_result

    try:
        payload = response.json()
    except Exception:
        payload = {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    data = data if isinstance(data, dict) else {}
    signed_url = str(data.get("signed_url") or "").strip()
    if not signed_url:
        return {
            **base_result,
            "status": "OFFLINE",
            "success": False,
            "error_message": "A Central respondeu, mas não retornou URL de leitura do Storage.",
        }

    storage_http = None
    try:
        storage_response = requests.get(
            signed_url,
            headers={"Range": "bytes=0-0"},
            timeout=min(15, max(3, int(api.get("timeout_seconds") or 15))),
            allow_redirects=True,
            stream=True,
        )
        storage_http = int(storage_response.status_code)
        storage_ok = storage_http in {200, 206}
        storage_response.close()
    except requests.RequestException as exc:
        latency = round((time.perf_counter() - start) * 1000, 2)
        return {
            **base_result,
            "status": "OFFLINE",
            "success": False,
            "latency_ms": latency,
            "error_message": f"Storage: {type(exc).__name__}: {exc}",
            "integration_meta": {"storage_http_status": storage_http},
        }

    latency = round((time.perf_counter() - start) * 1000, 2)
    warning_latency = max(1, int(api.get("warning_latency_ms") or 2500))
    status = (
        "OFFLINE"
        if not storage_ok
        else "ATENÇÃO"
        if latency >= warning_latency
        else "ONLINE"
    )
    return {
        **base_result,
        "status": status,
        "success": bool(storage_ok),
        "latency_ms": latency,
        "error_message": "" if storage_ok else f"Storage HTTP {storage_http}.",
        "integration_meta": {
            "storage_http_status": storage_http,
            "base_key": (
                (api.get("request_json") or {}).get("payload") or {}
            ).get("base_key"),
        },
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
        request_kwargs = {
            "method": method,
            "url": endpoint,
            "headers": headers,
            "timeout": timeout,
            "allow_redirects": True,
        }
        if api.get("request_json") is not None:
            request_kwargs["json"] = api.get("request_json")
        response = requests.request(**request_kwargs)
        latency = round((time.perf_counter() - start) * 1000, 2)

        health_mode = str(api.get("health_mode") or "")
        if health_mode == "NF_MATERIAIS_STATUS":
            result = _nf_materials_status(response, latency, api)
            return {"checked_at": checked_at, **result}
        if health_mode == "CENTRAL_ACTION":
            result = _central_action_status(response, latency, api)
            return {"checked_at": checked_at, **result}
        if health_mode == "CENTRAL_DERIVED_DOWNLOAD":
            result = _central_derived_download_status(response, start, api)
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

    persistence_error = ""
    try:
        store.save_check(api_id, result)
    except Exception as exc:
        persistence_error = f"{type(exc).__name__}: {exc}"

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

    try:
        store.update_api_runtime(api_id, runtime)
    except Exception as exc:
        if not persistence_error:
            persistence_error = f"{type(exc).__name__}: {exc}"
    merged = {**api, **runtime, **result}
    if persistence_error:
        meta = dict(merged.get("integration_meta") or {})
        meta["monitor_persistence_error"] = persistence_error
        merged["integration_meta"] = meta
    return merged


def run_all_checks() -> list[dict]:
    results = []
    for api in store.list_apis(include_demo=False):
        if not bool(api.get("active", True)):
            continue
        results.append(run_check(api))
    return results


def restart_api(api: dict, attempts: int = 3, pause_seconds: float = 0.8) -> dict:
    """
    Executa um ciclo de recuperação da API com conexões novas.

    O objetivo é recuperar falhas transitórias de rede/timeout sem esconder
    erros estruturais: se a origem continuar respondendo com erro, o estado
    permanece OFFLINE e a causa continua visível no monitor.
    """
    current = dict(api)
    attempts = max(1, min(int(attempts or 1), 3))
    pause_seconds = max(0.0, min(float(pause_seconds or 0.0), 2.0))

    for attempt in range(1, attempts + 1):
        current = run_check(current)
        current["restart_attempts"] = attempt
        if bool(current.get("success")):
            break
        if attempt < attempts and pause_seconds:
            time.sleep(pause_seconds)

    return current


def _hydrate_from_checks(api: dict, checks: list[dict]) -> dict:
    if checks:
        successes = sum(1 for item in checks if bool(item.get("success")))
        uptime = (successes / len(checks)) * 100
    else:
        uptime = None

    history = [
        float(item.get("latency_ms"))
        for item in reversed(checks[:12])
        if item.get("latency_ms") is not None
    ]
    return {
        **api,
        "status": (
            "DESATIVADA"
            if not bool(api.get("active", True))
            else str(api.get("status") or "SEM DADOS")
        ),
        "latency_ms": api.get("last_latency_ms", api.get("latency_ms")),
        "http_status": api.get("last_http_status", api.get("http_status")),
        "uptime_24h": uptime,
        "uptime_samples": len(checks),
        "latency_history": history,
        "last_check_label": store.format_dt(api.get("last_check_at")),
        "last_success_label": store.format_dt(api.get("last_success_at")),
    }


def hydrate_api(api: dict) -> dict:
    api_id = str(api.get("id") or "")
    cutoff = datetime.now(TZ) - timedelta(hours=24)
    checks = store.list_check_summary(
        api_id,
        cutoff.isoformat(),
        limit=2000,
    )
    return _hydrate_from_checks(api, checks)



def hydrate_all(apis: list[dict]) -> list[dict]:
    normalized = [dict(api) for api in apis]
    cutoff = datetime.now(TZ) - timedelta(hours=24)
    ids = [str(api.get("id") or "") for api in normalized]
    grouped = store.list_check_summaries(
        ids,
        cutoff.isoformat(),
        limit=max(2000, len(ids) * 1600),
    )
    return [
        _hydrate_from_checks(api, grouped.get(str(api.get("id") or ""), []))
        for api in normalized
    ]
