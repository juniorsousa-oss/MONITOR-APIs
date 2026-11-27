import gzip
import json
import unittest
from io import BytesIO

from openpyxl import Workbook
import data_store as store


def make_source(warehouse):
    book = Workbook()
    ws = book.active
    for cell, value in {"A1":"CODIGO", "K1":"DATA", "M1":"TES", "AE1":"OP", "A2":"00001000",
                        "K2":"01/11/2026", "L2":warehouse, "M2":"520", "AE2":"OP00001234567"}.items():
        ws[cell] = value
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class ClosingSourceTests(unittest.TestCase):
    def test_dedicated_package_always_shows_the_four_sources(self):
        rows = store.closing_source_fields([{"source_key": "ops", "version": 6},
                                            {"source_key": "analitico", "version": 2}])
        self.assertEqual([r["source_key"] for r in rows], ["ops", "kardex_s2", "kardex_ep", "kardex_e2"])
        self.assertEqual([r["name"] for r in rows], ["OPS", "KARDEX S2", "KARDEX EP", "KARDEX E2"])
        self.assertEqual(rows[0]["version"], 6)

    def test_same_contract_as_the_receiving_app(self):
        data, count = store.build_normalized_source("kardex_ep", "kardex.xlsx", make_source("EP"))
        payload = json.loads(gzip.decompress(data))
        self.assertEqual(count, 1)
        self.assertEqual(payload["source_key"], "kardex_ep")
        self.assertEqual(payload["profile"], "CLOSING_XML_VALUES_V1")
        self.assertEqual(payload["sheets"][0]["rows"][1][0], "00001000")

    def test_wrong_warehouse_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "armazém diferente"):
            store.build_normalized_source("kardex_ep", "kardex.xlsx", make_source("S2"))
