from __future__ import annotations

from frappe.model.document import Document
from frappe.utils import flt


class APSScheduleResult(Document):
	def validate(self):
		segments = self.get("segments") or []
		if segments:
			self.scheduled_qty = sum(flt(row.planned_qty) for row in segments)
		self.unscheduled_qty = max(flt(self.planned_qty) - flt(self.scheduled_qty), 0)
		self.status = self.status or "Draft"
		self.risk_status = self.risk_status or "Normal"
