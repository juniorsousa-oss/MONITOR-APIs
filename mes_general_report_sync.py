"""Sincronização do Relatório Geral via MES, manual ou agendada.

Pipeline: leitura segura > auditoria individual > proteções > Excel técnico
pré-validado > publicação no mesmo source_key da Central. O Conversor MRP
detecta a nova versão no worker existente e publica tratado + quarentena.

Não imprime token nem dados sensíveis; não salva arquivo local.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
import gzip
import hashlib
import json
import os
from zoneinfo import ZoneInfo

import pandas as pd

import data_store as store
from mes_general_report import URL, TOKEN_ENV
from mes_general_report_validation import (
    _download_limited, _mes_records, _dia, _quantidade,
    auditar_registros_mes, avaliar_continuidade_mes, _em_branco,
)

SOURCE_KEY = "relatorio_geral"
ORIGIN = "MES_GENERAL_REPORT_API"
COLS = [
    "Projeto", "Código", "Descrição", "Última solicitação",
    "Qtd. necessária", "Qtd. atendida", "Resp. separação",
    "Data de separação", "Resp. conferência", "Data de conferência",
    # Layout 16/11: pendencia de CADA registro/lote (nao saldo cumulativo).
    # Caso o JSON nao envie pendencia explicita, calcula-se a diferenca
    # usando os dois campos MES auditados. Preserva Lote como ultima coluna.
    "Qtd. pendências",
    "Lote",
]
EXCEPTION_COLUMNS = [
    "Linha JSON", "Projeto informado", "Código informado", "Descrição",
    "Qtd. necessária informada", "Qtd. atendida informada",
    "Motivo", "Status",
]
TZ = ZoneInfo("America/Sao_Paulo")


def _source_status():
    source = next(
        (x for x in store.list_sources() if x["source_key"] == SOURCE_KEY), {}
    )
    return source


def preparar_carga_mes(payload, *, referencia: int | None = None):
    registros = _mes_records(payload)
    audit, validos = auditar_registros_mes(registros)
    policy = avaliar_continuidade_mes(audit, linhas_referencia=referencia)
    if not policy["pode_processar_validos"]:
        return {
            "status": "PROTEGER_BASE",
            "auditoria": audit,
            "politica": policy,
            "arquivo": None,
            "linhas_fonte": 0,
        }

    ids_validos = {id(x) for x in validos}
    linhas = []
    excecoes = []
    pendencias_da_api = 0
    pendencias_calculadas = 0

    for indice, obj in enumerate(registros, 1):
        def valor(key):
            return str(obj.get(key) or "").strip()

        if id(obj) in ids_validos:
            necessaria = _quantidade(obj["NecessaryQuantity"], "NecessaryQuantity", indice)
            atendida = _quantidade(obj["AttendedQuantity"], "AttendedQuantity", indice)
            calculada = necessaria - atendida
            if calculada < -0.000001:
                raise ValueError("MES retornou atendimento maior que necessidade em registro validado.")
            chaves_pendencia = [
                chave for chave in ("PendingQuantity", "Pending", "RemainingQuantity")
                if chave in obj and not _em_branco(obj.get(chave))
            ]
            if chaves_pendencia:
                pendencia = _quantidade(obj[chaves_pendencia[0]], chaves_pendencia[0], indice)
                if abs(pendencia - calculada) > 0.000001:
                    raise ValueError("MES retornou pendencia divergente em registro validado.")
                pendencias_da_api += 1
            else:
                # Derivacao declarada: o contrato novo garante N - A = P
                # por linha. Nao usar a ultima pendencia de outra linha/lote.
                pendencia = round(max(0.0, calculada), 6)
                pendencias_calculadas += 1
            linhas.append([
                valor("OP"), valor("Code"), valor("Description"),
                _dia(obj.get("LastRequest")),
                necessaria, atendida,
                valor("SeparationUser"), _dia(obj.get("SeparationDate")),
                valor("ConferenceResponse"), _dia(obj.get("ConferenceDate")),
                pendencia,
                # Lote somente de Batch. Preservar zeros à esquerda.
                "" if obj.get("Batch") is None else str(obj["Batch"]).strip(),
            ])
        elif any(v is not None and str(v).strip() for v in obj.values()):
            # NUNCA inserir exceções na aba Geral: o Conversor poderia
            # recuperar um código por descrição e criar demanda não
            # homologada. Toda exceção segue na aba lateral de auditoria,
            # publicada como base derivada de inconsistências.
            excecoes.append({
                "Linha JSON": indice,
                "Projeto informado": valor("OP"),
                "Código informado": valor("Code"),
                "Descrição": valor("Description"),
                "Qtd. necessária informada": obj.get("NecessaryQuantity"),
                "Qtd. atendida informada": obj.get("AttendedQuantity"),
                "Motivo": "REGISTRO INCONSISTENTE NA ORIGEM MES",
                "Status": "PENDENTE DE REGULARIZAÇÃO",
            })

    if not linhas:
        raise ValueError("Nenhum registro publicável após validação.")
    frame = pd.DataFrame(linhas, columns=COLS)
    exceptions = pd.DataFrame(excecoes, columns=EXCEPTION_COLUMNS)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Geral", index=False)
        exceptions.to_excel(writer, sheet_name="Inconsistencias MES", index=False)
    arquivo = buffer.getvalue()

    # Pré-validação de normalização ANTES de atualizar a fonte corrente.
    normalized, normalized_count = store.build_normalized_source(
        SOURCE_KEY, "RelatorioGeral_MES.xlsx", arquivo,
    )
    if not normalized or normalized_count <= 0:
        raise RuntimeError("Pré-validação do Excel técnico falhou.")

    # Contrato de publicação também validado no formato que o FECHAMENTO
    # lê de verdade (SETTA_SOURCE_V1). A presença de Batch na resposta
    # MES não bastava: a planilha/normalização podiam omitir Lote.
    try:
        pack = json.loads(gzip.decompress(normalized).decode("utf-8"))
        geral = next(
            sheet for sheet in pack.get("sheets", [])
            if str(sheet.get("name") or "").strip().casefold() == "geral"
        )
        linhas_geral = geral.get("rows") or []
        cabecalho = linhas_geral[0] if linhas_geral else []
    except (ValueError, TypeError, OSError, StopIteration, IndexError) as exc:
        raise RuntimeError(
            "Pré-validação falhou: Relatório Geral normalizado ilegível. "
            "Nenhuma atualização foi publicada."
        ) from exc
    if (
        "Lote" not in cabecalho or "Qtd. pendências" not in cabecalho
        or len(linhas_geral) != len(frame) + 1 or len(cabecalho) != len(COLS)
    ):
        raise RuntimeError(
            "Pré-validação falhou: o Relatório Geral normalizado está "
            "sem Lote/Pendências ou com quantidade incorreta de linhas. "
            "Fonte anterior preservada."
        )

    # Conferencia no artefato NORMALIZADO, exatamente como o Conversor
    # MRP o consumira. A validacao e feita antes de salvar nova versao.
    idx_n = cabecalho.index("Qtd. necessária")
    idx_a = cabecalho.index("Qtd. atendida")
    idx_p = cabecalho.index("Qtd. pendências")
    for numero, linha in enumerate(linhas_geral[1:], 2):
        # A camada SETTA_SOURCE_V1 suprime células vazias ao final da
        # linha (por exemplo Batch vazio), sem alterar as colunas internas.
        # K deve existir na posição correta; Lote vazio pode estar ausente.
        if len(linha) <= idx_p or len(linha) > len(cabecalho):
            raise RuntimeError("Relatório Geral normalizado sem coluna de pendências por linha; fonte preservada.")
        n, a, p = (
            _quantidade(linha[idx_n], "Qtd. necessária", numero),
            _quantidade(linha[idx_a], "Qtd. atendida", numero),
            _quantidade(linha[idx_p], "Qtd. pendências", numero),
        )
        if a > n + 0.000001 or abs((n - a) - p) > 0.000001:
            raise RuntimeError("Relatório Geral normalizado com pendências divergentes; fonte preservada.")

    return {
        "status": policy["status"],
        "auditoria": audit,
        "politica": policy,
        "arquivo": arquivo,
        "linhas_fonte": len(frame),
        "linhas_excecao": len(excecoes),
        "pendencias_api": pendencias_da_api,
        "pendencias_calculadas": pendencias_calculadas,
        "sha256": hashlib.sha256(arquivo).hexdigest(),
    }


def sincronizar_relatorio_geral(*, session=None, dry_run=False):
    """Executa sob autorização, uma consulta por operação.

    Atenção: a publicação da Central é o commit que altera a origem.
    A validação do payload e do Excel é concluída antes do commit.
    """
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError("Token MES ausente no ambiente executor.")

    source = _source_status()
    referencia = int(source.get("rows_count") or 0) or None
    raw = _download_limited(
        URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
        session=session,
    )
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise ValueError("API MES retornou conteúdo que não é JSON.") from None

    prepared = preparar_carga_mes(payload, referencia=referencia)
    status = prepared["status"]
    audit = prepared["auditoria"]
    result = {
        "status": status,
        "timestamp": datetime.now(TZ).isoformat(),
        "recebidos": audit["total_recebido"],
        "validos": audit["registros_validos"],
        "quarentena": audit["registros_pendentes"],
        "pendencias_api": prepared.get("pendencias_api", 0),
        "pendencias_calculadas": prepared.get("pendencias_calculadas", 0),
        "motivos_protecao": prepared["politica"]["motivos_protecao"],
        "publicado": False,
    }

    if status == "PROTEGER_BASE":
        return result
    if dry_run:
        return result

    # Não registra uma nova versão se o conteúdo binário está idêntico.
    if (
        source.get("content_sha256") == prepared["sha256"]
        and source.get("normalized_available")
    ):
        store.touch_source(SOURCE_KEY)
        result["status"] = (
            "SEM_ALTERACAO_COM_RESSALVAS" if audit["registros_pendentes"]
            else "SEM_ALTERACAO"
        )
        return result

    saved = store.save_report(
        SOURCE_KEY,
        "RelatorioGeral_MES.xlsx",
        prepared["arquivo"],
        rows_count=prepared["linhas_fonte"],
        origin=ORIGIN,
        max_attempts=2,
    )
    result["publicado"] = True
    result["versao"] = saved.get("version")
    result["normalizado"] = bool(saved.get("normalized"))
    return result


def main():
    try:
        res = sincronizar_relatorio_geral()
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res["status"] != "PROTEGER_BASE" else 2
    except Exception as exc:
        # Não exibir URL assinada, stack traces ou dados das requisições.
        print(json.dumps({"status": "ERRO", "tipo": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
