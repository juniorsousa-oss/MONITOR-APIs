"""Sincronização controlada da API MES -> fonte Relatório Geral SETTA.

O processamento das bases derivadas continua sob responsabilidade do
MRP-CONVERSOR (worker a cada ~5 minutos). O relatório JSON é mantido apenas
em memória; erros individuais seguem para uma aba de auditoria e não travam a
publicação dos registros válidos.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import os

import pandas as pd

import data_store as store
from mes_general_report import TOKEN_ENV, URL
from mes_general_report_validation import (
    _codigo, _dia, _download_limited, _mes_records,
    _quantidade, _registro_realmente_vazio, avaliar_continuidade_mes,
)

FONTE = "relatorio_geral"
CABECALHO = [
    "Projeto", "Código", "Descrição", "Última solicitação",
    "Qtd. necessária", "Qtd. atendida", "Resp. separação",
    "Data de separação", "Resp. conferência", "Data de conferência",
]
CABECALHO_EXCECOES = [
    "Linha de origem", "Projeto informado", "Código informado",
    "Descrição", "Qtd. necessária", "Qtd. atendida", "Pendência",
    "Última solicitação", "Motivo", "Status",
    "ORIGEM DO CÓDIGO", "DESCRIÇÃO REFERÊNCIA CADASTROS",
]


def _texto(value) -> str:
    return "" if value is None else str(value).strip()


def _linha_valida(obj: dict, indice: int) -> list:
    # Os mesmos campos e validações usados na homologação MES.
    return [
        _codigo(obj.get("OP"), 11, "OP", indice),
        _codigo(obj.get("Code"), 8, "Code", indice),
        _texto(obj.get("Description")),
        _dia(obj.get("LastRequest")),
        _quantidade(obj.get("NecessaryQuantity"), "NecessaryQuantity", indice),
        _quantidade(obj.get("AttendedQuantity"), "AttendedQuantity", indice),
        _texto(obj.get("SeparationUser")),
        _dia(obj.get("SeparationDate")),
        _texto(obj.get("ConferenceResponse")),
        _dia(obj.get("ConferenceDate")),
    ]


def _quantidade_auditavel(value):
    try:
        return _quantidade(value, "Quantidade", 0)
    except ValueError:
        return None


def _linha_excecao(obj: dict, indice: int, motivo: str) -> list:
    necessaria = _quantidade_auditavel(obj.get("NecessaryQuantity"))
    atendida = _quantidade_auditavel(obj.get("AttendedQuantity"))
    pendencia = (
        max(0.0, necessaria - atendida)
        if necessaria is not None and atendida is not None else None
    )
    # Esses campos são restritos à base de auditoria do Conversor.
    return [
        indice + 1, _texto(obj.get("OP")), _texto(obj.get("Code")),
        _texto(obj.get("Description")), necessaria, atendida, pendencia,
        _texto(obj.get("LastRequest")), str(motivo)[:260],
        "PENDENTE DE REGULARIZAÇÃO",
        "MES API", "",
    ]


def preparar_fonte(payload, *, linhas_referencia: int | None = None) -> dict:
    registros = _mes_records(payload)
    validas, excecoes = [], []
    vazias = 0
    for indice, obj in enumerate(registros, 1):
        if _registro_realmente_vazio(obj):
            vazias += 1
            continue
        try:
            validas.append(_linha_valida(obj, indice))
        except (ValueError, TypeError, OverflowError) as exc:
            excecoes.append(_linha_excecao(obj, indice, str(exc)))

    auditoria = {
        "total_recebido": len(registros),
        "registros_validos": len(validas),
        "registros_pendentes": len(excecoes),
        "registros_vazios": vazias,
    }
    politica = avaliar_continuidade_mes(
        auditoria, linhas_referencia=linhas_referencia,
    )
    if not politica["pode_processar_validos"]:
        raise ValueError(
            "PROTEGER_BASE: "
            + "; ".join(politica["motivos_protecao"])
        )

    # Assinatura estável do conteúdo de negócio (não depende da hora de
    # criação do arquivo XLSX). Evita versões diárias idênticas.
    canonico = json.dumps(
        {"geral": validas, "excecoes": excecoes},
        ensure_ascii=False, separators=(",", ":"), default=str,
    ).encode("utf-8")
    digest = sha256(canonico).hexdigest()[:20]
    return {
        "validas": validas,
        "excecoes": excecoes,
        "auditoria": auditoria,
        "politica": politica,
        "assinatura": digest,
        "arquivo": f"API_MES_{digest}.xlsx",
    }


def _xlsx(preparado: dict) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(
            preparado["validas"], columns=CABECALHO,
        ).to_excel(writer, sheet_name="Geral", index=False)
        pd.DataFrame(
            preparado["excecoes"], columns=CABECALHO_EXCECOES,
        ).to_excel(writer, sheet_name="API_INCONSISTENCIAS", index=False)
    return buffer.getvalue()


def sincronizar_api_mes(*, forcar: bool = False,
                        session=None, registrar: bool = True) -> dict:
    """Coleta e publica somente após validação integral do JSON.

    A ausência da credencial não toca a fonte. Nunca logar o corpo do MES.
    """
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        raise ValueError("Credencial MES não configurada neste executor.")

    status = store.central_api_call(
        "source_status", {"keys": [FONTE]}, timeout=35,
    ).get("data") or []
    anterior = next(
        (item for item in status if item.get("source_key") == FONTE),
        {},
    )
    total_anterior = int(anterior.get("rows_count") or 0)
    resposta = _download_limited(
        URL, session=session,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    try:
        payload = json.loads(resposta.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise ValueError("API MES retornou resposta sem JSON válido.") from None

    preparado = preparar_fonte(
        payload, linhas_referencia=total_anterior or None,
    )
    nome_anterior = str(anterior.get("last_file_name") or "")
    iguais = nome_anterior == preparado["arquivo"]
    if iguais and not forcar:
        # Sem mudança de negócio, não incrementar versão do MRP.
        if registrar:
            store.touch_source(FONTE)
        return {
            "status": "SEM ALTERAÇÃO", "versao": int(anterior.get("version") or 0),
            "registros": len(preparado["validas"]),
            "quarentena": len(preparado["excecoes"]),
            "publicado": False,
        }

    # A publicação no formato usado pela Central reaproveita sua
    # normalização e dispara o worker existente do Conversor MRP.
    salvo = store.save_report(
        FONTE, preparado["arquivo"], _xlsx(preparado),
        rows_count=len(preparado["validas"]),
        origin="MES_API", max_attempts=2,
    )
    return {
        "status": preparado["politica"]["status"],
        "versao": int(salvo.get("version") or 0),
        "registros": len(preparado["validas"]),
        "quarentena": len(preparado["excecoes"]),
        "publicado": True,
        "atualizado_em": store.now_iso(),
        "pipeline": "MRP-CONVERSOR (worker periódico)",
    }
