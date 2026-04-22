from __future__ import annotations

from frappe.model.document import Document


class APSMachineCapability(Document):
	def validate(self):
		self.machine_status = self.machine_status or "Available"
		self.is_active = 1 if self.is_active is None else self.is_active
