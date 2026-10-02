from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path
from typing import Any

import pandas as pd


NORMALIZED_FORMAT = "pandas-split-json-gzip-v1"

# Cada fonte é interpretada uma única vez no ponto de entrada.
# Depois disso os consumidores trabalham somente com DataFrame serializado.
SOURCE_PROFILES: dict[str, dict[str, Any]] = {
    "relatorio_geral": {"sheet_name": "Geral", "header": 0, "profile": "GERAL_HEADER_0"},
    "for001": {"sheet_name": "PAINEL", "header": 4, "profile": "PAINEL_HEADER_4"},
    "for022": {"sheet_name": "Datas esperadas", "header": 0, "profile": "DATAS_ESPERADAS_HEADER_0"},
    "analitico": {"sheet_name": 0, "header": 1, "profile": "ANALITICO_HEADER_1"},
    "endereco": {"sheet_name": 0, "header": 1, "profile": "ENDERECO_HEADER_1"},
    "sc": {"sheet_name": 0, "header": 1, "profile": "SC_HEADER_1"},
    "pc": {
        "sheet_name": "2-Pedido de Compras   Autoriz",
        "header": 1,
        "profile": "PC_AUTORIZ_HEADER_1",
    },
    "pre_nota": {"sheet_name": 0, "header": 1, "profile": "PRE_NOTA_HEADER_1"},
    "pmp": {"sheet_name": 0, "header": 0, "profile": "PMP_HEADER_0"},
    "h001": {"sheet_name": 0, "header": 0, "profile": "H001_HEADER_0"},
    "cadastros": {"sheet_name": 0, "header": 1, "profile": "CADASTROS_HEADER_1"},
    # NF e MES PRÉ-NOTAS preservam a matriz bruta porque os consumidores
    # aplicam regras próprias de cabeçalho/posição. Mesmo assim o Excel
    # deixa de circular depois desta leitura.
    "nf": {"sheet_name": 0, "header": None, "profile": "NF_RAW_MATRIX"},
    "mes_pre_notas": {"sheet_name": 0, "header": None, "profile": "MES_PRE_NOTAS_RAW_MATRIX"},
}


def _read_excel(raw: bytes, profile: dict[str, Any], suffix: str) -> pd.DataFrame:
    kwargs: dict[str, Any] = {
        "sheet_name": profile.get("sheet_name", 0),
        "header": profile.get("header", 0),
    }
    if suffix in {".xls", ".xlt"}:
        kwargs["engine"] = "xlrd"
    return pd.read_excel(io.BytesIO(raw), **kwargs)


def read_source_frame(source_key: str, file_name: str, raw: bytes) -> tuple[pd.DataFrame, str]:
    key = str(source_key or "").strip().lower()
    profile = SOURCE_PROFILES.get(key)
    if profile is None:
        raise ValueError(f"Fonte sem perfil de normalização: {source_key}")

    suffix = Path(str(file_name or "").lower()).suffix
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xls", ".xlt"}:
        frame = _read_excel(raw, profile, suffix)
    elif suffix == ".csv":
        header = profile.get("header", 0)
        frame = pd.read_csv(
            io.BytesIO(raw),
            sep=None,
            engine="python",
            header=header,
        )
    elif suffix == ".json":
        frame = pd.read_json(io.BytesIO(raw))
    else:
        raise ValueError(
            f"{str(file_name or source_key)} não possui formato tabular suportado para normalização."
        )

    if not isinstance(frame, pd.DataFrame):
        raise ValueError(f"A fonte {source_key} não resultou em uma tabela válida.")

    return frame, str(profile.get("profile") or key.upper())


def dataframe_payload(frame: pd.DataFrame) -> bytes:
    text = frame.to_json(
        orient="split",
        date_format="iso",
        force_ascii=False,
        default_handler=str,
    )
    return gzip.compress(text.encode("utf-8"), compresslevel=6)


def normalize_source(source_key: str, file_name: str, raw: bytes) -> dict[str, Any]:
    frame, profile = read_source_frame(source_key, file_name, raw)
    payload = dataframe_payload(frame)
    return {
        "payload": payload,
        "rows_count": int(len(frame)),
        "columns_count": int(frame.shape[1]),
        "profile": profile,
        "format": NORMALIZED_FORMAT,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
    }
