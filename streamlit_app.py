from __future__ import annotations

import base64
import io
import re
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_autorefresh import st_autorefresh

import data_store as store
import monitor_logic as monitor
from ui import api_card, derived_card, inject_css, kpi_grid, logo_html, section_band, source_card
import ui as ui_components

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


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">'
            '<div class="sidebar-brand-title">MONITOR DE APIs</div>'
            '<div class="sidebar-brand-sub">Central operacional SETTA</div>'
            '</div>'
            '<div class="sidebar-section-label">NAVEGAÇÃO</div>',
            unsafe_allow_html=True,
        )
        page = st.radio(
            "NAVEGAÇÃO",
            ["MONITOR DE APIs", "BANCO DE DADOS"],
            label_visibility="collapsed",
            key="central_monitor_page",
        )

        # A tela de Banco de Dados pode processar arquivos grandes.
        # Não interromper uploads/processamentos com o refresh de 30 segundos.
        if page == "MONITOR DE APIs":
            st_autorefresh(
                # O monitor 24/7 roda no Supabase a cada 2 minutos.
                # A UI acompanha o mesmo ciclo para reduzir consumo no Streamlit.
                interval=120_000,
                limit=None,
                key="setta_monitor_refresh",
            )

        st.markdown("---")
        st.markdown(
            '<div class="sidebar-info-card">'
            '<b>CENTRAL DE DADOS</b><br>'
            'IDENTIDADE VISUAL GLOBAL<br>'
            'ATUALIZAÇÃO AUTOMÁTICA · 30 S'
            '</div>',
            unsafe_allow_html=True,
        )
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
    """Conta linhas sem materializar planilhas Excel grandes no pandas."""
    lower = name.lower()
    try:
        if lower.endswith(".csv"):
            # Não cria DataFrame só para metadado de quantidade.
            text = raw.decode("utf-8-sig", errors="ignore")
            lines = [line for line in text.splitlines() if line.strip()]
            return max(len(lines) - 1, 0)

        if lower.endswith((".xlsx", ".xlsm", ".xltx")):
            # XLSX/XLSM/XLTX são ZIPs. O atributo dimension da primeira
            # worksheet informa a última linha e evita ler milhões de células.
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                sheet_names = sorted(
                    path
                    for path in archive.namelist()
                    if re.fullmatch(
                        r"xl/worksheets/sheet\d+\.xml",
                        path,
                    )
                )
                if not sheet_names:
                    return 0

                xml = archive.read(sheet_names[0])[:200_000]
                match = re.search(
                    rb'<dimension[^>]+ref="[A-Z]+\d+:?[A-Z]*(\d+)"',
                    xml,
                )
                if match:
                    last_row = int(match.group(1))
                    # Quantidade usada apenas como metadado/status.
                    # Desconta uma linha de cabeçalho sem carregar a planilha.
                    return max(last_row - 1, 0)

            return 0
    except Exception:
        return 0
    return 0


def _monitor_pill(apis: list[dict]) -> str:
    if not store.monitor_shared_enabled():
        return "BACKEND COMPARTILHADO INDISPONÍVEL"
    real = [x for x in apis if not x.get("demo")]
    if not real:
        return "SEM APIs"
    dates = [store.parse_dt(x.get("last_check_at")) for x in real]
    dates = [x for x in dates if x]
    if not dates:
        return "WORKER · AGUARDANDO PRIMEIRO CICLO"
    age = (datetime.now(TZ) - max(dates)).total_seconds()
    return "WORKER ATIVO 24/7" if age <= 180 else "WORKER · SEM CICLO RECENTE"


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

    restart_id = str(st.query_params.get("restart_api") or "").strip()
    if restart_id:
        target = next(
            (api for api in raw_apis if str(api.get("id") or "") == restart_id),
            None,
        )
        try:
            if target is None:
                raise ValueError("API não encontrada.")
            result = monitor.restart_api(target)
            attempts = int(result.get("restart_attempts") or 1)
            ok = bool(result.get("success"))
            st.session_state["_api_restart_notice"] = {
                "ok": ok,
                "message": (
                    f"{target.get('name')}: conexão restabelecida em {attempts} tentativa(s)."
                    if ok
                    else (
                        f"{target.get('name')}: a reinicialização foi executada, mas a API continua "
                        f"indisponível. {result.get('error_message') or 'Verifique a origem.'}"
                    )
                ),
            }
        except Exception as exc:
            st.session_state["_api_restart_notice"] = {
                "ok": False,
                "message": f"Não foi possível reiniciar a API: {exc}",
            }
        st.query_params.clear()
        st.rerun()

    apis = monitor.hydrate_all(raw_apis)
    integrations = store.list_integrations()

    render_header(
        "MONITOR DE APIs | SETTA",
        "APIS • INTEGRAÇÕES • DISPONIBILIDADE",
        _monitor_pill(apis),
    )

    if not store.monitor_shared_enabled():
        st.error(
            "BACKEND COMPARTILHADO INDISPONÍVEL: a Central de Dados SETTA não está "
            "acessível para persistir os checks do Monitor. Verifique a Edge Function "
            "setta-data-api antes de executar novos ciclos."
        )

    restart_notice = st.session_state.pop("_api_restart_notice", None)
    if restart_notice:
        if restart_notice.get("ok"):
            st.success(str(restart_notice.get("message") or "API reiniciada."))
        else:
            st.error(str(restart_notice.get("message") or "Falha ao reiniciar a API."))

    active = [x for x in apis if str(x.get("status")).upper() != "DESATIVADA"]
    online = sum(1 for x in active if str(x.get("status")).upper() == "ONLINE")
    attention = sum(1 for x in active if str(x.get("status")).upper() == "ATENÇÃO")
    offline = sum(1 for x in active if str(x.get("status")).upper() == "OFFLINE")

    integration_online = sum(
        1 for item in integrations if str(item.get("status")).upper() == "ONLINE"
    )
    integration_attention = sum(
        1 for item in integrations if str(item.get("status")).upper() == "ATENÇÃO"
    )
    integration_offline = sum(
        1 for item in integrations if str(item.get("status")).upper() == "OFFLINE"
    )

    kpi_grid(
        [
            {
                "label": "APIs / serviços",
                "value": len(active),
                "note": f"{online} online",
                "accent": "#111827",
            },
            {
                "label": "Serviços online",
                "value": online,
                "note": f"{attention} atenção • {offline} offline",
                "accent": "#22c55e" if offline == 0 else "#ef4444",
            },
            {
                "label": "Integrações",
                "value": len(integrations),
                "note": "",
                "accent": "#111827",
            },
            {
                "label": "Integrações OK",
                "value": integration_online,
                "note": f"{integration_attention} atenção • {integration_offline} offline",
                "accent": "#22c55e" if integration_offline == 0 else "#ef4444",
            },
        ]
    )

    real_apis = list(apis)
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
        "01 · SERVIÇOS",
        "APIS E ENDPOINTS",
        "",
    )
    st.markdown(
        '<div class="api-grid">' + "".join(api_card(api) for api in apis) + "</div>",
        unsafe_allow_html=True,
    )

    if real_apis:
        with st.expander("DETALHES", expanded=False):
            api_map = {str(x.get("name")): x for x in real_apis}
            selected_name = st.selectbox("API", list(api_map.keys()))
            selected = api_map[selected_name]
            h1, h2, h3 = st.columns(3)
            h1.metric("Método", selected.get("method") or "GET")
            h2.metric("HTTP esperado", selected.get("expected_status") or 200)
            h3.metric("Timeout", f"{selected.get('timeout_seconds') or 10}s")
            if selected.get("source_app") or selected.get("target_app"):
                st.caption(
                    "CONEXÃO · "
                    + str(selected.get("source_app") or "—")
                    + " → "
                    + str(selected.get("target_app") or "—")
                )
                st.caption(
                    "SERVIÇO · "
                    + str(selected.get("service") or "—")
                    + "  |  RECURSO · "
                    + str(selected.get("resource") or "—")
                )
                st.caption(
                    "LOCAL DA CONEXÃO · "
                    + str(selected.get("code_location") or "—")
                )
            st.code(str(selected.get("endpoint") or ""), language=None)

            if selected.get("system"):
                meta = selected.get("integration_meta") or {}
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Carga", f"#{meta.get('carga_id') or '—'}")
                s2.metric("Itens", meta.get("total_itens") or 0)
                s3.metric("Produtos", meta.get("total_produtos") or 0)
                s4.metric("Últ. fonte", meta.get("ultima_verificacao_label") or "—")
            else:
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

                if not selected.get("system") and st.button("EXCLUIR API SELECIONADA", type="secondary"):
                    store.delete_api(str(selected.get("id")))
                    st.rerun()

    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "02 · INTEGRAÇÕES",
        "FLUXOS ENTRE APLICATIVOS",
        "",
    )
    st.markdown(
        '<div class="integration-grid">'
        + "".join(ui_components.integration_card(item) for item in integrations)
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "03 · COBERTURA",
        "MAPA DE CONEXÕES",
        "Origem, destino e local técnico de cada integração conhecida.",
    )
    coverage = pd.DataFrame(store.connection_coverage())
    if not coverage.empty:
        coverage = coverage.rename(
            columns={
                "connection": "CONEXÃO",
                "source": "ORIGEM",
                "target": "DESTINO",
                "service": "SERVIÇO",
                "resource": "RECURSO",
                "code": "LOCAL DA CONEXÃO",
                "monitoring": "MONITORAMENTO",
            }
        )
        st.dataframe(
            coverage,
            use_container_width=True,
            hide_index=True,
            column_config={
                "CONEXÃO": st.column_config.TextColumn(width="medium"),
                "ORIGEM": st.column_config.TextColumn(width="medium"),
                "DESTINO": st.column_config.TextColumn(width="medium"),
                "SERVIÇO": st.column_config.TextColumn(width="medium"),
                "RECURSO": st.column_config.TextColumn(width="large"),
                "LOCAL DA CONEXÃO": st.column_config.TextColumn(width="large"),
                "MONITORAMENTO": st.column_config.TextColumn(width="medium"),
            },
        )

    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "04 · OCORRÊNCIAS",
        "INCIDENTES RECENTES",
        "",
    )
    incidents = store.list_incidents(limit=12)
    for item in integrations:
        if str(item.get("status")).upper() in {"OFFLINE", "ATENÇÃO"}:
            incidents = [
                {
                    "started_at": item.get("last_activity_at"),
                    "api_name": item.get("name"),
                    "kind": "INTEGRAÇÃO",
                    "status": "ABERTO",
                    "resolved_at": None,
                }
            ] + incidents
    for api in apis:
        if api.get("system") and str(api.get("status")).upper() in {"OFFLINE", "ATENÇÃO"}:
            incidents = [
                {
                    "started_at": api.get("last_check_at"),
                    "api_name": api.get("name"),
                    "kind": "STATUS ATUAL",
                    "status": "ABERTO",
                    "resolved_at": None,
                }
            ] + incidents
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
        "Fontes • Processamentos • Alimentação",
        "CENTRAL DE DADOS",
    )

    sources = store.list_sources()
    derived = store.list_derived_bases()
    updated = sum(
        1
        for item in sources
        if str(item.get("status")).upper() == "ATUALIZADO"
    )

    system_status = monitor.hydrate_all(store.system_apis())
    active_apis = sum(
        1
        for item in system_status
        if str(item.get("status")).upper() == "ONLINE"
    )

    for base in derived:
        if base.get("key") == "materiais_api" and system_status:
            api_status = str(system_status[0].get("status") or "SEM DADOS").upper()
            base["mode"] = f"API {api_status}"

    kpi_grid(
        [
            {
                "label": "Fontes de origem",
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
                "label": "Bases derivadas",
                "value": len(derived),
                "note": "",
                "accent": "#64748b",
            },
            {
                "label": "APIs ativas",
                "value": active_apis,
                "note": "",
                "accent": "#2563eb",
            },
        ]
    )

    section_band(
        "01 · ORIGEM",
        "FONTES DE DADOS",
        "",
    )
    normalized = [
        {
            **source,
            "last_update_label": store.format_dt(
                source.get("last_update_at")
            ),
        }
        for source in sources
    ]
    st.markdown(
        '<div class="source-grid">'
        + "".join(source_card(source) for source in normalized)
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "02 · PROCESSAMENTO",
        "BASES DERIVADAS",
        "",
    )
    st.markdown(
        '<div class="derived-grid">'
        + "".join(derived_card(base) for base in derived)
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "03 · ALIMENTAÇÃO",
        "ATUALIZAR FONTE",
        "",
    )

    source_map = {
        f"{item['name']} · {item['source_system']}": item
        for item in sources
    }

    preset = st.radio(
        "PACOTE DE ALIMENTAÇÃO",
        [
            "PERSONALIZADO",
            "RELATÓRIO GERAL",
            "ESTOQUE",
            "COMPRAS",
            "TCTP",
        ],
        horizontal=True,
        key="central_feed_preset",
    )

    preset_keys = {
        "RELATÓRIO GERAL": {"relatorio_geral", "for001", "for022"},
        "ESTOQUE": {"analitico", "endereco"},
        "COMPRAS": {"sc", "pc", "pre_nota"},
        "TCTP": {"pmp", "h001"},
    }

    default_labels = []
    if preset != "PERSONALIZADO":
        wanted = preset_keys[preset]
        default_labels = [
            label
            for label, item in source_map.items()
            if item.get("source_key") in wanted
        ]

    selected_labels = st.multiselect(
        "FONTES A ATUALIZAR",
        list(source_map.keys()),
        default=default_labels,
        key=f"central_source_multi_{preset}",
    )

    selected_sources = [source_map[label] for label in selected_labels]
    uploads = {}

    for source in selected_sources:
        source_key = source["source_key"]
        st.markdown(
            f"**{source['name']}** · {source['source_system']} · "
            f"última atualização {store.format_dt(source.get('last_update_at'))}"
        )
        uploaded = st.file_uploader(
            f"ARQUIVO — {source['name']}",
            type=["xlsx", "xls", "xlsm", "xltx", "csv", "xml", "txt", "json"],
            accept_multiple_files=False,
            key=f"central_batch_upload_{source_key}",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            raw = uploaded.getvalue()
            uploads[source_key] = {
                "source": source,
                "file": uploaded,
                "raw": raw,
                "rows_count": _count_rows(uploaded.name, raw),
            }

    if selected_sources:
        ready = len(uploads) == len(selected_sources)
        if not ready:
            missing = [
                source["name"]
                for source in selected_sources
                if source["source_key"] not in uploads
            ]
            st.caption("AGUARDANDO ARQUIVO: " + " • ".join(missing))

        if st.button(
            "ATUALIZAR FONTES",
            type="primary",
            use_container_width=True,
            disabled=not ready,
            key="save_selected_sources",
        ):
            progress = st.progress(0)
            status = st.empty()
            total = len(selected_sources)
            updated_names = []
            try:
                for index, source in enumerate(selected_sources, start=1):
                    item = uploads[source["source_key"]]
                    status.write(f"Atualizando {source['name']}...")
                    store.save_report(
                        source["source_key"],
                        item["file"].name,
                        item["raw"],
                        rows_count=item["rows_count"],
                        origin=source.get("source_system") or "UPLOAD",
                    )
                    updated_names.append(source["name"])
                    progress.progress(index / total)

                status.empty()
                progress.empty()
                st.success(
                    f"{len(updated_names)} fonte(s) atualizada(s): "
                    + " • ".join(updated_names)
                )
                st.rerun()
            except Exception as exc:
                st.error(
                    "Falha durante a carga. Fontes concluídas antes do erro: "
                    + (" • ".join(updated_names) if updated_names else "nenhuma")
                    + f". Erro: {exc}"
                )

    st.markdown('<div class="topic-divider"></div>', unsafe_allow_html=True)
    section_band(
        "04 · PADRÃO SETTA",
        "IDENTIDADE VISUAL GLOBAL",
        "",
    )

    current_logo = logo_html(
        str(VISUAL_CONFIG.get("logo_data") or ""),
        str(VISUAL_CONFIG.get("logo_mime") or "image/svg+xml"),
    )
    st.markdown(
        f'<div class="global-visual-preview">{current_logo}</div>',
        unsafe_allow_html=True,
    )

    v1, v2 = st.columns(2)
    logo_file = v1.file_uploader(
        "LOGO GLOBAL",
        type=["png", "jpg", "jpeg", "webp", "svg"],
        key="global_logo_file",
    )
    favicon_file = v2.file_uploader(
        "FAVICON GLOBAL",
        type=["png", "jpg", "jpeg", "ico"],
        key="global_favicon_file",
    )

    save_col, reset_col = st.columns(2)
    if save_col.button(
        "SALVAR IDENTIDADE GLOBAL",
        type="primary",
        use_container_width=True,
        key="save_global_visual_config",
    ):
        if logo_file is None and favicon_file is None:
            st.warning("Selecione a logo ou o favicon.")
        else:
            try:
                kwargs = {}
                if logo_file is not None:
                    raw_logo = logo_file.getvalue()
                    if len(raw_logo) > 2 * 1024 * 1024:
                        raise ValueError("A logo deve ter no máximo 2 MB.")
                    kwargs["logo_data"] = base64.b64encode(raw_logo).decode()
                    kwargs["logo_mime"] = logo_file.type or "image/png"

                if favicon_file is not None:
                    raw_icon = favicon_file.getvalue()
                    if len(raw_icon) > 1 * 1024 * 1024:
                        raise ValueError("O favicon deve ter no máximo 1 MB.")
                    image = Image.open(io.BytesIO(raw_icon))
                    image.verify()
                    kwargs["favicon_data"] = base64.b64encode(raw_icon).decode()
                    kwargs["favicon_mime"] = favicon_file.type or "image/png"

                store.save_visual_config(**kwargs)
                st.success("Identidade visual global atualizada.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar: {exc}")

    if reset_col.button(
        "RESTAURAR PADRÃO",
        use_container_width=True,
        key="reset_global_visual_config",
    ):
        store.reset_visual_config()
        st.rerun()


page = render_sidebar()
render_logo()

if page == "MONITOR DE APIs":
    render_monitor()
else:
    render_database()

st.markdown(
    '<div class="footer">SETTA · Monitor de APIs e Central de Dados</div>',
    unsafe_allow_html=True,
)
