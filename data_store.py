from __future__ import annotations

import io
import json
import os
import uuid

import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).parent
RUNTIME = ROOT / ".runtime"
LOCAL_FILE = RUNTIME / "monitor_data.json"
UPLOAD_DIR = RUNTIME / "uploads"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

CENTRAL_SUPABASE_URL = "https://cuixazpxkvniqldmmnth.supabase.co"
CENTRAL_SUPABASE_ANON_KEY = (
    os.getenv("SETTA_SUPABASE_ANON_KEY", "").strip()
    or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1aXhhenB4a3ZuaXFsZG1tbnRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTYwNTMsImV4cCI6MjEwMzA5MjA1M30.jNFaIG1FcDYnMAoVaI23UYMuRL1BpZmuqu_LPEYb88E"
)
CENTRAL_EDGE_URL = f"{CENTRAL_SUPABASE_URL}/functions/v1/setta-data-api"

_client = None


def now_iso() -> str:
    return datetime.now(TZ).isoformat()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(TZ)
    except Exception:
        return None


def format_dt(value: Any) -> str:
    dt = parse_dt(value)
    return dt.strftime("%d/%m/%Y %H:%M:%S") if dt else "—"


def central_api_call(action: str, payload: dict | None = None, timeout: int = 60) -> dict:
    response = requests.post(
        CENTRAL_EDGE_URL,
        headers={
            "Authorization": f"Bearer {CENTRAL_SUPABASE_ANON_KEY}",
            "apikey": CENTRAL_SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"action": action, "payload": payload or {}},
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "error": response.text or f"HTTP {response.status_code}"}
    if not response.ok or not data.get("ok"):
        raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
    return data


def central_client():
    from supabase import create_client
    return create_client(CENTRAL_SUPABASE_URL, CENTRAL_SUPABASE_ANON_KEY)


def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def get_client():
    global _client
    if not supabase_enabled():
        return None
    if _client is None:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def _default_local() -> dict:
    return {
        "apis": [],
        "checks": [],
        "incidents": [],
        "sources": [],
        "imports": [],
        "visual_config": {},
    }


def _load_local() -> dict:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if not LOCAL_FILE.exists():
        return _default_local()
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
        base = _default_local()
        base.update(data if isinstance(data, dict) else {})
        return base
    except Exception:
        return _default_local()


def _save_local(data: dict) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def system_apis() -> list[dict]:
    central_endpoint = CENTRAL_EDGE_URL
    return [
        {
            "id": "11111111-1111-4111-8111-111111111101",
            "name": "CENTRAL DE DADOS SETTA",
            "app_name": "Saúde da Edge Function principal",
            "endpoint": central_endpoint + "/health",
            "method": "GET",
            "expected_status": 200,
            "timeout_seconds": 15,
            "warning_latency_ms": 1200,
            "active": True,
            "secret_ref": "__GESTAO_ENTREGAS_ANON__",
            "system": True,
            "source_app": "MONITOR DE APIs",
            "target_app": "CENTRAL DE DADOS SETTA",
            "service": "Supabase Edge Function",
            "resource": "setta-data-api /health",
            "code_location": "MONITOR-APIs/data_store.py",
        },
        {
            "id": "11111111-1111-4111-8111-111111111102",
            "name": "MRP → CENTRAL DE DADOS",
            "app_name": "Leitura das bases que alimentam o MRP",
            "endpoint": central_endpoint,
            "method": "POST",
            "expected_status": 200,
            "timeout_seconds": 20,
            "warning_latency_ms": 1800,
            "active": True,
            "secret_ref": "__GESTAO_ENTREGAS_ANON__",
            "health_mode": "CENTRAL_ACTION",
            "request_json": {
                "action": "bundle_state",
                "payload": {
                    "source_keys": ["cadastros"],
                    "derived_keys": [
                        "relatorio_geral_tratado",
                        "estoque_tratado",
                        "compras_tratado",
                        "tctp_tratado",
                        "relatorio_mrp",
                    ],
                },
            },
            "system": True,
            "source_app": "MRP",
            "target_app": "CENTRAL DE DADOS SETTA",
            "service": "Supabase Edge Function",
            "resource": "setta-data-api · bundle_state",
            "code_location": "MRP/central_mrp_data.py",
        },
        {
            "id": "11111111-1111-4111-8111-111111111103",
            "name": "CONVERSOR MRP → CENTRAL",
            "app_name": "Estado dos relatórios de origem e bases tratadas",
            "endpoint": central_endpoint,
            "method": "POST",
            "expected_status": 200,
            "timeout_seconds": 20,
            "warning_latency_ms": 1800,
            "active": True,
            "secret_ref": "__GESTAO_ENTREGAS_ANON__",
            "health_mode": "CENTRAL_ACTION",
            "request_json": {
                "action": "pipeline_state",
                "payload": {
                    "source_keys": ["relatorio_geral", "for001", "for022"],
                    "derived_key": "relatorio_geral_tratado",
                },
            },
            "system": True,
            "source_app": "CONVERSOR MRP",
            "target_app": "CENTRAL DE DADOS SETTA",
            "service": "Supabase Edge Function",
            "resource": "setta-data-api · pipeline_state",
            "code_location": "MRP-CONVERSOR/central_data.py · pipeline_sync.py",
        },
        {
            "id": "11111111-1111-4111-8111-111111111104",
            "name": "CENTRAL → STORAGE MRP",
            "app_name": "Disponibilização das bases tratadas",
            "endpoint": central_endpoint,
            "method": "POST",
            "expected_status": 200,
            "timeout_seconds": 25,
            "warning_latency_ms": 2500,
            "active": True,
            "secret_ref": "__GESTAO_ENTREGAS_ANON__",
            "health_mode": "CENTRAL_DERIVED_DOWNLOAD",
            "request_json": {
                "action": "derived_download",
                "payload": {"base_key": "relatorio_geral_tratado"},
            },
            "system": True,
            "source_app": "CENTRAL DE DADOS SETTA",
            "target_app": "SUPABASE STORAGE",
            "service": "Supabase Storage",
            "resource": "bucket setta-data · relatorio_geral_tratado",
            "code_location": "MRP/central_mrp_data.py · MRP-CONVERSOR/central_data.py",
        },
        {
            "id": "11111111-1111-4111-8111-111111111105",
            "name": "GESTÃO DE ENTREGAS — OPERACIONAL",
            "app_name": "Cronograma • Central • Sincronização",
            "endpoint": (
                "https://cuixazpxkvniqldmmnth.supabase.co/"
                "functions/v1/entrega-cronograma-api/health"
            ),
            "method": "GET",
            "expected_status": 200,
            "timeout_seconds": 15,
            "warning_latency_ms": 1200,
            "active": True,
            "secret_ref": "__GESTAO_ENTREGAS_ANON__",
            "system": True,
            "source_app": "GESTÃO DE ENTREGAS",
            "target_app": "CENTRAL DE DADOS SETTA",
            "service": "Supabase Edge Function",
            "resource": "entrega-cronograma-api /health",
            "code_location": "Gestão de Entregas · integração operacional",
        },
        {
            "id": "11111111-1111-4111-8111-111111111106",
            "name": "GESTÃO DE ENTREGAS → NFs",
            "app_name": "Materiais pendentes • Impacto MRP",
            "endpoint": (
                "https://cuixazpxkvniqldmmnth.supabase.co/"
                "functions/v1/nf-materiais-api/status"
            ),
            "method": "GET",
            "expected_status": 200,
            "timeout_seconds": 15,
            "warning_latency_ms": 1500,
            "active": True,
            "secret_ref": "__GESTAO_ENTREGAS_ANON__",
            "health_mode": "NF_MATERIAIS_STATUS",
            "system": True,
            "source_app": "GESTÃO DE ENTREGAS",
            "target_app": "CONTROLE DE NFs",
            "service": "Supabase Edge Function",
            "resource": "nf-materiais-api /status",
            "code_location": "Gestão de Entregas · Controle de NFs",
        },
    ]


def _system_db_payload(api: dict) -> dict:
    return {
        "id": str(api["id"]),
        "name": str(api.get("name") or ""),
        "app_name": str(api.get("app_name") or ""),
        "endpoint": str(api.get("endpoint") or ""),
        "method": str(api.get("method") or "GET"),
        "expected_status": int(api.get("expected_status") or 200),
        "timeout_seconds": int(api.get("timeout_seconds") or 10),
        "warning_latency_ms": int(api.get("warning_latency_ms") or 1000),
        "active": bool(api.get("active", True)),
        "secret_ref": str(api.get("secret_ref") or ""),
    }


def ensure_system_apis() -> None:
    systems = system_apis()
    client = get_client()
    if client:
        try:
            client.table("monitor_apis").upsert(
                [_system_db_payload(item) for item in systems],
                on_conflict="id",
            ).execute()
        except Exception:
            # O painel continua funcional; o card indicará ausência de histórico
            # até a persistência voltar a responder.
            pass
        return

    data = _load_local()
    by_id = {str(item.get("id")): item for item in data["apis"]}
    changed = False
    for api in systems:
        api_id = str(api["id"])
        current = by_id.get(api_id)
        if current is None:
            data["apis"].append(_system_db_payload(api))
            changed = True
        else:
            before = dict(current)
            current.update(_system_db_payload(api))
            changed = changed or current != before
    if changed:
        _save_local(data)


def connection_coverage() -> list[dict]:
    monitored = [
        {
            "connection": item["name"],
            "source": item.get("source_app") or "—",
            "target": item.get("target_app") or "—",
            "service": item.get("service") or "—",
            "resource": item.get("resource") or "—",
            "code": item.get("code_location") or "—",
            "monitoring": "MONITORADO",
        }
        for item in system_apis()
    ]
    pending = [
        {
            "connection": "MRP → HISTÓRICO",
            "source": "MRP",
            "target": "SUPABASE DATABASE",
            "service": "PostgREST / PostgreSQL",
            "resource": "mrp_snapshots",
            "code": "MRP/mrp_conexao_patch.py · mrp_salvamento_compacto_patch.py",
            "monitoring": "SEM TESTE DEDICADO",
        },
        {
            "connection": "MRP → TRATATIVAS",
            "source": "MRP",
            "target": "SUPABASE DATABASE",
            "service": "PostgREST / PostgreSQL",
            "resource": "mrp_project_treatments · mrp_project_product_treatments",
            "code": "MRP/app_mrp_runtime.py · mrp_tratativa_produto_patch.py",
            "monitoring": "SEM TESTE DEDICADO",
        },
        {
            "connection": "SETTA HUB → CONFIGURAÇÃO",
            "source": "SETTA HUB",
            "target": "SUPABASE DATABASE",
            "service": "PostgREST",
            "resource": "setta_hub_config",
            "code": "SETTA-HUB/streamlit_app.py",
            "monitoring": "SEM TESTE DEDICADO",
        },
    ]
    return monitored + pending


def _integration_location(item: dict) -> dict:
    source = str(item.get("source_app") or "").upper()
    target = str(item.get("target_app") or "").upper()
    name = str(item.get("name") or "").upper()
    haystack = " ".join((source, target, name))
    if "CONVERSOR MRP" in haystack:
        return {
            "service": "Edge Function + Storage",
            "resource": "setta-data-api · fontes e bases tratadas",
            "code_location": "MRP-CONVERSOR/central_data.py · pipeline_sync.py",
        }
    if "MRP" in haystack and "CENTRAL" in haystack:
        return {
            "service": "Edge Function + Storage",
            "resource": "setta-data-api · bundle/derived",
            "code_location": "MRP/central_mrp_data.py",
        }
    if "MRP" in haystack:
        return {
            "service": "Central de Dados SETTA",
            "resource": "relatorio_mrp",
            "code_location": "MRP/mrp_central_data_patch.py",
        }
    return {
        "service": str(item.get("service") or "Central de Dados SETTA"),
        "resource": str(item.get("resource") or "—"),
        "code_location": str(item.get("code_location") or "—"),
    }



def list_integrations() -> list[dict]:
    try:
        rows = central_api_call("integration_status", timeout=30).get("data") or []
    except Exception as exc:
        return [
            {
                "id": "integration-status-error",
                "name": "INTEGRAÇÕES SETTA",
                "source_app": "MONITOR DE APIS",
                "target_app": "CENTRAL DE DADOS",
                "status": "OFFLINE",
                "last_activity_at": None,
                "last_activity_label": "—",
                "resource_count": 0,
                "expected_count": 0,
                "rows_count": 0,
                "version_label": "FALHA AO CONSULTAR INTEGRAÇÕES",
                "resources": [],
                "error_message": str(exc),
            }
        ]

    output: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["status"] = str(item.get("status") or "SEM DADOS").upper()
        item["last_activity_label"] = format_dt(item.get("last_activity_at"))
        item["resource_count"] = int(item.get("resource_count") or 0)
        item["expected_count"] = int(item.get("expected_count") or 0)
        item["rows_count"] = int(item.get("rows_count") or 0)
        item.update(_integration_location(item))
        output.append(item)
    return output


def list_apis(include_demo: bool = True) -> list[dict]:
    ensure_system_apis()
    client = get_client()
    rows: list[dict] = []
    if client:
        try:
            rows = client.table("monitor_apis").select("*").order("name").execute().data or []
        except Exception:
            rows = []
    else:
        rows = _load_local()["apis"]

    configs = system_apis()
    by_id = {str(row.get("id")): row for row in rows}
    system_ids = {str(item.get("id")) for item in configs}
    systems = [
        {**config, **by_id.get(str(config["id"]), {})}
        for config in configs
    ]
    # Metadados técnicos não pertencem à tabela; reaplica depois do overlay.
    systems = [
        {
            **item,
            **{
                key: config.get(key)
                for key in (
                    "system", "health_mode", "request_json", "source_app",
                    "target_app", "service", "resource", "code_location",
                )
            },
        }
        for item, config in zip(systems, configs)
    ]
    custom = [row for row in rows if str(row.get("id")) not in system_ids]
    return systems + custom



def save_api(payload: dict) -> dict:
    clean = {
        "name": str(payload.get("name") or "").strip(),
        "app_name": str(payload.get("app_name") or "").strip(),
        "endpoint": str(payload.get("endpoint") or "").strip(),
        "method": str(payload.get("method") or "GET").upper(),
        "expected_status": int(payload.get("expected_status") or 200),
        "timeout_seconds": int(payload.get("timeout_seconds") or 10),
        "warning_latency_ms": int(payload.get("warning_latency_ms") or 1000),
        "active": bool(payload.get("active", True)),
        "secret_ref": str(payload.get("secret_ref") or "").strip(),
        "updated_at": now_iso(),
    }
    if not clean["name"] or not clean["endpoint"]:
        raise ValueError("Nome e endpoint são obrigatórios.")

    client = get_client()
    if client:
        api_id = payload.get("id")
        if api_id:
            rows = client.table("monitor_apis").update(clean).eq("id", api_id).execute().data or []
        else:
            clean["created_at"] = now_iso()
            rows = client.table("monitor_apis").insert(clean).execute().data or []
        return rows[0] if rows else clean

    data = _load_local()
    api_id = str(payload.get("id") or uuid.uuid4())
    clean["id"] = api_id
    existing = next((x for x in data["apis"] if x.get("id") == api_id), None)
    if existing:
        existing.update(clean)
        result = existing
    else:
        clean["created_at"] = now_iso()
        data["apis"].append(clean)
        result = clean
    _save_local(data)
    return result


def delete_api(api_id: str) -> None:
    system_ids = {str(item.get("id")) for item in system_apis()}
    if str(api_id) in system_ids:
        return
    client = get_client()
    if client:
        client.table("monitor_apis").delete().eq("id", api_id).execute()
        return
    data = _load_local()
    data["apis"] = [x for x in data["apis"] if x.get("id") != api_id]
    data["checks"] = [x for x in data["checks"] if x.get("api_id") != api_id]
    data["incidents"] = [x for x in data["incidents"] if x.get("api_id") != api_id]
    _save_local(data)


def list_checks(api_id: str | None = None, limit: int = 200) -> list[dict]:
    client = get_client()
    if client:
        query = client.table("api_checks").select("*")
        if api_id:
            query = query.eq("api_id", api_id)
        return query.order("checked_at", desc=True).limit(limit).execute().data or []

    rows = _load_local()["checks"]
    if api_id:
        rows = [x for x in rows if x.get("api_id") == api_id]
    return sorted(rows, key=lambda x: x.get("checked_at", ""), reverse=True)[:limit]


def list_check_summary(
    api_id: str,
    since_iso: str,
    limit: int = 2000,
) -> list[dict]:
    client = get_client()
    if client:
        try:
            return (
                client.table("api_checks")
                .select("checked_at,success,latency_ms")
                .eq("api_id", api_id)
                .gte("checked_at", since_iso)
                .order("checked_at", desc=True)
                .limit(limit)
                .execute()
                .data
                or []
            )
        except Exception:
            return []
    rows = [
        row for row in _load_local()["checks"]
        if str(row.get("api_id")) == str(api_id)
        and str(row.get("checked_at") or "") >= str(since_iso)
    ]
    return sorted(
        rows,
        key=lambda x: x.get("checked_at", ""),
        reverse=True,
    )[:limit]


def save_check(api_id: str, result: dict) -> dict:
    row = {
        "api_id": api_id,
        "checked_at": result.get("checked_at") or now_iso(),
        "status": result.get("status"),
        "http_status": result.get("http_status"),
        "latency_ms": result.get("latency_ms"),
        "success": bool(result.get("success")),
        "error_message": str(result.get("error_message") or "")[:1000],
    }
    client = get_client()
    if client:
        saved = client.table("api_checks").insert(row).execute().data or []
        return saved[0] if saved else row

    data = _load_local()
    row["id"] = str(uuid.uuid4())
    data["checks"].append(row)
    data["checks"] = data["checks"][-10000:]
    _save_local(data)
    return row


def update_api_runtime(api_id: str, fields: dict) -> None:
    if str(api_id).startswith("demo-"):
        return
    allowed = {
        "status", "last_check_at", "last_success_at", "last_failure_at",
        "last_http_status", "last_latency_ms", "consecutive_failures", "updated_at"
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    clean["updated_at"] = now_iso()
    client = get_client()
    if client:
        client.table("monitor_apis").update(clean).eq("id", api_id).execute()
        return
    data = _load_local()
    for api in data["apis"]:
        if api.get("id") == api_id:
            api.update(clean)
            break
    _save_local(data)


def list_incidents(limit: int = 100) -> list[dict]:
    client = get_client()
    if client:
        return client.table("api_incidents").select("*").order("started_at", desc=True).limit(limit).execute().data or []
    return sorted(_load_local()["incidents"], key=lambda x: x.get("started_at", ""), reverse=True)[:limit]


def open_incident(api_id: str, api_name: str, kind: str, message: str) -> None:
    client = get_client()
    if client:
        open_rows = (
            client.table("api_incidents").select("id")
            .eq("api_id", api_id).eq("status", "ABERTO").limit(1).execute().data or []
        )
        if open_rows:
            return
        client.table("api_incidents").insert({
            "api_id": api_id, "api_name": api_name, "kind": kind,
            "message": message[:1000], "status": "ABERTO", "started_at": now_iso()
        }).execute()
        return

    data = _load_local()
    if any(x.get("api_id") == api_id and x.get("status") == "ABERTO" for x in data["incidents"]):
        return
    data["incidents"].append({
        "id": str(uuid.uuid4()), "api_id": api_id, "api_name": api_name,
        "kind": kind, "message": message[:1000], "status": "ABERTO", "started_at": now_iso()
    })
    _save_local(data)


def resolve_incidents(api_id: str) -> None:
    client = get_client()
    if client:
        client.table("api_incidents").update({
            "status": "NORMALIZADO", "resolved_at": now_iso()
        }).eq("api_id", api_id).eq("status", "ABERTO").execute()
        return
    data = _load_local()
    for incident in data["incidents"]:
        if incident.get("api_id") == api_id and incident.get("status") == "ABERTO":
            incident["status"] = "NORMALIZADO"
            incident["resolved_at"] = now_iso()
    _save_local(data)


SOURCE_CATALOG = [
    {
        "key": "relatorio_geral",
        "name": "RELATÓRIO GERAL",
        "source_system": "MES",
        "apps": "Conversor MRP • Gestão de Equipes",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "for001",
        "name": "FOR001",
        "source_system": "PLANILHA MANUAL",
        "apps": "Conversor MRP",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "for022",
        "name": "FOR022",
        "source_system": "PLANILHA MANUAL",
        "apps": "Conversor MRP • Gestão de Entregas • Gestão de Equipes",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "analitico",
        "name": "ANALÍTICO",
        "source_system": "PROTHEUS",
        "apps": "Conversor MRP • Fechamento Mensal • Inventário Rotativo",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "endereco",
        "name": "ENDEREÇO",
        "source_system": "PROTHEUS",
        "apps": "Conversor MRP • Inventário Rotativo",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "sc",
        "name": "S.C",
        "source_system": "PROTHEUS",
        "apps": "Conversor MRP",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "pc",
        "name": "P.C",
        "source_system": "PROTHEUS",
        "apps": "Conversor MRP",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "pre_nota",
        "name": "PRÉ NOTA",
        "source_system": "PROTHEUS",
        "apps": "Conversor MRP",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "pmp",
        "name": "PMP",
        "source_system": "OUTRO APP",
        "apps": "Conversor MRP",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "h001",
        "name": "H001",
        "source_system": "PLANILHA MANUAL",
        "apps": "Conversor MRP",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "cadastros",
        "name": "CADASTROS",
        "source_system": "PROTHEUS",
        "apps": "MRP • Gestão de Equipes",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "nf",
        "name": "NF",
        "source_system": "PROTHEUS",
        "apps": "Gestão de Entregas • Controle de NFs",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
    {
        "key": "mes_pre_notas",
        "name": "MES PRÉ NOTAS",
        "source_system": "MES",
        "apps": "Controle de NFs",
        "mode": "UPLOAD CENTRAL",
        "api_plan": True,
    },
]

DERIVED_CATALOG = [
    {
        "key": "relatorio_geral_tratado",
        "name": "RELATÓRIO GERAL TRATADO",
        "producer": "Conversor MRP",
        "depends_on": ["RELATÓRIO GERAL", "FOR001", "FOR022"],
        "apps": "MRP",
        "mode": "AUTOMÁTICO",
    },
    {
        "key": "estoque_tratado",
        "name": "ESTOQUE TRATADO",
        "producer": "Conversor MRP",
        "depends_on": ["ANALÍTICO", "ENDEREÇO"],
        "apps": "MRP",
        "mode": "AUTOMÁTICO",
    },
    {
        "key": "compras_tratado",
        "name": "COMPRAS TRATADO",
        "producer": "Conversor MRP",
        "depends_on": ["S.C", "P.C", "PRÉ NOTA"],
        "apps": "MRP",
        "mode": "AUTOMÁTICO",
    },
    {
        "key": "tctp_tratado",
        "name": "TCTP TRATADO",
        "producer": "Conversor MRP",
        "depends_on": ["PMP", "H001"],
        "apps": "MRP",
        "mode": "AUTOMÁTICO",
    },
    {
        "key": "relatorio_mrp",
        "name": "RELATÓRIO MRP",
        "producer": "MRP",
        "depends_on": [
            "CADASTROS",
            "RELATÓRIO GERAL TRATADO",
            "ESTOQUE TRATADO",
            "COMPRAS TRATADO",
            "TCTP TRATADO",
        ],
        "apps": "Gestão de Entregas • Gestão de Equipes",
        "mode": "AUTOMÁTICO",
    },
    {
        "key": "materiais_api",
        "name": "MATERIAIS",
        "producer": "Gestão de Entregas",
        "depends_on": ["FOR022", "RELATÓRIO MRP", "NF"],
        "apps": "Controle de NFs",
        "mode": "API ATIVA",
    },
]


def list_sources() -> list[dict]:
    try:
        rows = central_api_call(
            "source_status",
            {"keys": [item["key"] for item in SOURCE_CATALOG]},
            timeout=30,
        ).get("data") or []
        by_key = {
            str(row.get("source_key")): row
            for row in rows
            if isinstance(row, dict)
        }
    except Exception:
        by_key = {}

    result = []
    for base in SOURCE_CATALOG:
        row = by_key.get(base["key"], {})
        result.append(
            {
                "source_key": base["key"],
                "name": base["name"],
                "apps": base["apps"],
                "source_system": base["source_system"],
                "mode": base["mode"],
                "api_plan": bool(base.get("api_plan")),
                "status": row.get("status") or "AGUARDANDO",
                "last_update_at": row.get("last_update_at"),
                "rows_count": row.get("rows_count") or 0,
                "origin": row.get("origin") or base["source_system"],
                "last_file_name": row.get("last_file_name") or "",
                "version": int(row.get("version") or 0),
                "available": bool(row.get("available")),
            }
        )
    return result


def list_derived_bases() -> list[dict]:
    rows_by_key: dict[str, dict] = {}
    try:
        rows = central_api_call(
            "derived_status",
            {"keys": [item["key"] for item in DERIVED_CATALOG]},
            timeout=30,
        ).get("data") or []
        rows_by_key = {
            str(row.get("base_key")): row
            for row in rows
            if isinstance(row, dict)
        }
    except Exception:
        rows_by_key = {}

    result = []
    for base in DERIVED_CATALOG:
        row = rows_by_key.get(base["key"], {})
        result.append(
            {
                **base,
                "status": row.get("status") or "AGUARDANDO",
                "rows_count": int(row.get("rows_count") or 0),
                "processed_at": row.get("processed_at"),
                "available": bool(row.get("available")),
                "source_versions": row.get("source_versions") or {},
            }
        )
    return result


def save_report(
    source_key: str,
    file_name: str,
    raw: bytes,
    rows_count: int = 0,
    origin: str = "UPLOAD",
) -> dict:
    prepared = central_api_call(
        "source_upload_prepare",
        {"source_key": source_key},
        timeout=30,
    )
    path = str(prepared.get("path") or "")
    token = str(prepared.get("token") or "")
    if not path or not token:
        raise RuntimeError("A Central não retornou autorização para upload.")

    client = central_client()
    client.storage.from_("setta-data").upload_to_signed_url(
        path=path,
        token=token,
        file=raw,
    )

    committed = central_api_call(
        "source_commit",
        {
            "source_key": source_key,
            "file_name": file_name,
            "rows_count": int(rows_count),
            "mime_type": "application/octet-stream",
        },
        timeout=30,
    ).get("data") or {}
    return committed


def list_imports(source_key: str | None = None, limit: int = 100) -> list[dict]:
    client = get_client()
    if client:
        query = client.table("data_imports").select("*")
        if source_key:
            query = query.eq("source_key", source_key)
        return query.order("imported_at", desc=True).limit(limit).execute().data or []
    rows = _load_local()["imports"]
    if source_key:
        rows = [x for x in rows if x.get("source_key") == source_key]
    return sorted(rows, key=lambda x: x.get("imported_at", ""), reverse=True)[:limit]


def load_visual_config() -> dict:
    try:
        row = central_api_call(
            "visual_get",
            {"app_key": "setta_global"},
            timeout=30,
        ).get("data") or {}
        return {
            "logo_data": row.get("logo_data") or "",
            "logo_mime": row.get("logo_mime") or "image/png",
            "favicon_data": row.get("favicon_data") or "",
            "favicon_mime": row.get("favicon_mime") or "image/png",
        }
    except Exception:
        return dict(_load_local().get("visual_config") or {})


def save_visual_config(
    logo_data: str | None = None,
    logo_mime: str | None = None,
    favicon_data: str | None = None,
    favicon_mime: str | None = None,
) -> dict:
    current = load_visual_config()
    if logo_data is not None:
        current["logo_data"] = logo_data
    if logo_mime is not None:
        current["logo_mime"] = logo_mime
    if favicon_data is not None:
        current["favicon_data"] = favicon_data
    if favicon_mime is not None:
        current["favicon_mime"] = favicon_mime

    try:
        row = central_api_call(
            "visual_set",
            {
                "app_key": "setta_global",
                **current,
            },
            timeout=30,
        ).get("data") or current
        return {
            "logo_data": row.get("logo_data") or "",
            "logo_mime": row.get("logo_mime") or "image/png",
            "favicon_data": row.get("favicon_data") or "",
            "favicon_mime": row.get("favicon_mime") or "image/png",
        }
    except Exception:
        data = _load_local()
        data["visual_config"] = current
        _save_local(data)
        return current


def reset_visual_config() -> None:
    save_visual_config(
        logo_data="",
        logo_mime="image/png",
        favicon_data="",
        favicon_mime="image/png",
    )
