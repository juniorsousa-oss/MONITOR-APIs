from datetime import date
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook
import data_store as store

HEADER = ["Data", "Recebedor", "Nota fiscal", "Razão social", "CNPJ", "Status"]


def workbook(*rows):
    book = Workbook()
    sheet = book.active
    sheet.title = "NotasFiscais-Exportacao"
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


class MesPreNotasTests(TestCase):
    def test_valid_export_gives_header_and_two_rows(self):
        raw = workbook(HEADER, [date(2026, 11, 27), None, "000001", None, None, "Pré-nota lançada"],
                       ["27/11/2026 11:59", None, "000002", None, None, "Pré-nota lançada"])
        data, count = store.build_normalized_source("mes_pre_notas", "MES.xlsx", raw)
        self.assertTrue(data)
        self.assertEqual(count, 3)

    def test_incompatible_files_never_prepare_a_production_upload(self):
        cases = [
            ("protheus.xlsx", workbook(["Data", "Número", "Fornecedor"], [date.today(), 1, "Exemplo"])),
            ("vazio.xlsx", workbook(HEADER)),
            ("sem-filtro.xlsx", workbook(HEADER, [date.today(), None, 1, None, None, "Recebida"])),
            ("sem-data.xlsx", workbook(HEADER, ["-", None, 1, None, None, "Pré-nota lançada"])),
            ("sem-numero.xlsx", workbook(HEADER, [date.today(), None, None, None, None, "Pré-nota lançada"])),
            ("exportacao.csv", b"Data,Nota fiscal,Status"),
        ]
        for name, raw in cases:
            with self.subTest(name=name), patch.object(store, "central_api_call") as call:
                with self.assertRaises(ValueError):
                    store.save_report("mes_pre_notas", name, raw, max_attempts=1)
                call.assert_not_called()
