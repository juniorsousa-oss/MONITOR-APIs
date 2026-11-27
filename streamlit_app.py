from __future__ import annotations

import base64
import hashlib
import hmac
import os
import io
import re
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# Padrão SETTA: tabelas responsivas ao total de registros exibidos nos filtros.
def _setta_table_height(data, requested=None):
    """Altura baseada nas linhas reais (DataFrame ou pandas.Styler)."""
    if isinstance(requested, str):
        return requested
    frame = getattr(data, "data", data)
    try:
        rows = len(frame)
    except (TypeError, ValueError, AttributeError):
        return requested if isinstance(requested, int) and requested >= 120 else None
    ceiling = max(120, requested) if isinstance(requested, int) and requested > 0 else 600
    return int(min(ceiling, max(120, 42 + 35 * (min(max(0, rows), 100) + 1))))


def _setta_dataframe(data, *args, **kwargs):
    height = _setta_table_height(data, kwargs.get("height"))
    if height is None:
        kwargs.pop("height", None)
    else:
        kwargs["height"] = height
    return st.dataframe(data, *args, **kwargs)


def _setta_data_editor(data, *args, **kwargs):
    if kwargs.get("num_rows") != "dynamic":
        height = _setta_table_height(data, kwargs.get("height"))
        if height is None:
            kwargs.pop("height", None)
        else:
            kwargs["height"] = height
    return st.data_editor(data, *args, **kwargs)


from PIL import Image, ImageOps, UnidentifiedImageError
from streamlit_autorefresh import st_autorefresh

import data_store as store
import monitor_logic as monitor
from mes_refresh_flow import ManualRefreshGuard, estado_relatorio_tratado
from ui import api_card, derived_card, inject_css, kpi_grid, logo_html, section_band, source_card
import ui as ui_components

TZ = ZoneInfo("America/Sao_Paulo")
VISUAL_CONFIG = store.load_visual_config()


@st.cache_resource
def _mes_manual_guard() -> ManualRefreshGuard:
    """Uma sincronização MES por vez e intervalo mínimo entre tentativas."""
    return ManualRefreshGuard(cooldown_seconds=120)


@st.fragment(run_every="15s")
def _mes_await_derived():
    """Acompanha o Conversor sem repetir GET à MES nem bloquear a interface."""
    expected = int(st.session_state.get("_mes_pending_version") or 0)
    if not expected:
        return
    try:
        base = next(
            (x for x in store.list_derived_bases()
             if x.get("key") == "relatorio_geral_tratado"), {},
        )
        source = next(
            (x for x in store.list_sources()
             if x.get("source_key") == "relatorio_geral"), {},
        )
        current_source = int(source.get("version") or expected)
        desired = max(expected, current_source)
        status, treated = estado_relatorio_tratado(desired, base)
    except Exception:
        st.warning(
            "A fonte foi publicada, mas ainda não foi possível consultar "
            "a conclusão do Conversor MRP. Não é necessário reprocessar."
        )
        return

    if status == "CONCLUIDO":
        st.session_state["_mes_pending_version"] = 0
        st.session_state["mes_manual_result"] = {
            "kind": "success",
            "message": (
                f"Atualização completa: Relatório Geral v{desired} e "
                f"Tratado v{treated} sincronizados. Apenas uma consulta MES."
            ),
        }
        st.rerun()
    elif status == "ERRO_CONVERSOR":
        st.error(
            f"Relatório Geral v{desired} publicado, mas o Conversor MRP "
            f"não concluiu (Tratado v{treated}). Verifique o processamento; "
            "reconsultar a MES não corrigirá esse erro."
        )
    else:
        st.info(
            f"Etapa 1/2: fonte MES v{desired} publicada. "
            f"Etapa 2/2: aguardando Relatório Geral Tratado (v{treated}). "
            "Atualização automática desta mensagem a cada 15 s; "
            "não clique em Reprocessar novamente."
        )


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


def prepare_favicon(raw: bytes) -> bytes:
    """Normaliza imagens enviadas (ate 10 MB) em favicon PNG transparente, 256x256."""
    max_upload_bytes = 10 * 1024 * 1024
    if len(raw) > max_upload_bytes:
        raise ValueError("O favicon deve ter no máximo 10 MB.")

    try:
        with Image.open(io.BytesIO(raw)) as source:
            # Evita consumo excessivo de memória ao decodificar imagens enormes.
            if source.width * source.height > 40_000_000:
                raise ValueError("A imagem do favicon tem resolução muito alta.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Arquivo de favicon inválido. Envie PNG, JPG, WEBP ou ICO.") from exc

    # Mantém proporções e canal alfa. Centralizar evita cortes em logos não quadradas.
    image = ImageOps.contain(image, (256, 256), method=Image.Resampling.LANCZOS)
    icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    icon.alpha_composite(image, ((256 - image.width) // 2, (256 - image.height) // 2))

    output = io.BytesIO()
    icon.save(output, format="PNG", optimize=True)
    return output.getvalue()


st.set_page_config(
    page_title="MONITOR DE APIs | SETTA",
    page_icon=browser_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# A tela apenas lê os resultados. O worker é responsável pelos testes das APIs.


MONITOR_ROUTES = ("MONITOR DE APIs", "BANCO DE DADOS")
MONITOR_LABELS = ("Monitor de APIs", "Banco de Dados")
MONITOR_ICONS = ("monitoring", "database")


def _set_monitor_page(target: int) -> None:
    st.session_state["monitor_route"] = target


def render_sidebar() -> str:
    legacy = st.session_state.get("central_monitor_page")
    initial = MONITOR_ROUTES.index(legacy) if legacy in MONITOR_ROUTES else 0
    route = st.session_state.get("monitor_route", initial)
    with st.sidebar:
        with st.container(key="setta_route_list"):
            st.html('<div class="sidebar-brand">Navegação</div>')
            for index, label in enumerate(MONITOR_LABELS):
                st.button(label, key=f"setta_nav_{index}", width="stretch",
                          type="primary" if index == route else "secondary",
                          icon=f":material/{MONITOR_ICONS[index]}:",
                          on_click=_set_monitor_page, args=(index,))
        with st.container(key="monitor_sidebar_status"):
            if route == 0:
                st.html(
                    '<div class="sidebar-section-label">Monitoramento</div>'
                    '<div class="sidebar-status-card"><div class="sidebar-status-name">'
                    'Atualização automática</div><div class="sidebar-status-meta">'
                    'A cada 2 minutos</div></div>'
                )
                # Banco de Dados não atualiza sozinho enquanto recebe arquivos.
                st_autorefresh(interval=120_000, limit=None, key="setta_monitor_refresh")
    return MONITOR_ROUTES[route]


def render_header(title: str, subtitle: str, pill: str) -> None:
    route = 1 if title == "BANCO DE DADOS | SETTA" else 0
    label = MONITOR_LABELS[route]
    st.markdown(
        f'<div class="monitor-page-head"><div class="setta-inv-intro" data-setta-route="{route}">'
        f'<div class="setta-inv-breadcrumb">Setta / {label}</div><h1>{label}</h1>'
        f'<p>{ui_components.esc(subtitle)}</p></div>'
        f'<div class="system-pill"><span class="pulse"></span>{ui_components.esc(pill)}</div></div>',
        unsafe_allow_html=True,
    )


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


def _api_status(item):
    if not item.get("active", True):
        return "DESATIVADA"
    return str(item.get("status") or "SEM DADOS").upper()


def _status_rows(items, *, attention=False):
    rows = []
    for category, item in items:
        status = _api_status(item)
        timestamp = item.get("last_check_at") or item.get("last_activity_at")
        row = {"Conexão": item.get("name") or "—", "Tipo": category,
               "Status": status, "Última verificação": store.format_dt(timestamp)}
        if attention:
            http = item.get("last_http_status")
            row["Próximo passo"] = (
                "Verificar a origem" if status == "OFFLINE" else
                "Aguardar a primeira verificação" if status in {"SEM DADOS", "AGUARDANDO"} else
                "Conferir latência e detalhes" if http == 200 else "Conferir a conexão"
            )
        rows.append(row)
    return rows


def _render_selected_api(apis, *, maintenance=False):
    api_map = {str(x["id"]): x for x in apis if x.get("id")}
    selected_id = st.selectbox(
        "Detalhes de uma API", list(api_map), index=None, placeholder="Selecione uma API",
        format_func=lambda key: str(api_map[key].get("name") or key),
        key="monitor_api_maintenance" if maintenance else "monitor_api_detail",
    )
    if not selected_id:
        return
    api = api_map[selected_id]
    if not maintenance:
        detail = monitor.hydrate_api(api)
        st.markdown(api_card(detail), unsafe_allow_html=True)
        if api.get("active", True) and st.button("Revalidar conexão", key="monitor_revalidate"):
            try:
                with st.spinner("Verificando conexão..."):
                    result = monitor.restart_api(api)
                outcome = str(result.get("status") or "SEM DADOS")
                st.session_state["_monitor_check_notice"] = f"{api.get('name')}: {outcome}."
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível revalidar a conexão: {exc}")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Método", api.get("method") or "GET")
    c2.metric("HTTP esperado", api.get("expected_status") or 200)
    c3.metric("Timeout", f"{api.get('timeout_seconds') or 10}s")
    st.caption("Conexão: " + str(api.get("source_app") or "—") + " → " + str(api.get("target_app") or "—"))
    st.caption("Recurso: " + str(api.get("resource") or "—"))
    st.caption("Local da conexão: " + str(api.get("code_location") or "—"))
    st.code(str(api.get("endpoint") or ""), language=None)
    if st.toggle("Consultar últimas verificações", key="monitor_show_checks_" + selected_id):
        checks = store.list_checks(selected_id, limit=50)
        if checks:
            columns = ("checked_at","status","http_status","latency_ms","success","error_message")
            frame = pd.DataFrame(checks)
            _setta_dataframe(frame[[c for c in columns if c in frame.columns]], width="stretch", hide_index=True)
        else:
            st.info("Nenhuma verificação registrada.")
    if not api.get("system"):
        confirmed = st.checkbox("Confirmar exclusão desta API do Monitor", key="monitor_confirm_delete_" + selected_id)
        if st.button("Excluir API", disabled=not confirmed, key="monitor_delete_" + selected_id):
            try:
                store.delete_api(selected_id)
                st.session_state["_monitor_check_notice"] = f"{api.get('name')}: API excluída do Monitor."
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível excluir a API: {exc}")


def render_monitor() -> None:
    apis = store.list_apis(include_demo=False)
    integrations = store.list_integrations()
    render_header("MONITOR DE APIs | SETTA", "Saúde das conexões", _monitor_pill(apis))
    if notice := st.session_state.pop("_monitor_check_notice", None):
        st.info(notice)
    if not store.monitor_shared_enabled():
        st.error("Central de Dados indisponível para registrar verificações.")

    items = ([("API", api) for api in apis] + [("Integração", item) for item in integrations])
    statuses = [_api_status(item) for _, item in items]
    active = [status for status in statuses if status != "DESATIVADA"]
    kpi_grid([
        {"label": "Online", "value": active.count("ONLINE"), "accent": "#22c55e"},
        {"label": "Em atenção", "value": active.count("ATENÇÃO"), "accent": "#ffbb00"},
        {"label": "Offline", "value": active.count("OFFLINE"), "accent": "#ef4444"},
        {"label": "Sem verificação", "value": sum(s not in {"ONLINE", "ATENÇÃO", "OFFLINE"} for s in active)},
    ])

    view = st.segmented_control("Visualização do Monitor",
        ["Pendências", "Conexões", "Incidentes", "Manutenção"], default="Pendências",
        required=True, key="monitor_view", label_visibility="collapsed")
    if view == "Pendências":
        priority = {"OFFLINE": 0, "ATENÇÃO": 1}
        queue = sorted((x for x in items if _api_status(x[1]) not in {"ONLINE", "DESATIVADA"}),
                       key=lambda x: (priority.get(_api_status(x[1]), 2), str(x[1].get("name") or "")))
        if queue:
            _setta_dataframe(pd.DataFrame(_status_rows(queue, attention=True)), width="stretch", hide_index=True)
            affected = {str(item.get("id")) for category, item in queue if category == "API"}
            if affected:
                _render_selected_api([api for api in apis if str(api.get("id")) in affected])
        else:
            st.success("Nenhuma conexão exige atenção." if active else "Sem conexões verificadas.")
    elif view == "Conexões":
        term = st.text_input("Buscar conexão").strip().casefold()
        status_filter = st.selectbox("Status", ["Todos", *sorted(set(statuses))])
        filtered = [x for x in items if term in str(x[1].get("name") or "").casefold()
                    and (status_filter == "Todos" or _api_status(x[1]) == status_filter)]
        if filtered:
            _setta_dataframe(pd.DataFrame(_status_rows(filtered)), width="stretch", hide_index=True)
        else:
            st.info("Nenhuma conexão encontrada.")
        ids = {str(item.get("id")) for category, item in filtered if category == "API"}
        if ids:
            _render_selected_api([api for api in apis if str(api.get("id")) in ids])
        if st.toggle("Detalhes das integrações", key="monitor_integration_details"):
            st.markdown(
                '<div class="integration-grid">'
                + "".join(ui_components.integration_card(item) for item in integrations)
                + "</div>",
                unsafe_allow_html=True,
            )
    elif view == "Incidentes":
        incidents = store.list_incidents(limit=12)
        if incidents:
            rows = [{"Início": store.format_dt(item.get("started_at")), "Conexão": item.get("api_name") or "—",
                     "Tipo": item.get("kind"), "Status": item.get("status"),
                     "Fim": store.format_dt(item.get("resolved_at"))} for item in incidents]
            _setta_dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("Nenhum incidente registrado.")
    else:
        if st.button("Verificar todas agora", type="primary", disabled=not bool(apis)):
            with st.spinner("Verificando conexões..."):
                monitor.run_all_checks()
            st.session_state["_monitor_check_notice"] = "Verificação manual concluída."
            st.rerun()
        render_api_registration()
        _render_selected_api(apis, maintenance=True)
        tool = st.segmented_control("Ferramenta técnica", ["Mapa de conexões", "Homologação MES"], key="monitor_tool")
        if tool == "Mapa de conexões":
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
                _setta_dataframe(
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
        elif tool == "Homologação MES":
            # Homologação controlada: resultado agregado, sem dados brutos, acesso
            # apenas com um segundo segredo que NÃO é o token do serviço MES.
            with st.expander("HOMOLOGAÇÃO — RELATÓRIO GERAL VIA API MES", expanded=False):
                st.caption(
                    "Busca o JSON completo uma única vez, compara com a última fonte "
                    "normalizada Relatório Geral da Central e apresenta apenas indicadores "
                    "agregados. NÃO substitui planilhas, não publica registros e não altera MRP."
                )
                chave_esperada = os.getenv("SETTA_MES_GENERAL_REPORT_VALIDATE_PIN", "")
                if len(chave_esperada) < 12:
                    st.info(
                        "HOMOLOGAÇÃO BLOQUEADA: configure em Streamlit Secrets a variável "
                        "SETTA_MES_GENERAL_REPORT_VALIDATE_PIN com um código privado de "
                        "pelo menos 12 caracteres. Não utilize o token MES como código."
                    )
                else:
                    digitado = st.text_input(
                        "CÓDIGO PRIVADO DE HOMOLOGAÇÃO", type="password",
                        key="mes_homologacao_pin",
                    )
                    autorizado = hmac.compare_digest(digitado, chave_esperada)
                    arquivo_manual = None
                    if autorizado:
                        st.caption(
                            "RECOMENDADO: utilize o Excel manual do mesmo dia da API. "
                            "A fonte atualmente publicada na Central pode estar desatualizada."
                        )
                        arquivo_manual = st.file_uploader(
                            "EXCEL MANUAL — RELATÓRIO GERAL (opcional)",
                            type=["xlsx"], accept_multiple_files=False,
                            key="mes_excel_homologacao_manual",
                        )
                        if arquivo_manual is not None:
                            st.caption(
                                "O arquivo será lido apenas nesta sessão para comparação. "
                                "Não será enviado à Central nem publicado no MRP."
                            )
                    if st.button(
                        "COLETAR E COMPARAR COM O RELATÓRIO ATUAL",
                        use_container_width=True, type="primary",
                        disabled=not autorizado, key="mes_homologar_agora",
                    ):
                        from mes_general_report_validation import coletar_e_comparar
                        with st.spinner("Lendo API MES e comparando a versão da Central de Dados..."):
                            try:
                                # O retorno contém apenas estatísticas; JSON MES não é
                                # guardado no session_state, cache, banco ou navegador.
                                resumo = coletar_e_comparar(
                                    excel_manual_bytes=(
                                        arquivo_manual.getvalue() if arquivo_manual is not None else None
                                    )
                                )
                                st.session_state["_mes_homologacao_resumo"] = resumo
                                politica = resumo.get("politica_continuidade") or {}
                                if politica.get("status") == "PROCESSAR_COM_RESSALVAS":
                                    st.warning(
                                        "Coleta concluída COM RESSALVAS. Os registros válidos estão "
                                        "aptos ao processamento; as exceções seguem em quarentena. "
                                        "Esta tela não publica ou sincroniza o MRP."
                                    )
                                elif politica.get("status") == "PROTEGER_BASE":
                                    st.error(
                                        "Falha estrutural ou volumétrica: manter a última base "
                                        "válida e investigar antes de atualizar."
                                    )
                                else:
                                    st.success("Comparação concluída — nenhuma fonte foi substituída.")
                            except ValueError as exc:
                                st.session_state.pop("_mes_homologacao_resumo", None)
                                st.error(str(exc))
                            except Exception:
                                st.session_state.pop("_mes_homologacao_resumo", None)
                                st.error("Não foi possível concluir a comparação. Verifique a disponibilidade da Central.")
                    resultado = st.session_state.get("_mes_homologacao_resumo")
                    if autorizado and resultado:
                        auditoria = resultado.get("auditoria") or {}
                        if auditoria:
                            st.caption("AUDITORIA ESTRUTURAL DO JSON — SEM DADOS INDIVIDUAIS")
                            a0, a1, a2, a3 = st.columns(4)
                            a0.metric("Registros recebidos", auditoria["total_recebido"])
                            a1.metric("Registros válidos", auditoria["registros_validos"])
                            a2.metric("Pendências de dados", auditoria["registros_pendentes"])
                            a3.metric("Linhas completamente vazias", auditoria["registros_vazios"])
                            if auditoria["registros_pendentes"]:
                                st.warning(
                                    "REGISTROS EM QUARENTENA: itens com inconsistências são "
                                    "isolados para correção; não são incluídos na demanda MRP."
                                )
                                if auditoria["sem_codigo_com_movimento"]:
                                    st.warning(
                                        f'{auditoria["sem_codigo_com_movimento"]} registro(s) sem código '
                                        "possuem quantidade positiva. Devem ser corrigidos na origem."
                                    )
                                motivos = pd.DataFrame([
                                    {"Tipo de inconsistência": tipo, "Registros": qtd}
                                    for tipo, qtd in sorted(auditoria["motivos"].items())
                                ])
                                _setta_dataframe(motivos, use_container_width=True, hide_index=True)
                                st.caption("Exemplos de posições com inconsistência — sem conteúdo sensível:")
                                _setta_dataframe(pd.DataFrame(auditoria["exemplos"]),
                                                 use_container_width=True, hide_index=True)
                                st.caption(auditoria["observacao"])
                            elif auditoria["registros_vazios"]:
                                st.info("Linhas totalmente vazias foram identificadas e contabilizadas.")
                        if resultado.get("auditoria_excel"):
                            excel_aud = resultado["auditoria_excel"]
                            st.caption(
                                f'REFERÊNCIA: {resultado.get("referencia", "Excel manual")}. '
                                f'Registros da referência: '
                                f'{excel_aud["total_recebido"]} recebidos, '
                                f'{excel_aud["registros_pendentes"]} em quarentena.'
                            )
                            if excel_aud["registros_pendentes"]:
                                st.warning(
                                    "Também foram identificadas inconsistências na referência. "
                                    "As linhas sem chave ficam fora da comparação parcial, "
                                    "mas continuam impedindo a homologação integral."
                                )
                            if resultado.get("excecoes_correspondentes"):
                                st.info(
                                    "As exceções presentes na API e na referência correspondem "
                                    "pelas informações disponíveis, sem considerar um código inexistente."
                                )
                            else:
                                st.warning("As exceções entre API e referência não correspondem.")
                        politica = resultado.get("politica_continuidade") or {}
                        if politica:
                            st.markdown("#### POLÍTICA DE CONTINUIDADE DA ATUALIZAÇÃO")
                            status_operacional = politica["status"]
                            if status_operacional == "PROCESSAR_COM_RESSALVAS":
                                st.success(
                                    f'{politica["registros_validos"]:,} registros aptos ao processamento; '
                                    f'{politica["registros_em_quarentena"]:,} em quarentena para correção.'
                                )
                            elif status_operacional == "PROCESSAR":
                                st.success("Dados estruturalmente aptos ao processamento.")
                            else:
                                st.error(
                                    "PROTEGER BASE ANTERIOR: anomalias volumosas ou estruturais "
                                    "exigem investigação."
                                )
                                for motivo in politica["motivos_protecao"]:
                                    st.caption(motivo)
                            st.caption(
                                "Avaliação técnica para futura sincronização. O Monitor "
                                "continua em modo de homologação, sem publicar dados."
                            )
                        if resultado.get("homologacao_bloqueada"):
                            st.caption(resultado["observacao"])
                        if resultado.get("api") and resultado.get("excel"):
                            base_mes = resultado["api"]
                            base_excel = resultado["excel"]
                            indicadores = (
                                ("Linhas brutas", "linhas"), ("OPs distintas", "ops"),
                                ("Códigos distintos", "produtos"),
                                ("Pares OP + código", "op_produto"),
                                ("Solicitações distintas", "solicitacoes_distintas"),
                                ("Quantidade necessária", "necessidade"),
                                ("Quantidade atendida", "atendimento"),
                                ("Pendência", "pendencia"),
                                ("Solicitações divergentes", "solicitacoes_divergentes"),
                            )
                            if resultado.get("comparacao_parcial"):
                                st.warning(
                                    "COMPARAÇÃO COM RESSALVAS: totais abaixo consideram somente "
                                    "registros com chaves válidas. As exceções ficam em quarentena "
                                    "e não precisam impedir o processamento dos demais materiais."
                                )
                            tabela = pd.DataFrame([
                                {"Indicador": label, "API MES": base_mes[key],
                                 "Relatório atual": base_excel[key],
                                 "Diferença (API − atual)": round(float(base_mes[key]) - float(base_excel[key]), 4)}
                                for label, key in indicadores
                            ])
                            _setta_dataframe(tabela, use_container_width=True, hide_index=True)
                            d = resultado["comparativo"]
                            a, b, c, d_col = st.columns(4)
                            a.metric("OP-produtos somente na API", d["somente_api"])
                            b.metric("OP-produtos somente no Excel", d["somente_excel"])
                            c.metric("Quantidades divergentes", d["quantidades_diferentes"])
                            d_col.metric("Solicitações/datas divergentes", d["solicitacoes_por_data_diferentes"])
                            detalhamento = resultado.get("diagnostico_diferencas") or {}
                            if detalhamento:
                                st.markdown("#### ORIGEM DAS DIFERENÇAS DE QUANTIDADE")
                                st.caption(
                                    "Somente na API: contribuição das combinações OP/produto ausentes "
                                    "no Excel. Alteração nas chaves existentes: diferença entre "
                                    "quantidades das combinações presentes nas duas fontes."
                                )
                                _setta_dataframe(
                                    pd.DataFrame(detalhamento["diferencas_por_origem"]),
                                    use_container_width=True, hide_index=True,
                                )
                                st.markdown("#### DATAS DE SOLICITAÇÃO DAS COMBINAÇÕES EXCLUSIVAS DA API")
                                if detalhamento["datas_solicitacoes_apenas_api"]:
                                    _setta_dataframe(
                                        pd.DataFrame(detalhamento["datas_solicitacoes_apenas_api"]),
                                        use_container_width=True, hide_index=True,
                                    )
                                st.caption(
                                    f'Exibindo até 12 datas das '
                                    f'{detalhamento["total_datas_distintas_apenas_api"]} '
                                    "datas distintas encontradas."
                                )
                                st.caption(detalhamento["observacao_datas"])
                            if resultado["iguais_no_criterio_comparado"]:
                                st.success("Os valores e as chaves comparados coincidem. A fonte NÃO foi publicada.")
                            else:
                                st.warning("Existem divergências: manter o Excel até a investigação e homologação.")
                            st.caption(resultado["criterio"])
                            st.caption(resultado["observacao"])



def _render_mes_report_card(source: dict, mes_api: dict, treated_base: dict | None = None) -> None:
    """Cartão da fonte MES com ação real de reprocessamento no próprio cartão."""
    state = ui_components.mes_source_display(source, mes_api)
    esc = ui_components.esc
    status = str(source.get("status") or "AGUARDANDO").upper()
    last_check = esc(source.get("last_update_label") or "Nunca")
    last_change = esc(source.get("content_update_label") or "Nunca")
    rows = esc(source.get("rows_count") or 0)
    version = int(source.get("version") or 0)
    health = state["health"]
    health_chip = (
        "RECEPTOR ONLINE" if health == "ONLINE"
        else "RECEPTOR EM ATENÇÃO" if health == "ATENÇÃO"
        else "RECEPTOR OFFLINE" if health == "OFFLINE"
        else "RECEPTOR SEM VERIFICAÇÃO"
    )
    # O texto principal usa exatamente a mesma estrutura HTML/CSS de todos
    # os cartões de fonte; apenas o botão é um controle Streamlit nativo.
    # Evita o deslocamento causado por duas linhas extras de st.columns.
    with st.container(border=True, key="mes_general_source_card"):
        pending_chip = (
            '<span class="source-chip">PRIMEIRA CARGA VIA API PENDENTE</span>'
            if state["connected"] and not state["published"] else ""
        )
        st.markdown(
            '<div class="source-top"><div>'
            '<div class="source-name">RELATÓRIO GERAL</div>'
            '<div class="source-meta">'
            f'Última conferência: <b>{last_check}</b><br>'
            f'Última mudança: <b>{last_change}</b><br>'
            f'Registros: <b>{rows}</b> · Versão <b>{version}</b>'
            '</div></div>'
            f'<div class="source-badge">{esc(status)}</div></div>'
            '<div class="source-origin">'
            '<span class="source-chip">MES</span>'
            f'<span class="source-chip">{esc(state["mode"])}</span>'
            f'<span class="source-chip">{esc(state["badge"])}</span>'
            f'<span class="source-chip">{esc(health_chip)}</span>'
            f'{pending_chip}'
            '</div>'
            '<div class="source-apps mes-source-footer">'
            '<b>Usado por:</b> Conversor MRP · Gestão de Equipes'
            '</div>',
            unsafe_allow_html=True,
        )
        treated_base = treated_base or {}
        phase, treated_ver = estado_relatorio_tratado(version, treated_base)
        if phase in {"PROCESSANDO", "ERRO_CONVERSOR"} and version > 0:
            # Também acompanha uma atualização agendada por outra sessão.
            st.session_state["_mes_pending_version"] = max(
                int(st.session_state.get("_mes_pending_version") or 0), version
            )
        if phase != "CONCLUIDO":
            st.warning(
                f"Fonte v{version} recebida, mas Tratado v{treated_ver} "
                "ainda não está sincronizado. Aguarde o Conversor MRP."
            )
        else:
            st.caption(f"Fonte e Relatório Geral Tratado sincronizados: v{version}.")

        # Sem PIN de homologação adicional. O token MES continua exclusivo
        # do servidor; aplica-se bloqueio de concorrência e intervalo mínimo
        # para evitar consultas duplicadas em uma instância pública.
        tem_token_mes = bool(os.getenv("SETTA_MES_GENERAL_REPORT_TOKEN", "").strip())
        if not tem_token_mes:
            st.warning(
                "A credencial MES não está disponível neste servidor Streamlit. "
                "A atualização automática via GitHub continua independente."
            )
        if st.button(
            "↻ REPROCESSAR AGORA",
            key="mes_atualizar_agora",
            disabled=not tem_token_mes or phase in {"PROCESSANDO", "ERRO_CONVERSOR"},
            use_container_width=True,
            help=(
                "Aguarde o Conversor MRP concluir: repetir a consulta MES não atualiza a base tratada."
                if phase in {"PROCESSANDO", "ERRO_CONVERSOR"} else
                "Uma consulta MES; o Relatório Geral Tratado atualiza depois automaticamente."
            ),
        ):
            gate = _mes_manual_guard()
            allowed, gate_reason = gate.begin()
            if not allowed:
                msg = (
                    "Já existe uma consulta MES em execução. Aguarde a atualização."
                    if gate_reason == "EM_EXECUCAO" else
                    "Uma consulta MES acabou de ser executada. Aguarde o Conversor "
                    "MRP e a atualização automática da tela; não há necessidade "
                    "de repetir a operação."
                )
                kind = "info"
            else:
                from mes_general_report_sync import sincronizar_relatorio_geral
                try:
                    with st.spinner("Etapa 1/2: consultando MES e publicando fonte..."):
                        retorno = sincronizar_relatorio_geral()
                    if retorno["status"] == "PROTEGER_BASE":
                        msg = (
                            "Fonte anterior preservada: a resposta MES não passou "
                            "na validação de integridade."
                        )
                        kind = "error"
                    else:
                        source_version = int(
                            retorno.get("versao") or source.get("version") or 0
                        )
                        st.session_state["_mes_pending_version"] = source_version
                        msg = (
                            f'Consulta MES concluída ({retorno.get("validos", 0):,} '
                            "registros válidos). Fonte publicada; o Monitor "
                            "acompanhará automaticamente o Relatório Geral Tratado."
                            if retorno.get("publicado") else
                            "Consulta MES concluída sem alteração. "
                            "Conferindo se o Relatório Geral Tratado está atualizado."
                        )
                        kind = "info"
                except Exception as exc:
                    from mes_sync_diagnostics import diagnosticar_erro_mes
                    diagnostico = diagnosticar_erro_mes(exc)
                    kind = "error"
                    msg = (
                        "Falha na atualização: " + diagnostico["orientacao"]
                        + " Código técnico: " + diagnostico["codigo"] + "."
                    )
                    print(
                        "MES_REPROCESSAMENTO_MANUAL"
                        f" codigo={diagnostico['codigo']}"
                        f" classe={type(exc).__name__}",
                        flush=True,
                    )
                finally:
                    # Evitar duas consultas seguidas que só geram versões
                    # intermediárias enquanto o Conversor ainda trabalha.
                    gate.finish(success=True)
            st.session_state["mes_manual_result"] = {
                "kind": kind, "message": msg,
            }
            st.rerun()
        if st.session_state.get("_mes_pending_version"):
            _mes_await_derived()
        outcome = st.session_state.get("mes_manual_result")
        if outcome:
            kind = outcome.get("kind")
            msg = outcome.get("message", "")
            if kind == "success":
                st.success(msg)
            elif kind == "error":
                st.error(msg)
            else:
                st.info(msg)


def _render_feeding(sources):
    section_band("01 · ALIMENTAÇÃO", "Enviar arquivos", "")
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
            "MOVIMENTAÇÃO",
            "FECHAMENTO MENSAL",
        ],
        horizontal=True,
        key="central_feed_preset",
    )

    preset_keys = {
        "RELATÓRIO GERAL": {"relatorio_geral", "for001", "for022"},
        "ESTOQUE": {"analitico", "endereco"},
        "COMPRAS": {"sc", "pc", "pre_nota"},
        "TCTP": {"pmp", "h001"},
        "MOVIMENTAÇÃO": {"movimentacao"},
    }

    if preset == "FECHAMENTO MENSAL":
        selected_sources = store.closing_source_fields(sources)
        st.caption("Envie as quatro fontes aqui. O Fechamento Mensal lê os JSONs pela Central.")
    else:
        default_labels = [
            label for label, item in source_map.items()
            if item.get("source_key") in preset_keys.get(preset, set())
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
            f"última conferência {store.format_dt(source.get('last_received_at') or source.get('last_update_at'))}"
        )
        uploaded = st.file_uploader(
            f"ARQUIVO — {source['name']}",
            type=(["xlsx", "xltx"] if source_key in store.CLOSING_MOVEMENT_KEYS else
                  ["xlsx", "xls", "xlsm", "xltx", "csv", "xml", "txt", "json"]),
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
            skipped_names = []
            failed_sources = []

            done_hashes = st.session_state.setdefault(
                "_central_batch_done_hashes", {}
            )

            for index, source in enumerate(selected_sources, start=1):
                item = uploads[source["source_key"]]
                source_key = source["source_key"]
                fingerprint = hashlib.sha256(item["raw"]).hexdigest()

                persisted_hash = str(source.get("content_sha256") or "").strip()
                normalized_current = bool(source.get("normalized_available"))
                if persisted_hash == fingerprint and normalized_current:
                    # O conteúdo é idêntico, então não cria nova versão nem
                    # reprocessa consumidores. Ainda assim registramos que o
                    # usuário conferiu/enviou novamente a fonte hoje.
                    try:
                        store.touch_source(source_key)
                    except Exception:
                        pass
                    skipped_names.append(source["name"])
                    done_hashes[source_key] = fingerprint
                    status.write(
                        f"{source['name']} sem alteração de conteúdo. Conferência registrada."
                    )
                    progress.progress(index / total)
                    continue

                if persisted_hash == fingerprint and not normalized_current:
                    status.write(
                        f"{source['name']} já possui o bruto atual. Gerando formato técnico..."
                    )
                    try:
                        store.backfill_normalized_source(source_key)
                        updated_names.append(source["name"])
                        done_hashes[source_key] = fingerprint
                    except Exception as exc:
                        failed_sources.append((source["name"], str(exc)))
                    progress.progress(index / total)
                    continue

                if done_hashes.get(source_key) == fingerprint:
                    skipped_names.append(source["name"])
                    status.write(f"{source['name']} já concluída neste lote. Pulando...")
                    progress.progress(index / total)
                    continue

                status.write(f"Atualizando {source['name']}...")
                try:
                    store.save_report(
                        source_key,
                        item["file"].name,
                        item["raw"],
                        rows_count=item["rows_count"],
                        origin=source.get("source_system") or "UPLOAD",
                        max_attempts=3,
                    )
                    updated_names.append(source["name"])
                    done_hashes[source_key] = fingerprint
                except Exception as exc:
                    failed_sources.append((source["name"], str(exc)))

                progress.progress(index / total)

            status.empty()
            progress.empty()

            if failed_sources:
                completed = updated_names + skipped_names
                if completed:
                    st.success(
                        f"{len(completed)} fonte(s) concluída(s) neste lote: "
                        + " • ".join(completed)
                    )
                st.error(
                    "Não foi possível concluir: "
                    + " • ".join(
                        f"{name} — {error}"
                        for name, error in failed_sources
                    )
                    + ". Clique novamente em ATUALIZAR FONTES para retomar apenas as fontes pendentes."
                )
            else:
                st.session_state.pop("_central_batch_done_hashes", None)
                st.success(
                    f"{len(updated_names) + len(skipped_names)} fonte(s) atualizada(s): "
                    + " • ".join(updated_names + skipped_names)
                )
                st.rerun()


def _derived_with_materials():
    derived = store.list_derived_bases()

    # MATERIAIS é uma carga ativa da Gestão de Entregas, não uma linha
    # de setta_derived_bases. Complementa o cartão pela integração oficial.
    try:
        integration_rows = store.central_api_call(
            "integration_status",
            {},
            timeout=30,
        ).get("data") or []
        materials_info = next(
            (
                row for row in integration_rows
                if isinstance(row, dict)
                and str(row.get("id") or "") == "entregas-nfs"
            ),
            {},
        )
    except Exception:
        materials_info = {}

    if materials_info:
        for base in derived:
            if base.get("key") != "materiais_api":
                continue
            activity = materials_info.get("last_activity_at")
            activity_dt = store.parse_dt(activity)
            if activity_dt is None:
                materials_status = "PENDENTE"
            elif activity_dt.date() < datetime.now(store.TZ).date():
                materials_status = "DESATUALIZADO"
            else:
                materials_status = "ATUALIZADO"
            base["status"] = materials_status
            base["mode"] = f"API {materials_status}"
            base["processed_at"] = activity
            base["processed_label"] = store.format_dt(activity)
            base["rows_count"] = int(materials_info.get("rows_count") or 0)
            base["available"] = True
            base["version_label"] = materials_info.get("version_label") or ""
    return derived


def _render_database_maintenance(sources):
    section_band("Manutenção", "Normalização", "")
    pendentes_normalizacao = [
        item for item in sources
        if bool(item.get("available"))
        and not str(item.get("normalized_storage_path") or "").strip()
    ]
    if pendentes_normalizacao:
        if st.button(
            "NORMALIZAR FONTES EXISTENTES",
            use_container_width=True,
            key="normalize_existing_sources",
        ):
            progress = st.progress(0)
            status = st.empty()
            ok = []
            failed = []
            total_pending = len(pendentes_normalizacao)
            for idx, source in enumerate(pendentes_normalizacao, start=1):
                key = str(source.get("source_key") or "")
                status.write(f"Normalizando {source.get('name') or key}...")
                try:
                    store.backfill_normalized_source(key)
                    ok.append(source.get("name") or key)
                except Exception as exc:
                    failed.append((source.get("name") or key, str(exc)))
                progress.progress(idx / total_pending)
            status.empty()
            progress.empty()
            if ok:
                st.success(
                    f"{len(ok)} fonte(s) normalizada(s): " + " • ".join(map(str, ok))
                )
            if failed:
                st.error(
                    "Falha em: "
                    + " • ".join(f"{name} — {error}" for name, error in failed)
                )
            if ok and not failed:
                st.rerun()
    else:
        st.caption("Nenhuma fonte pendente de normalização.")

    if not st.toggle("Editar identidade visual global", key="monitor_global_branding"):
        return
    section_band("Manutenção", "Identidade visual global", "")
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
        type=["png", "jpg", "jpeg", "webp", "ico"],
        key="global_favicon_file",
        help="Até 10 MB. O ícone será otimizado para 256 × 256 px, preservando transparência.",
    )
    v2.caption("Máximo: 10 MB • PNG, JPG, WEBP ou ICO • Otimização automática")

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
                    optimized_icon = prepare_favicon(favicon_file.getvalue())
                    kwargs["favicon_data"] = base64.b64encode(optimized_icon).decode()
                    kwargs["favicon_mime"] = "image/png"

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


def render_database() -> None:
    render_header("BANCO DE DADOS | SETTA", "Alimentação e situação das fontes", "CENTRAL DE DADOS")
    sources = store.list_sources()
    _render_feeding(sources)

    view = st.segmented_control("Consultar dados", ["Fontes", "Bases derivadas", "Manutenção"],
                                default="Fontes", required=True, key="monitor_db_view")
    if view == "Manutenção":
        _render_database_maintenance(sources)
        return
    items = sources if view == "Fontes" else _derived_with_materials()
    term = st.text_input("Buscar fonte ou base", key=f"monitor_data_search_{view}").strip().casefold()
    options = sorted({str(item.get("status") or "AGUARDANDO") for item in items})
    selected_status = st.selectbox("Status da carga", ["Todos", *options], key=f"monitor_data_status_{view}")
    shown = [item for item in items if term in str(item.get("name") or "").casefold()
             and (selected_status == "Todos" or str(item.get("status") or "AGUARDANDO") == selected_status)]
    if not shown:
        st.info("Nenhuma fonte ou base corresponde aos filtros.")
        return
    _setta_dataframe(pd.DataFrame([
        {"Nome": item.get("name") or "—", "Status": item.get("status") or "AGUARDANDO",
         "Última carga": store.format_dt(item.get("last_update_at") or item.get("processed_at"))}
        for item in shown
    ]), width="stretch", hide_index=True)
    key_name = "source_key" if view == "Fontes" else "key"
    by_key = {item[key_name]: item for item in shown if item.get(key_name)}
    chosen = st.selectbox("Ver detalhes", list(by_key), index=None,
                          format_func=lambda key: by_key[key]["name"],
                          placeholder="Selecione uma fonte ou base", key=f"monitor_data_detail_{view}")
    if not chosen:
        return
    selected = by_key[chosen]
    if view == "Bases derivadas":
        st.markdown(derived_card(selected), unsafe_allow_html=True)
        return
    selected = {
        **selected,
        "last_update_label": store.format_dt(selected.get("last_received_at") or selected.get("last_update_at")),
        "content_update_label": store.format_dt(selected.get("last_update_at")),
    }
    if chosen == "relatorio_geral":
        # Usa o estado persistido, sem ler a série de 24 horas de todas as APIs.
        mes_receptor = next((api for api in store.list_apis(include_demo=False)
                             if api.get("health_mode") == "MES_GENERAL_REPORT"), {})
        treated = next((base for base in store.list_derived_bases()
                        if base.get("key") == "relatorio_geral_tratado"), {})
        _render_mes_report_card(selected, mes_receptor, treated)
    else:
        if chosen == "pmp":
            pmp = next((api for api in store.list_apis(include_demo=False)
                        if str(api.get("id") or "") == "11111111-1111-4111-8111-111111111119"), {})
            selected["api_health"] = _api_status(pmp) if pmp else ""
        st.markdown(source_card(selected), unsafe_allow_html=True)


page = render_sidebar()
ui_components.render_setta_shell()

if page == "MONITOR DE APIs":
    render_monitor()
else:
    render_database()

st.markdown(
    '<div class="footer">SETTA · Monitor de APIs e Central de Dados</div>',
    unsafe_allow_html=True,
)
