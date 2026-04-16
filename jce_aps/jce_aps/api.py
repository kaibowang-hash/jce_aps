import frappe
from frappe import _

from jce_aps.jce_aps.doctype.aps_planning_run.planner import plan_run


@frappe.whitelist()
def can_access_aps():
    return frappe.has_permission("APS Planning Run", "read")


@frappe.whitelist()
def run_planning_run(docname: str):
    doc = frappe.get_doc("APS Planning Run", docname)
    if doc.docstatus != 0:
        frappe.throw(_("Only Draft APS Planning Run can be planned."))
    result = plan_run(doc)
    doc.reload()
    return result
