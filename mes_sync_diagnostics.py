"""Diagnósticos seguros para o reprocessamento MES no Streamlit.

Nunca expor corpo HTTP, URL, tokens ou stacktrace ao usuário.
"""
from __future__ import annotations

import re


def diagnosticar_erro_mes(exc: Exception) -> dict[str, str]:
    tipo = type(exc).__name__
    texto = str(exc).casefold()
    if "token mes ausente" in texto or "token da api mes não está" in texto:
        return {"codigo": "MES_CREDENCIAL_STREAMLIT",
                "orientacao": "A credencial MES não está configurada neste aplicativo. A execução agendada pode utilizar outro ambiente."}
    if "consulta retornou http" in texto:
        status = re.search(r"\bhttp\s+(\d{3})\b", texto)
        code = status.group(1) if status else "ERRO"
        return {"codigo": f"MES_HTTP_{code}",
                "orientacao": "A API MES recusou a requisição. Consulte o estado do serviço."}
    if "erro de comunicação" in texto or tipo in {"ConnectTimeout", "ReadTimeout", "Timeout", "ConnectionError"}:
        return {"codigo": f"MES_COMUNICACAO_{tipo.upper()}",
                "orientacao": "Falha de comunicação com a MES. A versão anterior foi preservada."}
    if "json" in texto:
        return {"codigo": "MES_JSON_INVALIDO",
                "orientacao": "A MES respondeu em formato inesperado. Confira o sistema de origem."}
    if "tamanho máximo" in texto or "excede" in texto:
        return {"codigo": "MES_TAMANHO_LIMITE",
                "orientacao": "O tamanho da resposta excedeu o limite de segurança."}
    if "pré-validação" in texto or "normalizado" in texto or "pendências divergentes" in texto:
        return {"codigo": "MES_VALIDACAO_DADOS",
                "orientacao": "A fonte não passou na conferência de integridade. A versão anterior foi preservada."}
    if any(s in texto for s in ("central", "storage", "upload", "signed url")):
        return {"codigo": "MES_CENTRAL_PUBLICACAO",
                "orientacao": "O envio à Central de Dados falhou. Confira disponibilidade do armazenamento."}
    return {"codigo": f"MES_INESPERADO_{tipo.upper()}",
            "orientacao": "Falha não classificada. Consulte os logs do servidor usando este código."}
