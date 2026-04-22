import frappe

from injection_aps.services.customizations import (
	ensure_safe_to_uninstall,
	remove_owned_records,
	remove_standard_customizations,
)


def before_uninstall():
	ensure_safe_to_uninstall()
	remove_standard_customizations()
	remove_owned_records()
	frappe.clear_cache()
