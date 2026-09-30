from __future__ import annotations

import base64
import html
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
LOGO_FILE = ROOT / "config" / "logo_setta.svg"

CSS = """
<style>
[data-testid="stAppViewContainer"]{background:#f4f7fb!important}
[data-testid="stHeader"]{background:rgba(255,255,255,.96)!important}
.block-container{max-width:1780px!important;padding-top:3.2rem!important;padding-left:2.7rem!important;padding-right:2.7rem!important;padding-bottom:3rem!important;width:100%!important}
section[data-testid="stSidebar"]{background:#fff!important;border-right:1px solid #e8ebf0!important}
section[data-testid="stSidebar"] .block-container{padding-top:1.6rem!important;padding-left:1rem!important;padding-right:1rem!important}
.sidebar-brand{background:#f8fafc;border:1px solid #e5e8ee;border-radius:12px;padding:.9rem 1rem;margin:0 0 1.05rem 0}
.sidebar-brand-title{font-size:.92rem;font-weight:800;color:#111827;letter-spacing:-.01em}
.sidebar-brand-sub{margin-top:.18rem;font-size:.75rem;color:#6b7280}
.sidebar-section-label{margin:.25rem 0 .45rem;color:#374151;font-size:.76rem;font-weight:800;text-transform:uppercase;letter-spacing:.055em}
.sidebar-logo-preview{width:100%;min-height:82px;display:flex;justify-content:center;align-items:center;margin:.65rem 0 .5rem;padding:.65rem .8rem;background:#fff;border:1px dashed #d1d5db;border-radius:10px;box-sizing:border-box;overflow:hidden}
.sidebar-logo-preview img{display:block;width:auto;height:auto;max-width:140px;max-height:62px;object-fit:contain}
.sidebar-info-card{background:#f8fafc;border:1px solid #e5e8ee;border-radius:10px;padding:.75rem .85rem;color:#6b7280;font-size:.76rem;line-height:1.55}
section[data-testid="stSidebar"] div[role="radiogroup"]{display:flex;flex-direction:column;gap:.34rem}
section[data-testid="stSidebar"] div[role="radiogroup"] label{position:relative;width:100%;min-height:42px;display:flex!important;align-items:center!important;padding:.56rem .72rem .56rem .88rem!important;margin:0!important;border:1px solid transparent!important;border-radius:10px!important;background:transparent!important;cursor:pointer}
section[data-testid="stSidebar"] div[role="radiogroup"] label>div:first-child{position:absolute!important;opacity:0!important;width:0!important;height:0!important;overflow:hidden!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label p{margin:0!important;font-size:.83rem!important;font-weight:600!important;color:#374151!important;white-space:normal!important;line-height:1.25!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover{background:#f8fafc!important;border-color:#e5e7eb!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){background:#111827!important;border-color:#111827!important;box-shadow:0 5px 14px rgba(17,24,39,.14)!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked)::before{content:"";position:absolute;left:.42rem;top:50%;width:4px;height:20px;border-radius:999px;background:#ef4444;transform:translateY(-50%)}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p{color:#fff!important;font-weight:700!important}

[data-testid="stAppViewContainer"] > .main,[data-testid="stAppViewContainer"] .main,[data-testid="stMain"],.stMain{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}
[data-testid="stAppViewContainer"] .main .block-container,[data-testid="stMain"] .block-container,.stMain .block-container{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}

.setta-logo-card{width:100%;min-height:128px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid #e5e8ee;border-radius:16px;box-shadow:0 4px 14px rgba(24,39,75,.08);box-sizing:border-box;margin:0 0 2.55rem;padding:1.1rem 2rem}
.setta-logo-card img{display:block;width:auto;height:auto;max-width:205px;max-height:86px;object-fit:contain}
.app-head{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;margin-bottom:1.65rem}
.app-title{margin:0!important;padding:0!important;font-size:2.55rem!important;line-height:1.08!important;font-weight:800!important;letter-spacing:-.04em!important;color:#050505!important}
.app-sub{margin-top:.72rem!important;color:#4f5661!important;font-size:.94rem!important}
.system-pill{display:inline-flex;align-items:center;gap:.48rem;background:#ecfdf3;border:1px solid #bbf7d0;color:#166534;border-radius:999px;padding:.46rem .68rem;font-size:.72rem;font-weight:900;white-space:nowrap}
.pulse{width:8px;height:8px;border-radius:999px;background:#22c55e;box-shadow:0 0 0 4px rgba(34,197,94,.12)}

.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.85rem;margin:.25rem 0 1rem}
.kpi-card{position:relative;background:#fff;border:1px solid #dfe3e8;border-radius:12px;box-shadow:0 3px 12px rgba(15,23,42,.04);padding:.85rem 1rem;overflow:hidden;min-height:110px}
.kpi-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent,#111827)}
.kpi-label{font-size:.66rem;font-weight:900;letter-spacing:.04em;text-transform:uppercase;color:#64748b;margin-bottom:.42rem}
.kpi-value{font-size:1.55rem;font-weight:900;letter-spacing:-.02em;color:#111827}
.kpi-note{margin-top:.3rem;font-size:.68rem;color:#94a3b8}

.section-band{margin:1.25rem 0 .95rem;padding:.82rem 1rem;background:#fff;border:1px solid #e5e8ee;border-left:5px solid #111827;border-radius:12px;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.section-band-kicker{font-size:.66rem;font-weight:900;letter-spacing:.085em;text-transform:uppercase;color:#ef4444;margin-bottom:.18rem}
.section-band-title{font-size:1.08rem;font-weight:900;color:#111827;letter-spacing:-.015em;line-height:1.2;text-transform:uppercase}
.section-band-note{margin-top:.26rem;color:#667085;font-size:.78rem;line-height:1.45}

.api-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin:.3rem 0 1rem}
.api-card{position:relative;background:#fff;border:1px solid #dfe3e8;border-radius:14px;box-shadow:0 4px 16px rgba(15,23,42,.05);padding:1rem 1.1rem;overflow:hidden;min-height:250px}
.api-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--status)}
.api-top{display:flex;align-items:flex-start;justify-content:space-between;gap:.7rem}
.api-name{font-size:.92rem;font-weight:900;color:#111827;line-height:1.25;text-transform:uppercase}
.api-app{margin-top:.2rem;font-size:.7rem;color:#667085}
.status-badge{display:inline-flex;align-items:center;gap:.35rem;border-radius:999px;padding:.28rem .48rem;font-size:.62rem;font-weight:900;background:var(--status-soft);color:var(--status-text);border:1px solid var(--status-border);white-space:nowrap}
.status-dot{width:7px;height:7px;border-radius:999px;background:var(--status)}
.api-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.58rem;margin:.9rem 0}
.api-metric{background:#f8fafc;border:1px solid #edf0f3;border-radius:10px;padding:.58rem .65rem}
.api-metric-label{font-size:.61rem;text-transform:uppercase;letter-spacing:.04em;font-weight:800;color:#94a3b8}
.api-metric-value{margin-top:.2rem;font-size:.83rem;font-weight:900;color:#111827}
.api-foot{display:flex;align-items:flex-end;justify-content:space-between;gap:.7rem;margin-top:.72rem}
.api-last{font-size:.67rem;color:#64748b;line-height:1.5}
.spark-wrap{width:104px}
.spark{display:flex;align-items:flex-end;height:36px;gap:3px}
.spark span{display:block;flex:1;min-width:4px;border-radius:3px 3px 1px 1px;background:#cbd5e1}
.spark-label{margin-top:.25rem;font-size:.57rem;color:#94a3b8;text-align:right}

.table-card{background:#fff;border:1px solid #dfe3e8;border-radius:14px;box-shadow:0 4px 16px rgba(15,23,42,.045);overflow:hidden;margin-bottom:1rem}
.table-row{display:grid;grid-template-columns:1.1fr 1.35fr .8fr .8fr .8fr;min-height:44px;border-bottom:1px solid #e5e7eb;align-items:stretch}
.table-row:last-child{border-bottom:0}
.table-head{background:#e5e7eb}
.table-cell{display:flex;align-items:center;padding:.65rem .78rem;border-right:1px solid #e5e7eb;color:#374151;font-size:.74rem}
.table-cell:last-child{border-right:0}
.table-head .table-cell{font-size:.67rem;font-weight:900;text-transform:uppercase;letter-spacing:.035em;color:#111827}
.event-ok{font-weight:900;color:#166534}.event-warn{font-weight:900;color:#92400e}.event-error{font-weight:900;color:#b91c1c}

.source-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.85rem;margin:.3rem 0 1rem}
.source-card{position:relative;background:#fff;border:1px solid #dfe3e8;border-radius:12px;padding:.95rem 1rem;box-shadow:0 3px 12px rgba(15,23,42,.035);overflow:hidden;min-height:145px}
.source-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--source-accent,#111827)}
.source-top{display:flex;justify-content:space-between;align-items:flex-start;gap:.8rem}
.source-name{font-size:.8rem;font-weight:900;color:#111827;text-transform:uppercase;margin-bottom:.3rem}
.source-meta{font-size:.74rem;color:#667085;line-height:1.55}
.source-apps{margin-top:.65rem;padding-top:.55rem;border-top:1px solid #edf0f3;color:#475569;font-size:.69rem;line-height:1.45}
.source-badge{display:inline-flex;border-radius:999px;padding:.22rem .46rem;font-size:.64rem;font-weight:800;background:#f1f5f9;color:#475569;white-space:nowrap}

.notice{border:1px solid #fde68a;background:#fffbeb;color:#92400e;border-radius:10px;padding:.72rem .85rem;font-size:.75rem;line-height:1.45;margin:.6rem 0 1rem}
.ok-notice{border-color:#bbf7d0;background:#f0fdf4;color:#166534}
.footer{text-align:center;color:#9298a1;font-size:.72rem;padding-top:1.2rem}

@media (max-width:1100px){.api-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.source-grid{grid-template-columns:1fr}}
@media (max-width:900px){
.block-container{padding-top:2rem!important;padding-left:1rem!important;padding-right:1rem!important;padding-bottom:2rem!important}
.setta-logo-card{min-height:105px;margin-bottom:1.8rem;padding:.9rem 1rem}.setta-logo-card img{max-width:170px;max-height:72px}
.app-head{flex-direction:column;gap:.7rem}.app-title{font-size:2rem!important}
.kpi-grid,.api-grid,.source-grid{grid-template-columns:1fr!important}
.table-row{grid-template-columns:1fr!important}.table-head{display:none!important}
.table-cell{border-right:0!important;border-bottom:1px solid #eef0f3;justify-content:flex-start!important}
.table-cell::before{content:attr(data-label);display:inline-block;min-width:108px;margin-right:.65rem;font-size:.62rem;font-weight:900;text-transform:uppercase;color:#64748b}
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def logo_html(data: str = "", mime: str = "image/svg+xml") -> str:
    if data:
        return f'<img src="data:{html.escape(mime)};base64,{data}" alt="Logo SETTA">'
    if LOGO_FILE.exists():
        encoded = base64.b64encode(LOGO_FILE.read_bytes()).decode()
        return f'<img src="data:image/svg+xml;base64,{encoded}" alt="Logo SETTA">'
    return '<b style="font-size:2rem;letter-spacing:.08em">SETTA</b>'


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def section_band(kicker: str, title: str, note: str) -> None:
    markup = (
        '<div class="section-band">'
        f'<div class="section-band-kicker">{esc(kicker)}</div>'
        f'<div class="section-band-title">{esc(title)}</div>'
        f'<div class="section-band-note">{esc(note)}</div>'
        '</div>'
    )
    st.markdown(markup, unsafe_allow_html=True)


def kpi_grid(items: list[dict]) -> None:
    cards = []
    for item in items:
        cards.append(
            '<div class="kpi-card" '
            f'style="--accent:{esc(item.get("accent", "#111827"))}">'
            f'<div class="kpi-label">{esc(item.get("label"))}</div>'
            f'<div class="kpi-value">{esc(item.get("value"))}</div>'
            f'<div class="kpi-note">{esc(item.get("note"))}</div>'
            '</div>'
        )
    st.markdown('<div class="kpi-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)


STATUS_STYLE = {
    "ONLINE": ("#22c55e", "#ecfdf3", "#166534", "#bbf7d0"),
    "ATENÇÃO": ("#f59e0b", "#fffbeb", "#92400e", "#fde68a"),
    "OFFLINE": ("#ef4444", "#fef2f2", "#b91c1c", "#fecaca"),
    "DESATIVADA": ("#94a3b8", "#f8fafc", "#475569", "#e2e8f0"),
    "SEM DADOS": ("#64748b", "#f8fafc", "#475569", "#e2e8f0"),
}


def api_card(api: dict) -> str:
    status = str(api.get("status") or "SEM DADOS").upper()
    status = status if status in STATUS_STYLE else "SEM DADOS"
    accent, soft, text, border = STATUS_STYLE[status]
    history = api.get("latency_history") or []
    usable = [max(1.0, float(v or 0)) for v in history[-12:]]
    peak = max(usable) if usable else 1
    bars = ''.join(
        f'<span style="height:{max(5, min(36, int((v / peak) * 34) + 2))}px"></span>'
        for v in usable
    ) or '<span style="height:5px"></span>' * 8
    latency = api.get("latency_ms")
    latency_text = "—" if latency is None else f"{float(latency):.0f} ms"
    http_status = api.get("http_status")
    http_text = "—" if http_status in (None, "") else str(http_status)
    uptime = api.get("uptime_24h")
    uptime_text = "—" if uptime is None else f"{float(uptime):.2f}%"
    failures = int(api.get("consecutive_failures") or 0)

    return (
        '<div class="api-card" '
        f'style="--status:{accent};--status-soft:{soft};--status-text:{text};--status-border:{border}">'
        '<div class="api-top"><div>'
        f'<div class="api-name">{esc(api.get("name"))}</div>'
        f'<div class="api-app">{esc(api.get("app_name") or "Integração SETTA")}</div>'
        '</div>'
        f'<div class="status-badge"><span class="status-dot"></span>{esc(status)}</div>'
        '</div>'
        '<div class="api-metrics">'
        f'<div class="api-metric"><div class="api-metric-label">Resposta</div><div class="api-metric-value">{esc(latency_text)}</div></div>'
        f'<div class="api-metric"><div class="api-metric-label">HTTP</div><div class="api-metric-value">{esc(http_text)}</div></div>'
        f'<div class="api-metric"><div class="api-metric-label">Uptime 24h</div><div class="api-metric-value">{esc(uptime_text)}</div></div>'
        f'<div class="api-metric"><div class="api-metric-label">Falhas seguidas</div><div class="api-metric-value">{failures}</div></div>'
        '</div>'
        '<div class="api-foot">'
        '<div class="api-last">'
        f'<b>Última verificação</b><br>{esc(api.get("last_check_label") or "Aguardando")}<br>'
        f'<b>Último sucesso</b><br>{esc(api.get("last_success_label") or "—")}'
        '</div>'
        f'<div class="spark-wrap"><div class="spark">{bars}</div><div class="spark-label">latência recente</div></div>'
        '</div></div>'
    )


def source_card(source: dict) -> str:
    status = str(source.get("status") or "AGUARDANDO").upper()
    accent = "#22c55e" if status == "ATUALIZADO" else "#f59e0b" if status == "ATENÇÃO" else "#64748b"
    return (
        '<div class="source-card" '
        f'style="--source-accent:{accent}">'
        '<div class="source-top"><div>'
        f'<div class="source-name">{esc(source.get("name"))}</div>'
        '<div class="source-meta">'
        f'Última atualização: <b>{esc(source.get("last_update_label") or "Nunca")}</b><br>'
        f'Registros: <b>{esc(source.get("rows_count") or 0)}</b><br>'
        f'Origem: <b>{esc(source.get("origin") or "Manual")}</b>'
        '</div></div>'
        f'<div class="source-badge">{esc(status)}</div></div>'
        f'<div class="source-apps"><b>Utilizado por:</b> {esc(source.get("apps") or "A definir")}</div>'
        '</div>'
    )
