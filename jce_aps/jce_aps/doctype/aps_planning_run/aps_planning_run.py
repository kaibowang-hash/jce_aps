
from frappe.model.document import Document


class APSPlanningRun(Document):
    def before_save(self):
        if not self.status:
            self.status = "Draft"
