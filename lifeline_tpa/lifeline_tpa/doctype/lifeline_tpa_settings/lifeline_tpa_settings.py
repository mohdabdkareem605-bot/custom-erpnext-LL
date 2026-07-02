import frappe
from frappe.model.document import Document


class LifelineTPASettings(Document):
    def validate(self):
        if self.max_revenue_invoice_lines and self.max_revenue_invoice_lines < 1:
            frappe.throw("Max Revenue Invoice Lines must be at least 1.")
