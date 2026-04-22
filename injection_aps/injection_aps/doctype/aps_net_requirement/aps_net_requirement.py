from __future__ import annotations

from frappe.model.document import Document


class APSNetRequirement(Document):
	def validate(self):
		self.planning_qty = self.planning_qty or self.net_requirement_qty
