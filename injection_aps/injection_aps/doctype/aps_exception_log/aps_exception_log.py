from __future__ import annotations

from frappe.model.document import Document


class APSExceptionLog(Document):
	def validate(self):
		self.status = self.status or "Open"
