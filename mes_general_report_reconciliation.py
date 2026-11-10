"""Conciliação MES + Relatório Geral com quarentena espelhada.

Não altera Central de Dados, snapshots ou MRP. Registros sem Code permanecem
isolados e impedem a homologação integral, mesmo que o restante coincida.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
import re
from typing import Any

import pandas as pd

from mes_general_report_validation import (
    _codigo, _dia, _em_branco, _quantidade,
    auditar_registros_mes, comparar_documentos,
)

TITULOS = (
    "Projeto", "Código", "Descrição", "Última solicitação",
    "Qtd. necessária", "Qtd. atendida",
)
MAX_UPLOAD_EXCEL = 45 * 1024 * 1024


def _registros_excel(pack: dict) -> list[dict]:
    if not isinstance(pack, dict) or pack.get("format") != "SETTA_SOURCE_V1":
        raise ValueError("Fonte de referência incompatível com SETTA_SOURCE_V1.")
    folhas = [x for x in pack.get("sheets", []) if isinstance(x, dict)]
    folha = next(
        (x for x in folhas if str(x.get("name", "")).strip().casefold() == "geral"),
        None,
    )
    if not folha:
        raise ValueError("Fonte de referência não contém a aba Geral.")
    linhas = folha.get("rows") or []
    if len(linhas) < 2:
        raise ValueError("Fonte de referência sem dados.")
    cab = [str(v or "").strip() for v in linhas[0]]
    faltantes = [col for col in TITULOS if col not in cab]
    if faltantes:
        raise ValueError("Fonte de referência sem colunas: " + ", ".join(faltantes))
    indices = {nome: cab.index(nome) for nome in TITULOS}
    registros = []
    for pos, linha in enumerate(linhas[1:], 2):
        if not isinstance(linha, list):
            raise ValueError(f"Linha {pos}: formato tabular incorreto.")
        def valor(nome):
            i = indices[nome]
            dado = linha[i] if i < len(linha) else None
            return None if pd.isna(dado) else dado
        registro = {
            "OP": valor("Projeto"),
            "Code": valor("Código"),
            "Description": valor("Descrição"),
            "LastRequest": valor("Última solicitação"),
            "NecessaryQuantity": valor("Qtd. necessária"),
            "AttendedQuantity": valor("Qtd. atendida"),
        }
        # O relatório manual representa quantidades vazias como zero.
        for nome in ("NecessaryQuantity", "AttendedQuantity"):
            if _em_branco(registro[nome]):
                registro[nome] = 0
        registros.append(registro)
    return registros


def pacote_do_excel_manual(dados: bytes):
    """Importa somente as colunas de interesse; nunca persiste o arquivo."""
    if not dados or len(dados) > MAX_UPLOAD_EXCEL:
        raise ValueError("Arquivo de homologação vazio ou acima de 45 MiB.")
    if dados[:2] != b"PK":
        raise ValueError("Arquivo inválido: selecione um Excel .xlsx.")
    try:
        df = pd.read_excel(
            BytesIO(dados), sheet_name="Geral", engine="openpyxl",
            dtype=object, usecols=lambda nome: str(nome).strip() in TITULOS,
        )
    except (ValueError, OSError, ImportError, KeyError):
        raise ValueError("Não foi possível ler a aba Geral do arquivo Excel.") from None
    cols = [str(x).strip() for x in df.columns]
    ausentes = [k for k in TITULOS if k not in cols]
    if ausentes:
        raise ValueError("O Excel não possui as colunas: " + ", ".join(ausentes))
    df.columns = cols
    registros = []
    for i, row in enumerate(df.loc[:, list(TITULOS)].itertuples(index=False, name=None), start=2):
        celulas = [None if pd.isna(x) else x for x in row]
        registros.append(celulas)
    return {
        "format": "SETTA_SOURCE_V1",
        "source_key": "relatorio_geral",
        "sheets": [{"name": "Geral", "rows": [list(TITULOS), *registros]}],
    }


def _registros_excecao(registros, validos):
    # Subtrair pela identidade permite registros duplicados idênticos.
    contagem = Counter(id(x) for x in validos)
    excecoes = []
    for x in registros:
        oid = id(x)
        if contagem[oid]:
            contagem[oid] -= 1
        elif any(not _em_branco(v) for v in x.values()):
            excecoes.append(x)
    return excecoes


def _assinatura_excecao(registro):
    """Assinatura somente em memória, nunca enviada ao frontend."""
    def limpo(x):
        return re.sub(r"\s+", " ", str(x or "").strip().casefold())
    def quantidade(x):
        try:
            return round(_quantidade(x, "q", 1, excel=True), 6)
        except ValueError:
            return limpo(x)
    try:
        dia = _dia(registro.get("LastRequest"))
    except ValueError:
        dia = limpo(registro.get("LastRequest"))
    return (
        limpo(registro.get("OP")),
        limpo(registro.get("Code")),
        limpo(registro.get("Description")),
        dia,
        quantidade(registro.get("NecessaryQuantity")),
        quantidade(registro.get("AttendedQuantity")),
    )


def _pacote_validos(validos):
    linhas = [list(TITULOS)]
    for x in validos:
        linhas.append([
            x.get("OP"), x.get("Code"), x.get("Description"),
            x.get("LastRequest"), x.get("NecessaryQuantity"),
            x.get("AttendedQuantity"),
        ])
    return {
        "format": "SETTA_SOURCE_V1",
        "source_key": "relatorio_geral",
        "sheets": [{"name": "Geral", "rows": linhas}],
    }


def comparar_com_quarentena(api_payload: Any, excel_pack: dict, *, referencia: str) -> dict:
    api_auditoria, api_validos = auditar_registros_mes(api_payload)
    excel_registros = _registros_excel(excel_pack)
    excel_auditoria, excel_validos = auditar_registros_mes(excel_registros)

    # A posição do Excel inclui cabeçalho na linha 1.
    for item in excel_auditoria["exemplos"]:
        item["Linha Excel"] = item.pop("Linha JSON") + 1

    api_excecoes = _registros_excecao(
        api_payload if isinstance(api_payload, list) else
        next(api_payload[k] for k in ("data","items","results") if isinstance(api_payload.get(k), list)),
        api_validos,
    )
    excel_excecoes = _registros_excecao(excel_registros, excel_validos)
    correspondentes = (
        Counter(_assinatura_excecao(x) for x in api_excecoes)
        == Counter(_assinatura_excecao(x) for x in excel_excecoes)
    )

    # O relatório inteiro pode ter um registro sem código; não perder a análise
    # dos demais, mas também jamais marcá-lo como homologado integralmente.
    if not api_validos or not excel_validos:
        return {
            "homologacao_bloqueada": True, "comparacao_parcial": False,
            "auditoria": api_auditoria, "auditoria_excel": excel_auditoria,
            "excecoes_correspondentes": correspondentes,
            "referencia": referencia,
            "observacao": "Sem registros válidos suficientes para comparar.",
        }

    resultado = comparar_documentos(api_validos, _pacote_validos(excel_validos))
    incompleto = bool(
        api_auditoria["registros_pendentes"]
        or excel_auditoria["registros_pendentes"]
    )
    coincidem_restantes = bool(resultado["iguais_no_criterio_comparado"])
    resultado.update({
        "auditoria": api_auditoria,
        "auditoria_excel": excel_auditoria,
        "referencia": referencia,
        "excecoes_correspondentes": correspondentes,
        "comparacao_parcial": incompleto,
        "coincidem_registros_validos": coincidem_restantes,
        "homologacao_bloqueada": incompleto,
        "iguais_no_criterio_comparado": coincidem_restantes and not incompleto,
        "observacao": (
            "A análise de registros válidos é apenas diagnóstica. "
            "Documentos sem código permanecem em quarentena e impedem "
            "homologação integral. Não houve publicação de dados."
            if incompleto else
            "Comparação concluída; não foram encontradas exceções estruturais. "
            "A janela temporal ainda exige validação operacional. "
            "Não houve publicação de dados."
        ),
    })
    return resultado
