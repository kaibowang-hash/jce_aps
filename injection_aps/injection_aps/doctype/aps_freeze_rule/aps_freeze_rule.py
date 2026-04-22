from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class APSFreezeRule(Document):
	def validate(self):
		self.freeze_scope = self.freeze_scope or "Global"
		self.freeze_days = cint(self.freeze_days or 0)
		if self.freeze_days < 0:
			frappe.throw(_("Freeze Days cannot be negative."))
