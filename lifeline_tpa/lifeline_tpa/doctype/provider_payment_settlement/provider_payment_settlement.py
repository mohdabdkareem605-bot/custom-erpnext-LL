import frappe
from frappe.model.document import Document

from lifeline_tpa.services.settlement_processing import (
    process_provider_payment,
    validate_provider_payment,
)


class ProviderPaymentSettlement(Document):
    def validate(self):
        self._validate_source_file()
        self._prevent_source_replacement()

    def before_submit(self):
        if self.status != "Validated":
            frappe.throw("Validate the provider payment file before submitting this settlement.")

    def on_cancel(self):
        if self.status == "Processed":
            frappe.throw(
                "A processed provider payment settlement cannot be cancelled automatically. "
                "Cancel its Payment Entries through the standard ERPNext controls."
            )
        self.db_set("status", "Cancelled", update_modified=False)

    def _validate_source_file(self):
        if self.source_file and not self.source_file.lower().endswith((".xlsx", ".csv")):
            frappe.throw("The provider payment file must be an .xlsx or .csv file.")

    def _prevent_source_replacement(self):
        previous = self.get_doc_before_save()
        if (
            previous
            and previous.source_file
            and previous.source_file != self.source_file
            and previous.status != "Draft"
        ):
            frappe.throw("The provider payment file cannot be replaced after validation starts.")


@frappe.whitelist()
def validate_payment_file(settlement_name):
    settlement = frappe.get_doc("Provider Payment Settlement", settlement_name)
    settlement.check_permission("write")

    if settlement.docstatus != 0:
        frappe.throw("Only a draft Provider Payment Settlement can be validated.")

    settlement.db_set("status", "Validating", update_modified=False)
    return validate_provider_payment(settlement)


@frappe.whitelist()
def process_payment_settlement(settlement_name):
    settlement = frappe.get_doc("Provider Payment Settlement", settlement_name)
    settlement.check_permission("write")
    return process_provider_payment(settlement, requested_by=frappe.session.user)
