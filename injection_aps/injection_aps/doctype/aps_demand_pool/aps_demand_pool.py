from __future__ import annotations

from frappe.model.document import Document


class APSDemandPool(Document):
	def validate(self):
		self.status = self.status or "Open"
		self.demand_source = self.demand_source or "Customer Delivery Schedule"
