"""Verificação segura da API MES GeneralReport da SETTA.

Somente testa a disponibilidade do endpoint. Não publica o relatório,
não altera a fonte "relatorio_geral" e nunca registra credenciais/dados.
"""
from __future__ import annotations

from datetime import datetime
import os
import re
import time
from zoneinfo import ZoneInfo

import requests

URL = "https://mes.settadigital.com/rest/v1/GeneralReport?Company=01&Branch=0201"
TOKEN_ENV = "SETTA_MES_GENERAL_REPORT_TOKEN"
AUTH_SCHEME_ENV = "SETTA_MES_GENERAL_REPORT_AUTH_SCHEME"


def check_general_report(timeout_seconds: int = 90, warning_latency_ms: int = 45000,
                         expected_status: int = 200, session=None) -> dict:
    """Teste leve por GET autenticado, fechando o stream após o primeiro bloco.

    A resposta pode ser grande (relatório mensal); não converter em JSON nem
    registrar conteúdo no Monitor. Não encaminhar o Bearer para redirects.
    A autenticação Bearer foi confirmada no Postman do fornecedor. O limite
    de leitura leva em conta os ~30s registrados na execução bem-sucedida.
    """
    checked = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        return {
            "checked_at": checked, "status": "OFFLINE", "success": False,
            "http_status": None, "latency_ms": None,
            "error_message": "Credencial MES não configurada no ambiente seguro.",
            "incident_kind": "CONFIGURAÇÃO",
        }

    # Confirmado por screenshot do Postman do fornecedor: Authorization Bearer.
    # A variável legada AUTH_SCHEME_ENV é ignorada para impedir uso acidental
    # de Basic após a validação do contrato. Não expor o valor do token.

    requester = session or requests
    start = time.perf_counter()
    response = None
    try:
        response = requester.get(
            URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "*/*",
                "Cache-Control": "no-cache",
            },
            # Postman respondeu em ~30s. Reservar margem para carga de dados.
            timeout=(10, max(60, int(timeout_seconds))),
            stream=True,
            allow_redirects=False,
        )
        latency = round((time.perf_counter() - start) * 1000, 2)
        http = int(response.status_code)

        # Não seguir 3xx: evita remeter o token a destinos imprevistos.
        if http != expected_status:
            # Metadata somente: nunca copiar corpo da resposta de erro para
            # banco/log, pois pode conter dados da empresa e stack traces.
            content_type = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not re.fullmatch(r"[a-z0-9.+-]{1,40}/[a-z0-9.+-]{1,40}", content_type):
                content_type = "não informado"
            request_id = str(response.headers.get("X-Request-ID") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", request_id):
                request_id = ""
            detalhe = f" Tipo da resposta: {content_type}."
            if request_id:
                detalhe += f" Identificador para o suporte: {request_id}."
            mensagem = (
                "Redirecionamento inesperado da API MES."
                if 300 <= http < 400
                else f"API MES HTTP {http}. Confirmar requisição e logs do MES."
            )
            return {
                "checked_at": checked, "status": "OFFLINE", "success": False,
                "http_status": http, "latency_ms": latency,
                "error_message": mensagem + detalhe,
                "incident_kind": "API MES",
            }

        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "text/html" in content_type:
            return {
                "checked_at": checked, "status": "OFFLINE", "success": False,
                "http_status": http, "latency_ms": latency,
                "error_message": "API MES retornou HTML em vez do relatório.",
                "incident_kind": "FORMATO INVÁLIDO",
            }

        # Não descarregar o arquivo todo apenas para verificar disponibilidade.
        primeiro_bloco = next(response.iter_content(chunk_size=1024), b"")
        if not primeiro_bloco:
            return {
                "checked_at": checked, "status": "ATENÇÃO", "success": False,
                "http_status": http, "latency_ms": latency,
                "error_message": "API MES respondeu sem conteúdo.",
                "incident_kind": "RESPOSTA VAZIA",
            }

        latency = round((time.perf_counter() - start) * 1000, 2)
        slow = latency >= warning_latency_ms
        return {
            "checked_at": checked,
            "status": "ATENÇÃO" if slow else "ONLINE",
            "success": True,
            "http_status": http,
            "latency_ms": latency,
            "error_message": "Latência elevada na API MES." if slow else "",
            "incident_kind": "LATÊNCIA" if slow else "",
        }
    except requests.RequestException as exc:
        # Tipo do erro, sem incluir URL completa, header, corpo ou Bearer.
        return {
            "checked_at": checked, "status": "OFFLINE", "success": False,
            "http_status": None,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error_message": f"Conexão com API MES falhou ({type(exc).__name__}).",
            "incident_kind": "INDISPONIBILIDADE",
        }
    finally:
        if response is not None:
            response.close()
