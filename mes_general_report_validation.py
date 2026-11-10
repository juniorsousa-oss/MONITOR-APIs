"""Homologação somente leitura da API MES contra o Relatório Geral da Central.

Executa uma coleta integral SOB DEMANDA, validada por segredo de acesso na UI.
Nenhum registro/JSON bruto é salvo, exibido ou substitui a fonte de produção.
Os indicadores de confronto são agregados (sem OPs, nomes, materiais ou lotes).
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import gzip
import json
import math
import re
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import pandas as pd
import requests

import data_store as store
from mes_general_report import URL, TOKEN_ENV

MES_FIELDS = {
    "OP": "Projeto", "Code": "Código",
    "Description": "Descrição", "LastRequest": "Última solicitação",
    "NecessaryQuantity": "Qtd. necessária",
    "AttendedQuantity": "Qtd. atendida",
    "SeparationUser": "Resp. separação",
    "SeparationDate": "Data de separação",
    "ConferenceResponse": "Resp. conferência",
    "ConferenceDate": "Data de conferência",
}
REQUIRED_MES = ("OP", "Code", "NecessaryQuantity", "AttendedQuantity")
REQUIRED_GENERAL = ("Projeto", "Código", "Última solicitação",
                    "Qtd. necessária", "Qtd. atendida")
FUSO = ZoneInfo("America/Sao_Paulo")
MAX_MES_BYTES = 50 * 1024 * 1024
MAX_CENTRAL_BYTES = 55 * 1024 * 1024
MAX_CENTRAL_UNPACKED = 180 * 1024 * 1024


def _codigo(valor, tamanho, campo, indice):
    if valor is None:
        raise ValueError(f"Linha {indice}: campo {campo} vazio.")
    txt = str(valor).strip()
    if re.fullmatch(r"\d+\.0", txt):
        txt = txt[:-2]
    if not txt.isdigit() or len(txt) > tamanho:
        raise ValueError(f"Linha {indice}: {campo} inválido.")
    return txt.zfill(tamanho)


def _quantidade(valor, campo, indice, *, excel=False):
    if excel and (valor is None or str(valor).strip().lower() in {"", "nan", "none"}):
        return 0.0
    if valor is None or isinstance(valor, bool):
        raise ValueError(f"Linha {indice}: {campo} ausente.")
    raw = str(valor).strip()
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        resultado = float(Decimal(raw))
    except (InvalidOperation, OverflowError, ValueError):
        raise ValueError(f"Linha {indice}: {campo} não numérico.") from None
    if not math.isfinite(resultado) or resultado < 0:
        raise ValueError(f"Linha {indice}: {campo} inválido ou negativo.")
    return resultado


def _dia(valor):
    if valor is None or str(valor).strip() in ("", "nan", "NaT", "None", "NI"):
        return ""
    if isinstance(valor, (datetime, date, pd.Timestamp)):
        ts = pd.Timestamp(valor)
        return ts.tz_convert(FUSO).strftime("%Y-%m-%d") if ts.tzinfo else ts.strftime("%Y-%m-%d")
    txt = str(valor).strip()
    if re.match(r"^\d{4}-\d\d-\d\d[T ]", txt):
        # MES declara UTC; Excel pode exportar hora local sem fuso.
        if re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", txt, re.I):
            ts = pd.to_datetime(txt, errors="coerce", utc=True)
            if pd.isna(ts):
                raise ValueError("Data inválida.")
            return ts.tz_convert(FUSO).strftime("%Y-%m-%d")
        try:
            return datetime.strptime(txt[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError("Data inválida.") from None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt[:10], formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("Data de solicitação não reconhecida.")


def _mes_records(payload):
    if isinstance(payload, dict):
        wrappers = [k for k in ("data", "items", "results") if isinstance(payload.get(k), list)]
        if len(wrappers) != 1:
            raise ValueError("JSON MES sem uma lista única de registros.")
        payload = payload[wrappers[0]]
    if not isinstance(payload, list) or not payload or any(not isinstance(x, dict) for x in payload):
        raise ValueError("JSON MES vazio ou estrutura incompatível.")
    return payload



def _em_branco(valor):
    return valor is None or (
        isinstance(valor, str) and valor.strip().lower() in {"", "null", "none", "nan"}
    )


def _registro_realmente_vazio(registro):
    """Descarta apenas objetos integralmente vazios, nunca demandas sem código."""
    return all(_em_branco(v) for v in registro.values())


def auditar_registros_mes(payload):
    """Analisa todo o JSON sem expor valores nem interromper na primeira falha.

    Saída pública: somente contagens, presença de informações e posições no
    array. Nenhuma OP, código, usuário, descrição, lote ou conteúdo bruto.
    """
    registros = _mes_records(payload)
    motivos_contagem = {}
    exemplos = []
    registros_validos = []
    vazios = 0
    com_movimento_sem_codigo = 0
    for indice, obj in enumerate(registros, 1):
        if _registro_realmente_vazio(obj):
            vazios += 1
            continue
        motivos = set()
        codigo_vazio = _em_branco(obj.get("Code"))
        op_vazia = _em_branco(obj.get("OP"))
        if codigo_vazio:
            motivos.add("CODIGO_AUSENTE")
        if op_vazia:
            motivos.add("OP_AUSENTE")
        quantidades = []
        for chave in ("NecessaryQuantity", "AttendedQuantity"):
            if _em_branco(obj.get(chave)):
                motivos.add("QUANTIDADE_AUSENTE")
                quantidades.append(None)
                continue
            try:
                quantidades.append(_quantidade(obj[chave], chave, indice))
            except ValueError:
                motivos.add("QUANTIDADE_INVALIDA")
                quantidades.append(None)
        movimento = any(q is not None and q > 0 for q in quantidades)
        if codigo_vazio and movimento:
            com_movimento_sem_codigo += 1
        if not codigo_vazio:
            try:
                _codigo(obj["Code"], 8, "Code", indice)
            except ValueError:
                motivos.add("CODIGO_INVALIDO")
        if not op_vazia:
            try:
                _codigo(obj["OP"], 11, "OP", indice)
            except ValueError:
                motivos.add("OP_INVALIDA")
        try:
            _dia(obj.get("LastRequest"))
        except ValueError:
            motivos.add("DATA_INVALIDA")
        if motivos:
            for motivo in sorted(motivos):
                motivos_contagem[motivo] = motivos_contagem.get(motivo, 0) + 1
            if len(exemplos) < 12:
                exemplos.append({
                    "Linha JSON": indice,
                    "Problemas": ", ".join(sorted(motivos)),
                    "OP informada": not op_vazia,
                    "Descrição informada": not _em_branco(obj.get("Description")),
                    "Lote informado": not _em_branco(obj.get("Batch")),
                    "Quantidade positiva": movimento,
                })
        else:
            registros_validos.append(obj)
    pendentes = len(registros) - vazios - len(registros_validos)
    auditoria = {
        "total_recebido": len(registros),
        "registros_validos": len(registros_validos),
        "registros_vazios": vazios,
        "registros_pendentes": pendentes,
        "sem_codigo_com_movimento": com_movimento_sem_codigo,
        "motivos": motivos_contagem,
        "exemplos": exemplos,
        "aprovado_para_comparacao": pendentes == 0 and len(registros_validos) > 0,
        "observacao": (
            "Linhas verdadeiramente vazias são ignoradas, com contagem. "
            "Registros sem código, mesmo sem quantidade, bloqueiam a homologação. "
            "Nenhuma necessidade é descartada automaticamente."
        ),
    }
    return auditoria, registros_validos


def _table_mes(payload):
    registros = _mes_records(payload)
    linhas = []
    for indice, obj in enumerate(registros, 1):
        ausentes = [k for k in REQUIRED_MES if k not in obj or obj[k] is None]
        if ausentes:
            raise ValueError(f"Linha {indice}: campos obrigatórios MES ausentes: {', '.join(ausentes)}.")
        linhas.append({
            "OP": _codigo(obj["OP"], 11, "OP", indice),
            "Código": _codigo(obj["Code"], 8, "Code", indice),
            "Data": _dia(obj.get("LastRequest")),
            "Necessária": _quantidade(obj["NecessaryQuantity"], "NecessaryQuantity", indice),
            "Atendida": _quantidade(obj["AttendedQuantity"], "AttendedQuantity", indice),
        })
    return pd.DataFrame(linhas), len(registros)


def _table_geral(pack):
    if not isinstance(pack, dict) or pack.get("format") != "SETTA_SOURCE_V1":
        raise ValueError("Fonte normalizada da Central inválida.")
    folhas = [sheet for sheet in (pack.get("sheets") or []) if isinstance(sheet, dict)]
    folha = next((f for f in folhas if str(f.get("name") or "").casefold() == "geral"), None)
    if folha is None:
        raise ValueError("Fonte atual sem aba Geral.")
    rows = folha.get("rows") or []
    if len(rows) < 2:
        raise ValueError("Relatório Geral armazenado não contém registros.")
    cab = [str(x or "").strip() for x in rows[0]]
    colunas = {name: cab.index(name) for name in REQUIRED_GENERAL if name in cab}
    missing = [name for name in REQUIRED_GENERAL if name not in colunas]
    if missing:
        raise ValueError("Fonte atual sem colunas: " + ", ".join(missing))
    linhas = []
    for indice, row in enumerate(rows[1:], 2):
        if not isinstance(row, list):
            raise ValueError("Relatório Geral possui linha não tabular.")
        def get(key):
            i = colunas[key]
            return row[i] if i < len(row) else None
        # O arquivo original pode conter uma última linha inteiramente vazia.
        if all(get(key) in (None, "") for key in REQUIRED_GENERAL):
            continue
        linhas.append({
            "OP": _codigo(get("Projeto"), 11, "Projeto", indice),
            "Código": _codigo(get("Código"), 8, "Código", indice),
            "Data": _dia(get("Última solicitação")),
            "Necessária": _quantidade(get("Qtd. necessária"), "Qtd. necessária", indice, excel=True),
            "Atendida": _quantidade(get("Qtd. atendida"), "Qtd. atendida", indice, excel=True),
        })
    if not linhas:
        raise ValueError("Fonte de comparação vazia.")
    return pd.DataFrame(linhas), len(linhas)


def _resumir(df):
    # Uma necessidade por OP/material/data, múltiplos lotes podem repetir
    # a mesma quantidade necessária; atendimento é somado por linha/lote.
    agrupamento = df.groupby(["OP", "Código", "Data"], dropna=False, sort=False)
    inconsistentes = int((agrupamento["Necessária"].nunique(dropna=False) > 1).sum())
    nec = agrupamento["Necessária"].first().reset_index()
    demandas = nec.groupby(["OP", "Código"], sort=False)["Necessária"].sum()
    atend = df.groupby(["OP", "Código"], sort=False)["Atendida"].sum()
    consolidado = pd.concat([demandas, atend], axis=1).fillna(0)
    consolidado["Pendência"] = (consolidado["Necessária"] - consolidado["Atendida"]).clip(lower=0)
    return {
        "linhas": int(len(df)),
        "ops": int(df["OP"].nunique()),
        "produtos": int(df["Código"].nunique()),
        "op_produto": int(len(consolidado)),
        "solicitacoes_distintas": int(len(nec)),
        "necessidade": round(float(consolidado["Necessária"].sum()), 4),
        "atendimento": round(float(consolidado["Atendida"].sum()), 4),
        "pendencia": round(float(consolidado["Pendência"].sum()), 4),
        "solicitacoes_divergentes": inconsistentes,
    }, consolidado


def comparar_documentos(api_payload, current_pack):
    api, n_api = _table_mes(api_payload)
    atual, n_atual = _table_geral(current_pack)
    api_stats, a = _resumir(api)
    current_stats, b = _resumir(atual)
    unidos = a.join(b, how="outer", lsuffix="_api", rsuffix="_atual")
    novos = int((~unidos["Necessária_api"].isna() & unidos["Necessária_atual"].isna()).sum())
    ausentes = int((unidos["Necessária_api"].isna() & ~unidos["Necessária_atual"].isna()).sum())
    iguais = unidos.dropna()
    divergencias = int((
        (iguais["Necessária_api"] - iguais["Necessária_atual"]).abs().gt(1e-6)
        | (iguais["Atendida_api"] - iguais["Atendida_atual"]).abs().gt(1e-6)
        | (iguais["Pendência_api"] - iguais["Pendência_atual"]).abs().gt(1e-6)
    ).sum())
    # Totais por OP-produto podem coincidir mesmo se as solicitações
    # tiverem datas distintas (mudando a semana de necessidade do MRP).
    por_data_api = api.groupby(["OP", "Código", "Data"], dropna=False)["Necessária"].first()
    por_data_atual = atual.groupby(["OP", "Código", "Data"], dropna=False)["Necessária"].first()
    comparacao_datas = pd.concat(
        [por_data_api.rename("mes"), por_data_atual.rename("excel")], axis=1
    )
    alteracoes_datas = int((
        comparacao_datas["mes"].isna()
        | comparacao_datas["excel"].isna()
        | (comparacao_datas["mes"] - comparacao_datas["excel"]).abs().gt(1e-6)
    ).sum())
    estrutura_ok = (
        not novos and not ausentes and not divergencias and not alteracoes_datas
        and api_stats["solicitacoes_divergentes"] == 0
        and current_stats["solicitacoes_divergentes"] == 0
    )
    return {
        "api": api_stats, "excel": current_stats,
        "comparativo": {
            "somente_api": novos,
            "somente_excel": ausentes,
            "quantidades_diferentes": divergencias,
            "solicitacoes_por_data_diferentes": alteracoes_datas,
            "chaves_coincidentes": int(len(iguais)),
        },
        # Indicador técnico, não autorização para substituir produção.
        "iguais_no_criterio_comparado": bool(estrutura_ok),
        "criterio": "OP + Código, necessidade por data de solicitação e atendimentos por lote",
        "observacao": (
            "Nenhum dado foi publicado. Coincidência dos totais não substitui "
            "a homologação da janela temporal e das múltiplas solicitações no mesmo dia."
        ),
    }


def _download_limited(url, *, headers=None, session=None, limit=MAX_MES_BYTES):
    requester = session or requests
    resp = None
    try:
        resp = requester.get(url, headers=headers, timeout=(10, 120),
                             stream=True, allow_redirects=False)
        if int(resp.status_code) != 200:
            raise ValueError(f"Consulta retornou HTTP {int(resp.status_code)}.")
        tamanho = resp.headers.get("Content-Length")
        if tamanho is not None and tamanho.isdecimal() and int(tamanho) > limit:
            raise ValueError("Relatório excede o tamanho máximo autorizado.")
        total = 0
        blocos = []
        for b in resp.iter_content(chunk_size=65536):
            if not b:
                continue
            total += len(b)
            if total > limit:
                raise ValueError("Relatório excede o tamanho máximo autorizado.")
            blocos.append(b)
        if not total:
            raise ValueError("Resposta sem dados.")
        return b"".join(blocos)
    except requests.RequestException as exc:
        # Não propagar URL assinada, cabeçalhos, valores retornados ou token.
        raise ValueError(f"Erro de comunicação ({type(exc).__name__}).") from None
    finally:
        if resp is not None:
            resp.close()


def coletar_e_comparar(*, mes_session=None, central_session=None,
                      excel_manual_bytes=None):
    """Operação manual protegida por PIN, sem publicação ou alteração da fonte.

    Opcionalmente compara o Excel recém-exportado, sem salvá-lo em disco;
    o padrão continua utilizando a Central de Dados.
    """
    token = str(__import__("os").getenv(TOKEN_ENV, "")).strip()
    if not token:
        raise ValueError("Token da API MES não está disponível no servidor.")
    raw_mes = _download_limited(
        URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "*/*", "Cache-Control": "no-cache"},
        session=mes_session,
    )
    try:
        api_payload = json.loads(raw_mes.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise ValueError("MES respondeu HTTP 200, mas o conteúdo não é JSON válido.") from None
    # Se o operador forneceu o Excel mais recente, permite comparar apenas
    # as linhas válidas, com a exceção bloqueando a homologação integral.
    # Sem upload, preservamos a proteção original antes de consultar a Central.
    from mes_general_report_reconciliation import (
        pacote_do_excel_manual, comparar_com_quarentena,
    )
    auditoria, _ = auditar_registros_mes(api_payload)
    if excel_manual_bytes is not None:
        pacote = pacote_do_excel_manual(excel_manual_bytes)
        return comparar_com_quarentena(
            api_payload, pacote, referencia="Excel manual enviado nesta sessão",
        )
    if not auditoria["aprovado_para_comparacao"]:
        return {
            "homologacao_bloqueada": True,
            "auditoria": auditoria,
            "observacao": "JSON recebido, mas existem registros para conferência no MES. "
                          "Envie o Excel manual atualizado para comparar as linhas válidas "
                          "sem autorizar a substituição da fonte.",
        }
    meta = store.central_api_call(
        "source_normalized_download", {"source_key": "relatorio_geral"}, timeout=35
    ).get("data") or {}
    signed_url = str(meta.get("signed_url") or "").strip()
    parsed = urlparse(signed_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "cuixazpxkvniqldmmnth.supabase.co"
        or not parsed.path.startswith("/storage/v1/")
    ):
        raise ValueError("Central de Dados não forneceu uma URL de Storage autorizada.")
    raw_central = _download_limited(
        signed_url, session=central_session, limit=MAX_CENTRAL_BYTES
    )
    try:
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(raw_central)) as f:
            unpacked = f.read(MAX_CENTRAL_UNPACKED + 1)
        if len(unpacked) > MAX_CENTRAL_UNPACKED:
            raise ValueError("Fonte da Central excede o limite de leitura segura.")
        pack = json.loads(unpacked.decode("utf-8"))
    except (ValueError, OSError, UnicodeError):
        raise ValueError("Não foi possível interpretar a fonte normalizada da Central.") from None
    return comparar_com_quarentena(
        api_payload, pack, referencia="Central de Dados (última versão publicada)",
    )
