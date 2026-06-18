import frappe
from frappe.model.document import Document


class ProviderFacilityMapping(Document):
    def validate(self):
        self.facility_id = self.facility_id.strip()
        if not self.facility_id:
            frappe.throw("Facility ID is required.")

