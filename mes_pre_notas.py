"""Contrato de alimentação do Excel de Pré-notas MES, sem operações externas."""
from __future__ import annotations

from datetime import date, datetime
import re
import unicodedata


def _token(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(c for c in value if c.isascii() and c.isalnum())


def _has_date(value):
    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    value = value.strip()
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        try:
            day = re.match(r"^\d{1,2}/\d{1,2}/\d{4}(?=$|\s)", value)
            return bool(day and datetime.strptime(day.group(), "%d/%m/%Y"))
        except ValueError:
            return False


def validate_sheets(sheets):
    """Valida a aba e todas as linhas de uma exportação oficial não vazia."""
    populated = [[row for row in sheet.get("rows", []) if any(
        value is not None and str(value).strip() for value in row
    )] for sheet in sheets]
    populated = [rows for rows in populated if rows]
    if len(populated) != 1:
        raise ValueError("Use o Excel exportado em Conferência de nota fiscal no MES.")
    header, *body = populated[0]
    names = [_token(value) for value in header]
    required = ("data", "notafiscal", "status")
    if any(names.count(name) != 1 for name in required):
        raise ValueError("Colunas esperadas no Excel do MES: Data, Nota fiscal e Status.")
    dt, nf, status = (names.index(key) for key in required)
    if not body:
        raise ValueError("Nenhuma pré-nota no arquivo. A base anterior foi preservada.")
    for number, row in enumerate(body, 2):
        if (len(row) <= max(dt, nf, status) or not _has_date(row[dt])
                or row[nf] is None or not str(row[nf]).strip()):
            raise ValueError(f"Registro incompleto ou inválido na linha de dados {number - 1}.")
        if _token(row[status]) != "prenotalancada":
            raise ValueError("Exporte apenas o status Pré-nota lançada no MES.")
    return len(body)
