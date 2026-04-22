from __future__ import annotations

import frappe

from injection_aps.services import planning


@frappe.whitelist()
def preview_customer_delivery_schedule(customer, company, version_no, file_url=None, rows_json=None):
	return planning.preview_customer_delivery_schedule(
		customer=customer,
		company=company,
		version_no=version_no,
		file_url=file_url,
		rows_json=rows_json,
	)


@frappe.whitelist()
def import_customer_delivery_schedule(customer, company, version_no, file_url=None, rows_json=None, source_type="Customer Delivery Schedule"):
	return planning.import_customer_delivery_schedule(
		customer=customer,
		company=company,
		version_no=version_no,
		file_url=file_url,
		rows_json=rows_json,
		source_type=source_type,
	)


@frappe.whitelist()
def rebuild_demand_pool(company=None):
	return planning.rebuild_demand_pool(company=company)


@frappe.whitelist()
def rebuild_net_requirements(company=None):
	return planning.rebuild_net_requirements(company=company)


@frappe.whitelist()
def run_planning_run(run_name=None, company=None, plant_floor=None, horizon_days=None):
	return planning.run_planning_run(
		run_name=run_name,
		company=company,
		plant_floor=plant_floor,
		horizon_days=horizon_days,
	)


@frappe.whitelist()
def approve_planning_run(run_name):
	return planning.approve_planning_run(run_name)


@frappe.whitelist()
def sync_planning_run_to_execution(run_name):
	return planning.sync_planning_run_to_execution(run_name)


@frappe.whitelist()
def release_planning_run(run_name, release_horizon_days=None):
	return planning.release_planning_run(run_name, release_horizon_days=release_horizon_days)


@frappe.whitelist()
def analyze_insert_order_impact(company, plant_floor, item_code, qty, required_date, customer=None):
	return planning.analyze_insert_order_impact(
		company=company,
		plant_floor=plant_floor,
		item_code=item_code,
		qty=qty,
		required_date=required_date,
		customer=customer,
	)


@frappe.whitelist()
def rebuild_exceptions(run_name):
	return planning.rebuild_exceptions(run_name)


@frappe.whitelist()
def detach_standard_references(dry_run=1):
	return planning.detach_standard_references(dry_run=frappe.utils.cint(dry_run))


@frappe.whitelist()
def get_workspace_dashboard_data():
	return {
		"active_schedules": frappe.db.count("Customer Delivery Schedule", {"status": "Active"}),
		"open_demands": frappe.db.count("APS Demand Pool", {"status": "Open"}),
		"open_net_requirements": frappe.db.count("APS Net Requirement", {"net_requirement_qty": (">", 0)}),
		"open_runs": frappe.db.count("APS Planning Run", {"status": ("in", planning.RUN_OPEN_STATUSES)}),
		"blocking_exceptions": frappe.db.count("APS Exception Log", {"status": "Open", "severity": ("in", ["Critical", "Blocking"])}),
		"released_batches": frappe.db.count("APS Release Batch", {"status": "Released"}),
		"synced_results": frappe.db.count("APS Schedule Result", {"status": ("in", ["Synced", "Released"])}),
		"machine_capabilities": frappe.db.count("APS Machine Capability", {"is_active": 1}),
	}


@frappe.whitelist()
def get_schedule_console_data(customer=None, company=None):
	schedule_filters = planning._strip_none({"customer": customer, "company": company})
	active_schedules = frappe.get_all(
		"Customer Delivery Schedule",
		filters=schedule_filters,
		fields=[
			"name",
			"customer",
			"company",
			"version_no",
			"source_type",
			"status",
			"schedule_total_qty",
			"modified",
		],
		order_by="modified desc",
		limit=50,
	)
	import_batches = frappe.get_all(
		"APS Schedule Import Batch",
		filters=schedule_filters,
		fields=[
			"name",
			"customer",
			"company",
			"version_no",
			"source_type",
			"status",
			"imported_rows",
			"effective_rows",
			"modified",
		],
		order_by="modified desc",
		limit=50,
	)
	return {
		"active_schedules": active_schedules,
		"import_batches": import_batches,
		"summary": {
			"active_versions": len([row for row in active_schedules if row.status == "Active"]),
			"recent_batches": len(import_batches),
			"active_qty": sum(frappe.utils.flt(row.schedule_total_qty) for row in active_schedules),
		},
	}


@frappe.whitelist()
def get_net_requirement_page_data(company=None, item_code=None):
	filters = planning._strip_none({"company": company, "item_code": item_code})
	rows = frappe.get_all(
		"APS Net Requirement",
		filters=filters,
		fields=[
			"name",
			"company",
			"customer",
			"item_code",
			"demand_date",
			"demand_qty",
			"available_stock_qty",
			"open_work_order_qty",
			"safety_stock_gap_qty",
			"minimum_batch_qty",
			"planning_qty",
			"net_requirement_qty",
			"reason_text",
		],
		order_by="demand_date asc, item_code asc",
		limit=200,
	)
	return {
		"rows": rows,
		"summary": {
			"rows": len(rows),
			"net_requirement_qty": sum(frappe.utils.flt(row.net_requirement_qty) for row in rows),
			"planning_qty": sum(frappe.utils.flt(row.planning_qty) for row in rows),
		},
	}


@frappe.whitelist()
def get_run_console_data(company=None, plant_floor=None):
	filters = planning._strip_none({"company": company, "plant_floor": plant_floor})
	runs = frappe.get_all(
		"APS Planning Run",
		filters=filters,
		fields=[
			"name",
			"company",
			"plant_floor",
			"planning_date",
			"status",
			"approval_state",
			"total_net_requirement_qty",
			"total_scheduled_qty",
			"total_unscheduled_qty",
			"exception_count",
			"result_count",
		],
		order_by="modified desc",
		limit=50,
	)
	return {"runs": runs}


@frappe.whitelist()
def get_schedule_gantt_data(run_name):
	results = frappe.get_all(
		"APS Schedule Result",
		filters={"planning_run": run_name},
		fields=["name", "item_code", "customer", "risk_status", "status"],
		order_by="modified asc",
	)
	if not results:
		return {"tasks": [], "rows": []}

	segments = frappe.get_all(
		"APS Schedule Segment",
		filters={"parent": ("in", [row.name for row in results])},
		fields=[
			"parent",
			"workstation",
			"start_time",
			"end_time",
			"planned_qty",
			"segment_status",
			"risk_flags",
		],
		order_by="start_time asc",
	)
	result_map = {row.name: row for row in results}
	tasks = []
	for row in segments:
		parent = result_map.get(row.parent)
		if not parent:
			continue
		tasks.append(
			{
				"id": row.parent,
				"name": f"{parent.item_code} / {row.workstation}",
				"start": row.start_time,
				"end": row.end_time,
				"progress": 100 if row.segment_status in ("Released", "Completed") else 0,
				"custom_class": f"ia-risk-{(parent.risk_status or 'normal').lower()}",
				"details": {
					"item_code": parent.item_code,
					"customer": parent.customer,
					"workstation": row.workstation,
					"planned_qty": row.planned_qty,
					"risk_flags": row.risk_flags,
				},
			}
		)
	return {"tasks": tasks, "rows": segments}


@frappe.whitelist()
def get_release_center_data(run_name=None):
	batch_filters = planning._strip_none({"planning_run": run_name})
	release_batches = frappe.get_all(
		"APS Release Batch",
		filters=batch_filters,
		fields=[
			"name",
			"planning_run",
			"status",
			"release_from_date",
			"release_to_date",
			"generated_work_orders",
			"work_order_scheduling",
		],
		order_by="modified desc",
		limit=50,
	)
	exception_filters = {"status": "Open"}
	if run_name:
		exception_filters["planning_run"] = run_name
	exceptions = frappe.get_all(
		"APS Exception Log",
		filters=exception_filters,
		fields=[
			"name",
			"planning_run",
			"severity",
			"exception_type",
			"item_code",
			"customer",
			"workstation",
			"message",
			"is_blocking",
		],
		order_by="modified desc",
		limit=100,
	)
	return {"release_batches": release_batches, "exceptions": exceptions}
