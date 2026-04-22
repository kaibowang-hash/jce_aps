from __future__ import annotations

from frappe.model.document import Document


class APSColorTransitionRule(Document):
	def validate(self):
		self.change_level = self.change_level or "Medium"
		self.is_active = 1 if self.is_active is None else self.is_active
