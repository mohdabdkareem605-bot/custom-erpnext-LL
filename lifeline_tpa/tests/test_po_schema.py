import unittest

from lifeline_tpa.services.po_schema import MASTER_SHEET_COLUMNS, compare_headers


class TestPOSchema(unittest.TestCase):
    def test_exact_master_sheet_columns_are_valid(self):
        result = compare_headers(MASTER_SHEET_COLUMNS)

        self.assertTrue(result["valid"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["unexpected"], [])
        self.assertFalse(result["wrong_order"])

    def test_changed_column_order_is_rejected(self):
        headers = list(MASTER_SHEET_COLUMNS)
        headers[0], headers[1] = headers[1], headers[0]

        result = compare_headers(headers)

        self.assertFalse(result["valid"])
        self.assertTrue(result["wrong_order"])


if __name__ == "__main__":
    unittest.main()
