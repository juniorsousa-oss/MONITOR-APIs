from __future__ import annotations

import io
import json
import os
import uuid
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
    return [
        {
            "id": "system-nf-materiais",
            "name": "API MATERIAIS",
            "app_name": "Gestão de Entregas → Controle de NFs",
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
        }
    ]


def list_apis(include_demo: bool = True) -> list[dict]:
    client = get_client()
    rows: list[dict] = []
    if client:
        try:
            rows = client.table("monitor_apis").select("*").order("name").execute().data or []
        except Exception:
            rows = []
    else:
        rows = _load_local()["apis"]

    systems = system_apis()
    system_ids = {str(item.get("id")) for item in systems}
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
    if str(api_id).startswith("system-"):
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


DEFAULT_SOURCES = [
    {"key": "cadastros", "name": "CADASTRO DE MATERIAIS", "apps": "MRP • Compra Fácil • Fechamento Mensal"},
    {"key": "estoque", "name": "ESTOQUE", "apps": "MRP • Gestão de Entregas • Inventários"},
    {"key": "relatorio_geral", "name": "RELATÓRIO GERAL", "apps": "MRP • PCP • Suprimentos"},
    {"key": "planejamento_pcp", "name": "PLANEJAMENTO PCP", "apps": "MRP • Gestão de Entregas"},
]


def list_sources() -> list[dict]:
    client = get_client()
    saved: list[dict] = []
    if client:
        try:
            saved = client.table("data_sources").select("*").order("name").execute().data or []
        except Exception:
            saved = []
    else:
        saved = _load_local()["sources"]

    by_key = {x.get("source_key"): x for x in saved}
    result = []
    for base in DEFAULT_SOURCES:
        row = by_key.get(base["key"], {})
        merged = {
            "source_key": base["key"],
            "name": base["name"],
            "apps": base["apps"],
            "status": row.get("status") or "AGUARDANDO",
            "last_update_at": row.get("last_update_at"),
            "rows_count": row.get("rows_count") or 0,
            "origin": row.get("origin") or "Manual",
            "last_file_name": row.get("last_file_name") or "",
        }
        result.append(merged)
    return result


def save_report(source_key: str, file_name: str, raw: bytes, rows_count: int = 0, origin: str = "UPLOAD") -> dict:
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in Path(file_name).name if c.isalnum() or c in "._- ")
    storage_path = f"{source_key}/{stamp}_{safe_name}"
    now = now_iso()
    client = get_client()

    if client:
        client.storage.from_("setta-data").upload(
            path=storage_path,
            file=io.BytesIO(raw),
            file_options={
                "content-type": "application/octet-stream",
                "upsert": "false",
            },
        )
        source_row = {
            "source_key": source_key,
            "name": next((x["name"] for x in DEFAULT_SOURCES if x["key"] == source_key), source_key.upper()),
            "status": "ATUALIZADO",
            "last_update_at": now,
            "rows_count": int(rows_count),
            "origin": origin,
            "last_file_name": file_name,
            "updated_at": now,
        }
        client.table("data_sources").upsert(source_row, on_conflict="source_key").execute()
        saved = client.table("data_imports").insert({
            "source_key": source_key,
            "file_name": file_name,
            "storage_path": storage_path,
            "rows_count": int(rows_count),
            "origin": origin,
            "imported_at": now,
        }).execute().data or []
        return saved[0] if saved else source_row

    folder = UPLOAD_DIR / source_key
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stamp}_{safe_name}"
    target.write_bytes(raw)
    data = _load_local()
    source = next((x for x in data["sources"] if x.get("source_key") == source_key), None)
    if source is None:
        source = {"source_key": source_key}
        data["sources"].append(source)
    source.update({
        "status": "ATUALIZADO", "last_update_at": now, "rows_count": int(rows_count),
        "origin": origin, "last_file_name": file_name, "updated_at": now
    })
    try:
        local_storage_path = str(target.relative_to(ROOT))
    except ValueError:
        local_storage_path = str(target)
    row = {
        "id": str(uuid.uuid4()), "source_key": source_key, "file_name": file_name,
        "storage_path": local_storage_path, "rows_count": int(rows_count),
        "origin": origin, "imported_at": now,
    }
    data["imports"].append(row)
    _save_local(data)
    return row


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
    client = get_client()
    if client:
        try:
            rows = (
                client.table("app_visual_config")
                .select("*")
                .eq("config_key", "default")
                .limit(1)
                .execute()
                .data
                or []
            )
            if rows:
                row = rows[0]
                return {
                    "logo_data": row.get("logo_data") or "",
                    "logo_mime": row.get("logo_mime") or "image/png",
                    "favicon_data": row.get("favicon_data") or "",
                    "favicon_mime": row.get("favicon_mime") or "image/png",
                }
        except Exception:
            pass
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

    client = get_client()
    if client:
        payload = {
            "config_key": "default",
            "logo_data": current.get("logo_data") or "",
            "logo_mime": current.get("logo_mime") or "image/png",
            "favicon_data": current.get("favicon_data") or "",
            "favicon_mime": current.get("favicon_mime") or "image/png",
            "updated_at": now_iso(),
        }
        try:
            client.table("app_visual_config").upsert(
                payload,
                on_conflict="config_key",
            ).execute()
            return current
        except Exception:
            pass

    data = _load_local()
    data["visual_config"] = current
    _save_local(data)
    return current


def reset_visual_config() -> None:
    client = get_client()
    if client:
        try:
            client.table("app_visual_config").delete().eq(
                "config_key", "default"
            ).execute()
        except Exception:
            pass

    data = _load_local()
    data["visual_config"] = {}
    _save_local(data)
