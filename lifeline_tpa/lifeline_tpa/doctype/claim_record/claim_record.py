import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ClaimRecord(Document):
    def validate(self):
        if flt(self.claim_amount) < 0:
            frappe.throw("Claim Amount cannot be negative.")
        if flt(self.payer_allocated_amount) > flt(self.claim_amount):
            frappe.throw("Payer Allocated Amount cannot exceed Claim Amount.")
        if flt(self.provider_paid_amount) > flt(self.claim_amount):
            frappe.throw("Provider Paid Amount cannot exceed Claim Amount.")

