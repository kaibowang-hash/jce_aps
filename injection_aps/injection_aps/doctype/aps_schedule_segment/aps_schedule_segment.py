from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class APSScheduleSegment(Document):
	def validate(self):
		self.segment_status = self.segment_status or "Planned"
		if self.start_time and self.end_time and get_datetime(self.end_time) < get_datetime(self.start_time):
			frappe.throw(_("Segment end time cannot be earlier than start time."))
