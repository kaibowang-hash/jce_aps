from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime


class APSPlanningRun(Document):
	def validate(self):
		self.status = self.status or "Draft"
		self.approval_state = self.approval_state or "Pending"
		self.run_type = self.run_type or "Trial"
		self.horizon_days = cint(self.horizon_days or 14)
		self.planning_date = self.planning_date or getdate()

		if not self.horizon_start:
			self.horizon_start = get_datetime(now_datetime())
		if not self.horizon_end:
			self.horizon_end = get_datetime(add_days(self.horizon_start, self.horizon_days))
		if get_datetime(self.horizon_end) < get_datetime(self.horizon_start):
			frappe.throw(_("Horizon End cannot be earlier than Horizon Start."))
