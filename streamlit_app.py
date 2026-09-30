from __future__ import annotations

import base64
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_autorefresh import st_autorefresh

import data_store as store
import monitor_logic as monitor
from ui import api_card, inject_css, kpi_grid, logo_html, section_band, source_card

TZ = ZoneInfo("America/Sao_Paulo")
VISUAL_CONFIG = store.load_visual_config()


def browser_icon():
    data = str(VISUAL_CONFIG.get("favicon_data") or "").strip()
    if not data:
        return "📡"
    try:
        raw = base64.b64decode(data, validate=True)
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image
    except Exception:
        return "📡"


st.set_page_config(
    page_title="MONITOR DE APIs | SETTA",
    page_icon=browser_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# A tela apenas lê os resultados. O worker é responsável pelos testes das APIs.
st_autorefresh(interval=30_000, limit=None, key="setta_monitor_refresh")


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">'
            '<div class="sidebar-brand-title">MONITOR DE APIs</div>'
            '<div class="sidebar-brand-sub">Central operacional SETTA</div>'
            '</div>'
            '<div class="sidebar-section-label">Navegação</div>',
            unsafe_allow_html=True,
        )
        page = st.radio(
            "Navegação",
            ["Monitor de APIs", "Banco de Dados"],
            label_visibility="collapsed",
        )

        st.markdown("---")
        with st.expander("PERSONALIZAÇÃO", expanded=False):
            st.caption("Logo do cabeçalho")
            current_logo = logo_html(
                str(VISUAL_CONFIG.get("logo_data") or ""),
                str(VISUAL_CONFIG.get("logo_mime") or "image/svg+xml"),
            )
            st.markdown(
                f'<div class="sidebar-logo-preview">{current_logo}</div>',
                unsafe_allow_html=True,
            )
            logo_file = st.file_uploader(
                "Alterar logo",
                type=["png", "jpg", "jpeg", "webp", "svg"],
                key="visual_logo_file",
                label_visibility="collapsed",
            )

            st.caption("Ícone do navegador")
            favicon_file = st.file_uploader(
                "Alterar ícone",
                type=["png", "jpg", "jpeg", "ico"],
                key="visual_favicon_file",
                label_visibility="collapsed",
            )

            save_col, reset_col = st.columns(2)
            if save_col.button(
                "SALVAR",
                type="primary",
                use_container_width=True,
                key="save_visual_config",
            ):
                if logo_file is None and favicon_file is None:
                    st.warning("Selecione a logo ou o ícone que deseja alterar.")
                else:
                    try:
                        kwargs = {}
                        if logo_file is not None:
                            if len(logo_file.getvalue()) > 2 * 1024 * 1024:
                                raise ValueError("A logo deve ter no máximo 2 MB.")
                            kwargs["logo_data"] = base64.b64encode(
                                logo_file.getvalue()
                            ).decode()
                            kwargs["logo_mime"] = (
                                logo_file.type or "image/png"
                            )
                        if favicon_file is not None:
                            if len(favicon_file.getvalue()) > 1 * 1024 * 1024:
                                raise ValueError(
                                    "O ícone deve ter no máximo 1 MB."
                                )
                            raw_icon = favicon_file.getvalue()
                            image = Image.open(io.BytesIO(raw_icon))
                            image.verify()
                            kwargs["favicon_data"] = base64.b64encode(
                                raw_icon
                            ).decode()
                            kwargs["favicon_mime"] = (
                                favicon_file.type or "image/png"
                            )
                        store.save_visual_config(**kwargs)
                        st.success("Identidade visual atualizada.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível salvar: {exc}")

            if reset_col.button(
                "PADRÃO",
                use_container_width=True,
                key="reset_visual_config",
            ):
                store.reset_visual_config()
                st.rerun()

        if store.supabase_enabled():
            st.success("Banco central conectado", icon="✓")
        else:
            st.info("Modo local de validação", icon="ℹ")
        st.caption("Atualização automática · 30 s")
    return page


def render_logo() -> None:
    image = logo_html(
        str(VISUAL_CONFIG.get("logo_data") or ""),
        str(VISUAL_CONFIG.get("logo_mime") or "image/svg+xml"),
    )
    st.markdown(
        f'<div class="setta-logo-card">{image}</div>',
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str, pill: str) -> None:
    markup = (
        '<div class="app-head"><div>'
        f'<div class="app-title">{title}</div>'
        f'<div class="app-sub">{subtitle}</div>'
        '</div>'
        f'<div class="system-pill"><span class="pulse"></span>{pill}</div>'
        '</div>'
    )
    st.markdown(markup, unsafe_allow_html=True)


def _count_rows(name: str, raw: bytes) -> int:
    lower = name.lower()
    try:
        if lower.endswith(".csv"):
            frame = pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
            return len(frame)
        if lower.endswith((".xlsx", ".xlsm", ".xltx")):
            frame = pd.read_excel(io.BytesIO(raw))
            return len(frame)
    except Exception:
        return 0
    return 0


def _monitor_pill(apis: list[dict]) -> str:
    real = [x for x in apis if not x.get("demo")]
    if not real:
        return "SEM APIs"
    dates = [store.parse_dt(x.get("last_check_at")) for x in real]
    dates = [x for x in dates if x]
    if not dates:
        return "AGUARDANDO PRIMEIRO CICLO"
    age = (datetime.now(TZ) - max(dates)).total_seconds()
    return "MONITORAMENTO ATIVO 24/7" if age <= 180 else "SEM CICLO RECENTE"


def render_api_registration() -> None:
    with st.expander("CADASTRAR NOVA API", expanded=False):
        with st.form("api_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Nome da API", placeholder="API PROTHEUS")
            app_name = c2.text_input("Aplicação / finalidade", placeholder="ERP / Estoque")
            endpoint = st.text_input("Endpoint", placeholder="https://sistema.exemplo.com/api/health")
            c3, c4, c5 = st.columns(3)
            method = c3.selectbox("Método", ["GET", "HEAD", "POST"])
            expected = c4.number_input("HTTP esperado", min_value=100, max_value=599, value=200)
            timeout = c5.number_input("Timeout (s)", min_value=1, max_value=120, value=10)
            c6, c7 = st.columns(2)
            warning = c6.number_input(
                "Latência para atenção (ms)",
                min_value=100,
                max_value=60_000,
                value=1000,
                step=100,
            )
            secret_ref = c7.text_input(
                "Referência do segredo",
                placeholder="PROTHEUS_API_HEADERS",
                help="Variável de ambiente com o token ou headers.",
            )
            active = st.checkbox("Monitoramento ativo", value=True)
            submitted = st.form_submit_button(
                "SALVAR API",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            try:
                store.save_api(
                    {
                        "name": name,
                        "app_name": app_name,
                        "endpoint": endpoint,
                        "method": method,
                        "expected_status": expected,
                        "timeout_seconds": timeout,
                        "warning_latency_ms": warning,
                        "secret_ref": secret_ref,
                        "active": active,
                    }
                )
                st.success("API cadastrada.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar a API: {exc}")


def render_monitor() -> None:
    raw_apis = store.list_apis(include_demo=True)
    apis = monitor.hydrate_all(raw_apis)

    render_header(
        "MONITOR DE APIs | SETTA",
        "Integrações • Disponibilidade • Desempenho",
        _monitor_pill(apis),
    )

    active = [x for x in apis if str(x.get("status")).upper() != "DESATIVADA"]
    online = sum(1 for x in active if str(x.get("status")).upper() == "ONLINE")
    attention = sum(1 for x in active if str(x.get("status")).upper() == "ATENÇÃO")
    offline = sum(1 for x in active if str(x.get("status")).upper() == "OFFLINE")

    kpi_grid(
        [
            {
                "label": "APIs cadastradas",
                "value": len(apis),
                "note": "",
                "accent": "#111827",
            },
            {
                "label": "Online",
                "value": online,
                "note": "",
                "accent": "#22c55e",
            },
            {
                "label": "Atenção",
                "value": attention,
                "note": "",
                "accent": "#f59e0b",
            },
            {
                "label": "Offline",
                "value": offline,
                "note": "",
                "accent": "#ef4444",
            },
        ]
    )

    real_apis = list(raw_apis)
    b1, b2 = st.columns([1, 1])
    if b1.button(
        "VERIFICAR TODAS AGORA",
        type="primary",
        use_container_width=True,
        disabled=not bool(real_apis),
    ):
        with st.spinner("Executando verificações..."):
            monitor.run_all_checks()
        st.success("Ciclo manual concluído.")
        st.rerun()

    if b2.button("ATUALIZAR PAINEL", use_container_width=True):
        st.rerun()

    render_api_registration()

    section_band(
        "01 · DISPONIBILIDADE",
        "INTEGRAÇÕES MONITORADAS",
        "",
    )
    st.markdown(
        '<div class="api-grid">' + "".join(api_card(api) for api in apis) + "</div>",
        unsafe_allow_html=True,
    )

    if real_apis:
        with st.expander("DETALHES E HISTÓRICO DAS APIs", expanded=False):
            api_map = {str(x.get("name")): x for x in real_apis}
            selected_name = st.selectbox("API", list(api_map.keys()))
            selected = api_map[selected_name]
            h1, h2, h3 = st.columns(3)
            h1.metric("Método", selected.get("method") or "GET")
            h2.metric("HTTP esperado", selected.get("expected_status") or 200)
            h3.metric("Timeout", f"{selected.get('timeout_seconds') or 10}s")
            st.code(str(selected.get("endpoint") or ""), language=None)

            checks = store.list_checks(str(selected.get("id")), limit=50)
            if checks:
                history = pd.DataFrame(checks)
                cols = [
                    c
                    for c in [
                        "checked_at",
                        "status",
                        "http_status",
                        "latency_ms",
                        "success",
                        "error_message",
                    ]
                    if c in history.columns
                ]
                st.dataframe(history[cols], use_container_width=True, hide_index=True)
            else:
                st.info("Ainda não existem verificações gravadas para esta API.")

            if not selected.get("system"):
                if st.button("EXCLUIR API SELECIONADA", type="secondary"):
                    store.delete_api(str(selected.get("id")))
                    st.rerun()

    section_band(
        "02 · OCORRÊNCIAS",
        "INCIDENTES RECENTES",
        "",
    )
    incidents = store.list_incidents(limit=12)
    if incidents:
        rows = ['<div class="table-card">']
        rows.append(
            '<div class="table-row table-head">'
            '<div class="table-cell">Início</div><div class="table-cell">API</div>'
            '<div class="table-cell">Tipo</div><div class="table-cell">Status</div>'
            '<div class="table-cell">Fim</div></div>'
        )
        for incident in incidents:
            status = str(incident.get("status") or "")
            css = "event-error" if status == "ABERTO" else "event-ok"
            rows.append(
                '<div class="table-row">'
                f'<div class="table-cell" data-label="Início">{store.format_dt(incident.get("started_at"))}</div>'
                f'<div class="table-cell" data-label="API">{incident.get("api_name") or "—"}</div>'
                f'<div class="table-cell" data-label="Tipo">{incident.get("kind") or "—"}</div>'
                f'<div class="table-cell {css}" data-label="Status">{status}</div>'
                f'<div class="table-cell" data-label="Fim">{store.format_dt(incident.get("resolved_at"))}</div>'
                "</div>"
            )
        rows.append("</div>")
        st.markdown("".join(rows), unsafe_allow_html=True)
    else:
        st.success("Nenhum incidente registrado.")


def render_database() -> None:
    render_header(
        "BANCO DE DADOS | SETTA",
        "Fontes • Alimentação • Histórico",
        "CENTRAL DE DADOS",
    )

    if store.supabase_enabled():
        st.caption("Banco central conectado")
    else:
        st.caption("Modo local de validação")

    sources = store.list_sources()
    updated = sum(1 for x in sources if str(x.get("status")).upper() == "ATUALIZADO")
    total_rows = sum(int(x.get("rows_count") or 0) for x in sources)

    kpi_grid(
        [
            {
                "label": "Bases previstas",
                "value": len(sources),
                "note": "",
                "accent": "#111827",
            },
            {
                "label": "Atualizadas",
                "value": updated,
                "note": "",
                "accent": "#22c55e",
            },
            {
                "label": "Aguardando",
                "value": len(sources) - updated,
                "note": "",
                "accent": "#f59e0b",
            },
            {
                "label": "Registros",
                "value": f"{total_rows:,}".replace(",", "."),
                "note": "",
                "accent": "#64748b",
            },
        ]
    )

    section_band(
        "01 · FONTES",
        "BASES COMPARTILHADAS",
        "",
    )
    normalized = []
    for source in sources:
        normalized.append(
            {
                **source,
                "last_update_label": store.format_dt(source.get("last_update_at")),
            }
        )
    st.markdown(
        '<div class="source-grid">'
        + "".join(source_card(source) for source in normalized)
        + "</div>",
        unsafe_allow_html=True,
    )

    section_band(
        "02 · ALIMENTAÇÃO",
        "ATUALIZAR BASE DE DADOS",
        "",
    )
    source_options = {
        f"{x['name']} · {x['source_key']}": x["source_key"] for x in sources
    }
    selected_label = st.selectbox("Base de destino", list(source_options.keys()))
    source_key = source_options[selected_label]
    uploaded = st.file_uploader(
        "Relatório",
        type=["xlsx", "xlsm", "xltx", "csv", "xml", "txt", "json"],
        accept_multiple_files=False,
    )

    if uploaded is not None:
        raw = uploaded.getvalue()
        rows_count = _count_rows(uploaded.name, raw)
        p1, p2, p3 = st.columns(3)
        p1.metric("Arquivo", uploaded.name)
        p2.metric("Tamanho", f"{len(raw) / 1024:.1f} KB")
        p3.metric("Linhas detectadas", rows_count if rows_count else "—")
        if st.button(
            "SALVAR NA CENTRAL DE DADOS",
            type="primary",
            use_container_width=True,
        ):
            try:
                store.save_report(
                    source_key,
                    uploaded.name,
                    raw,
                    rows_count=rows_count,
                )
                st.success("Base atualizada e histórico registrado.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar a carga: {exc}")

    section_band(
        "03 · RASTREABILIDADE",
        "HISTÓRICO DE CARGAS",
        "",
    )
    imports = store.list_imports(limit=100)
    if imports:
        frame = pd.DataFrame(imports)
        rename = {
            "source_key": "Base",
            "file_name": "Arquivo",
            "rows_count": "Registros",
            "origin": "Origem",
            "imported_at": "Data/Hora",
        }
        wanted = [x for x in rename if x in frame.columns]
        view = frame[wanted].rename(columns=rename)
        if "Data/Hora" in view.columns:
            view["Data/Hora"] = view["Data/Hora"].map(store.format_dt)
        st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma carga registrada até o momento.")


page = render_sidebar()
render_logo()

if page == "Monitor de APIs":
    render_monitor()
else:
    render_database()

st.markdown(
    '<div class="footer">SETTA · Monitor de APIs e Central de Dados</div>',
    unsafe_allow_html=True,
)
