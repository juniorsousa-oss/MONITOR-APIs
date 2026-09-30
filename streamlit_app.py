from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import data_store as store
import monitor_logic as monitor
from ui import api_card, inject_css, kpi_grid, logo_html, section_band, source_card

TZ = ZoneInfo("America/Sao_Paulo")

st.set_page_config(
    page_title="MONITOR DE APIs | SETTA",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# A tela apenas lê os resultados. O worker é responsável pelos testes das APIs.
st_autorefresh(interval=30_000, limit=None, key="setta_monitor_refresh")


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-brand-title">MONITOR DE APIs</div>
                <div class="sidebar-brand-sub">Central operacional SETTA</div>
            </div>
            <div class="sidebar-section-label">Navegação</div>
            """,
            unsafe_allow_html=True,
        )
        page = st.radio(
            "Navegação",
            ["Monitor de APIs", "Banco de Dados"],
            label_visibility="collapsed",
        )
        st.markdown("---")
        if store.supabase_enabled():
            st.success("Banco central conectado", icon="✓")
        else:
            st.info("Modo local de validação", icon="ℹ")
        st.caption("Atualização visual automática a cada 30 segundos.")
    return page


def render_logo() -> None:
    st.markdown(
        f'<div class="setta-logo-card">{logo_html()}</div>',
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str, pill: str) -> None:
    st.markdown(
        f"""
        <div class="app-head">
            <div>
                <div class="app-title">{title}</div>
                <div class="app-sub">{subtitle}</div>
            </div>
            <div class="system-pill"><span class="pulse"></span>{pill}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
        return "MODO DEMONSTRAÇÃO"
    dates = [store.parse_dt(x.get("last_check_at")) for x in real]
    dates = [x for x in dates if x]
    if not dates:
        return "AGUARDANDO PRIMEIRO CICLO"
    age = (datetime.now(TZ) - max(dates)).total_seconds()
    return "MONITORAMENTO ATIVO 24/7" if age <= 180 else "SEM CICLO RECENTE"


def render_api_registration() -> None:
    with st.expander("CADASTRAR NOVA API", expanded=False):
        st.caption(
            "O token não é salvo no cadastro. Para APIs autenticadas, informe apenas "
            "o nome de uma variável de ambiente em 'Referência do segredo'."
        )
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
                help="Nome da variável de ambiente. O valor pode ser um token ou um JSON de headers.",
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
                st.success("API cadastrada. O worker passará a monitorá-la no próximo ciclo.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar a API: {exc}")


def render_monitor() -> None:
    raw_apis = store.list_apis(include_demo=True)
    apis = monitor.hydrate_all(raw_apis)

    render_header(
        "MONITOR DE APIs",
        "Disponibilidade • Integrações • Desempenho • Histórico operacional",
        _monitor_pill(apis),
    )

    if apis and all(x.get("demo") for x in apis):
        st.markdown(
            """
            <div class="notice">
                <b>Modo de demonstração.</b> Estes três cartões servem somente para validar o layout.
                Assim que a primeira API real for cadastrada, os exemplos deixam de aparecer.
            </div>
            """,
            unsafe_allow_html=True,
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
                "note": "Integrações visíveis",
                "accent": "#111827",
            },
            {
                "label": "Online",
                "value": online,
                "note": "Operação normal",
                "accent": "#22c55e",
            },
            {
                "label": "Atenção",
                "value": attention,
                "note": "Degradação / latência",
                "accent": "#f59e0b",
            },
            {
                "label": "Offline",
                "value": offline,
                "note": "Exigem tratativa",
                "accent": "#ef4444",
            },
        ]
    )

    real_apis = [x for x in raw_apis if not x.get("demo")]
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
        "Cada cartão concentra status, HTTP, latência, uptime e a última comunicação registrada.",
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

            if st.button("EXCLUIR API SELECIONADA", type="secondary"):
                store.delete_api(str(selected.get("id")))
                st.rerun()

    section_band(
        "02 · OCORRÊNCIAS",
        "INCIDENTES RECENTES",
        "Falhas de comunicação e degradações permanecem registradas até a normalização.",
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
    elif apis and all(x.get("demo") for x in apis):
        st.info("Os incidentes reais aparecerão aqui depois do cadastro e monitoramento das APIs.")
    else:
        st.success("Nenhum incidente registrado.")


def render_database() -> None:
    render_header(
        "BANCO DE DADOS",
        "Central de alimentação • Histórico • Fontes compartilhadas entre os aplicativos SETTA",
        "CENTRAL DE DADOS",
    )

    if not store.supabase_enabled():
        st.markdown(
            """
            <div class="notice">
                <b>Validação local ativa.</b> Os uploads funcionam para teste nesta instância.
                Para que todos os aplicativos consumam a mesma base de forma permanente,
                configure o Supabase e execute o arquivo <b>supabase_schema.sql</b>.
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="notice ok-notice"><b>Banco central conectado.</b> Metadados e arquivos são persistidos no Supabase.</div>',
            unsafe_allow_html=True,
        )

    sources = store.list_sources()
    updated = sum(1 for x in sources if str(x.get("status")).upper() == "ATUALIZADO")
    total_rows = sum(int(x.get("rows_count") or 0) for x in sources)

    kpi_grid(
        [
            {
                "label": "Bases previstas",
                "value": len(sources),
                "note": "Fontes centrais",
                "accent": "#111827",
            },
            {
                "label": "Atualizadas",
                "value": updated,
                "note": "Com carga registrada",
                "accent": "#22c55e",
            },
            {
                "label": "Aguardando",
                "value": len(sources) - updated,
                "note": "Sem carga atual",
                "accent": "#f59e0b",
            },
            {
                "label": "Registros",
                "value": f"{total_rows:,}".replace(",", "."),
                "note": "Últimas cargas",
                "accent": "#64748b",
            },
        ]
    )

    section_band(
        "01 · FONTES",
        "BASES COMPARTILHADAS",
        "Cada base poderá abastecer vários aplicativos sem duplicar arquivos ou regras de origem.",
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
        "Nesta primeira versão aceitamos Excel, CSV, XML e arquivos de texto. As regras específicas de tratamento serão adicionadas por base.",
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
        "Registro cronológico das atualizações realizadas na Central de Dados.",
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
