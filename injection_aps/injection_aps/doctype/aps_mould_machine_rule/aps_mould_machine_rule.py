from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class APSMouldMachineRule(Document):
	def validate(self):
		if flt(self.min_tonnage) and flt(self.max_tonnage) and flt(self.min_tonnage) > flt(self.max_tonnage):
			frappe.throw(_("Min Tonnage cannot be greater than Max Tonnage."))
