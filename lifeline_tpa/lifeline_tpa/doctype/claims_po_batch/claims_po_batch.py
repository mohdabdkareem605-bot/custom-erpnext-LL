import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class ClaimsPOBatch(Document):
    def validate(self):
        self._validate_source_file()
        self._validate_dates()

    def _validate_source_file(self):
        if self.source_file and not self.source_file.lower().endswith(".xlsx"):
            frappe.throw("The PO source file must be an .xlsx workbook.")

    def _validate_dates(self):
        if self.posting_date and self.expected_payment_date:
            if getdate(self.expected_payment_date) < getdate(self.posting_date):
                frappe.throw("Expected Payment Date cannot be before Posting Date.")

