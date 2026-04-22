from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, today
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file


DEMAND_SOURCE_PRIORITY = {
	"Urgent Order": 1000,
	"Customer Delivery Schedule": 800,
	"Sales Order Backlog": 600,
	"Safety Stock": 400,
	"Trial Production": 300,
	"Complaint Replenishment": 300,
}

RUN_OPEN_STATUSES = ("Draft", "Planned", "Approved", "Synced", "Partially Released")
LOCKED_SEGMENT_STATUSES = ("Approved", "Synced", "Released", "Partially Released")
BLOCKING_WORKSTATION_RISK = "Non FDA"
MAX_REBUILD_WARNINGS = 20


class APSItemReferenceError(frappe.ValidationError):
	pass


def preview_customer_delivery_schedule(
	customer: str,
	company: str,
	version_no: str,
	file_url: str | None = None,
	rows_json: str | list[dict] | None = None,
) -> dict[str, Any]:
	rows = _normalize_schedule_rows(file_url=file_url, rows_json=rows_json)
	diff_rows = compare_schedule_against_active(customer=customer, company=company, rows=rows)
	return {
		"customer": customer,
		"company": company,
		"version_no": version_no,
		"row_count": len(diff_rows),
		"summary": _summarize_change_types(diff_rows),
		"rows": diff_rows,
	}


def import_customer_delivery_schedule(
	customer: str,
	company: str,
	version_no: str,
	file_url: str | None = None,
	rows_json: str | list[dict] | None = None,
	source_type: str = "Customer Delivery Schedule",
) -> dict[str, Any]:
	preview = preview_customer_delivery_schedule(
		customer=customer,
		company=company,
		version_no=version_no,
		file_url=file_url,
		rows_json=rows_json,
	)

	import_batch = frappe.get_doc(
		{
			"doctype": "APS Schedule Import Batch",
			"customer": customer,
			"company": company,
			"version_no": version_no,
			"status": "Imported",
			"imported_rows": len(preview["rows"]),
			"effective_rows": sum(1 for row in preview["rows"] if flt(row.get("qty")) > 0),
			"change_summary": json.dumps(preview["summary"], ensure_ascii=True, sort_keys=True),
			"source_type": source_type,
			"uploaded_file": file_url,
		}
	).insert(ignore_permissions=True)

	for name in frappe.get_all(
		"Customer Delivery Schedule",
		filters={"customer": customer, "company": company, "status": "Active"},
		pluck="name",
	):
		frappe.db.set_value("Customer Delivery Schedule", name, "status", "Superseded")

	schedule = frappe.get_doc(
		{
			"doctype": "Customer Delivery Schedule",
			"customer": customer,
			"company": company,
			"version_no": version_no,
			"import_batch": import_batch.name,
			"source_type": source_type,
			"status": "Active",
			"schedule_total_qty": sum(flt(row.get("qty")) for row in preview["rows"]),
			"change_summary": json.dumps(preview["summary"], ensure_ascii=True, sort_keys=True),
			"items": [
				{
					"sales_order": row.get("sales_order"),
					"item_code": row.get("item_code"),
					"customer_part_no": row.get("customer_part_no"),
					"schedule_date": row.get("schedule_date"),
					"qty": row.get("qty"),
					"allocated_qty": row.get("allocated_qty") or 0,
					"produced_qty": row.get("produced_qty") or 0,
					"delivered_qty": row.get("delivered_qty") or 0,
					"balance_qty": max(flt(row.get("qty")) - flt(row.get("delivered_qty")), 0),
					"change_type": row.get("change_type"),
					"status": "Open" if flt(row.get("qty")) > flt(row.get("delivered_qty")) else "Covered",
					"remark": row.get("remark"),
				}
				for row in preview["rows"]
			],
		}
	).insert(ignore_permissions=True)

	return {
		"import_batch": import_batch.name,
		"schedule": schedule.name,
		"summary": preview["summary"],
	}


def compare_schedule_against_active(customer: str, company: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	previous_rows = []
	previous_name = frappe.db.get_value(
		"Customer Delivery Schedule",
		{"customer": customer, "company": company, "status": "Active"},
		"name",
	)
	if previous_name:
		previous_rows = frappe.get_all(
			"Customer Delivery Schedule Item",
			filters={"parent": previous_name, "parenttype": "Customer Delivery Schedule"},
			fields=[
				"sales_order",
				"item_code",
				"customer_part_no",
				"schedule_date",
				"qty",
				"allocated_qty",
				"produced_qty",
				"delivered_qty",
				"balance_qty",
			],
		)

	previous_exact = {_schedule_row_key(row): row for row in previous_rows}
	current_exact = {_schedule_row_key(row): row for row in rows}
	processed_previous = set()
	diff_rows = []

	for key in sorted(set(previous_exact) & set(current_exact)):
		previous = previous_exact[key]
		current = dict(current_exact[key])
		current["previous_qty"] = flt(previous.get("qty"))
		current["allocated_qty"] = flt(previous.get("allocated_qty"))
		current["produced_qty"] = flt(previous.get("produced_qty"))
		current["delivered_qty"] = flt(previous.get("delivered_qty"))
		current["change_type"] = _detect_change_type(previous, current)
		current["balance_qty"] = max(flt(current.get("qty")) - flt(current.get("delivered_qty")), 0)
		diff_rows.append(current)
		processed_previous.add(key)

	previous_unmatched = [
		row for key, row in previous_exact.items() if key not in processed_previous and key not in current_exact
	]
	current_unmatched = [
		row for key, row in current_exact.items() if key not in processed_previous and key not in previous_exact
	]

	previous_grouped = defaultdict(list)
	current_grouped = defaultdict(list)
	for row in previous_unmatched:
		previous_grouped[_schedule_identity_key(row)].append(row)
	for row in current_unmatched:
		current_grouped[_schedule_identity_key(row)].append(row)

	for key in sorted(set(previous_grouped) | set(current_grouped)):
		previous_group = sorted(previous_grouped.get(key) or [], key=lambda row: getdate(row.get("schedule_date")))
		current_group = sorted(current_grouped.get(key) or [], key=lambda row: getdate(row.get("schedule_date")))
		pairs = min(len(previous_group), len(current_group))

		for idx in range(pairs):
			previous = previous_group[idx]
			current = dict(current_group[idx])
			current["previous_qty"] = flt(previous.get("qty"))
			current["allocated_qty"] = flt(previous.get("allocated_qty"))
			current["produced_qty"] = flt(previous.get("produced_qty"))
			current["delivered_qty"] = flt(previous.get("delivered_qty"))
			current["change_type"] = _detect_change_type(previous, current)
			current["balance_qty"] = max(flt(current.get("qty")) - flt(current.get("delivered_qty")), 0)
			diff_rows.append(current)

		for current in current_group[pairs:]:
			row = dict(current)
			row.setdefault("allocated_qty", 0)
			row.setdefault("produced_qty", 0)
			row.setdefault("delivered_qty", 0)
			row["previous_qty"] = 0
			row["change_type"] = "Added"
			row["balance_qty"] = max(flt(row.get("qty")) - flt(row.get("delivered_qty")), 0)
			diff_rows.append(row)

		for previous in previous_group[pairs:]:
			row = dict(previous)
			row["previous_qty"] = flt(previous.get("qty"))
			row["qty"] = 0
			row["change_type"] = "Cancelled"
			row["balance_qty"] = 0
			diff_rows.append(row)

	return sorted(
		diff_rows,
		key=lambda row: (
			getdate(row.get("schedule_date")),
			row.get("sales_order") or "",
			row.get("item_code") or "",
			row.get("customer_part_no") or "",
		),
	)


def rebuild_demand_pool(company: str | None = None) -> dict[str, Any]:
	_delete_system_generated_rows("APS Demand Pool", company=company)

	created_names = []
	warnings = []
	warning_keys = set()
	skipped_rows = 0
	active_schedules = frappe.get_all(
		"Customer Delivery Schedule",
		filters=_strip_none({"company": company, "status": "Active"}),
		fields=["name", "customer", "company", "version_no", "source_type"],
	)

	for schedule in active_schedules:
		for row in frappe.get_all(
			"Customer Delivery Schedule Item",
			filters={"parent": schedule.name, "parenttype": "Customer Delivery Schedule"},
			fields=[
				"name",
				"sales_order",
				"item_code",
				"schedule_date",
				"qty",
				"allocated_qty",
				"produced_qty",
				"delivered_qty",
				"balance_qty",
				"change_type",
				"customer_part_no",
			],
		):
			resolved_item_code = _resolve_item_name(row.item_code)
			if not resolved_item_code:
				skipped_rows += 1
				_append_rebuild_warning(
					warnings,
					warning_keys,
					item_reference=row.item_code,
					source_doctype="Customer Delivery Schedule",
					source_name=schedule.name,
					row_name=row.name,
				)
				continue
			if resolved_item_code != row.item_code:
				frappe.db.set_value(
					"Customer Delivery Schedule Item",
					row.name,
					"item_code",
					resolved_item_code,
					update_modified=False,
				)
			open_qty = max(flt(row.balance_qty or row.qty) - flt(row.allocated_qty), 0)
			if open_qty <= 0:
				continue
			demand = _build_demand_row(
				company=schedule.company,
				customer=schedule.customer,
				item_code=resolved_item_code,
				demand_source=schedule.source_type or "Customer Delivery Schedule",
				demand_date=row.schedule_date,
				qty=open_qty,
				source_doctype="Customer Delivery Schedule",
				source_name=schedule.name,
				sales_order=row.sales_order,
				remark=row.change_type,
				customer_part_no=row.customer_part_no,
			)
			created_names.append(demand.insert(ignore_permissions=True).name)

	backlog_result = _append_sales_order_backlog(company=company, warnings=warnings, warning_keys=warning_keys)
	created_names.extend(backlog_result["rows"])
	skipped_rows += cint(backlog_result.get("skipped_rows"))
	created_names.extend(_append_safety_stock_demands(company=company))

	return {
		"created_rows": len(created_names),
		"rows": created_names,
		"warning_count": len(warnings),
		"warnings": warnings[:MAX_REBUILD_WARNINGS],
		"skipped_rows": skipped_rows,
	}


def rebuild_net_requirements(company: str | None = None) -> dict[str, Any]:
	_delete_system_generated_rows("APS Net Requirement", company=company)

	demand_rows = frappe.get_all(
		"APS Demand Pool",
		filters=_strip_none({"company": company, "status": ("!=", "Cancelled")}),
		fields=[
			"name",
			"company",
			"customer",
			"item_code",
			"demand_date",
			"qty",
			"demand_source",
			"is_urgent",
		],
		order_by="demand_date asc, priority_score desc, modified asc",
	)
	grouped = defaultdict(list)
	warnings = []
	warning_keys = set()
	skipped_rows = 0
	for row in demand_rows:
		resolved_item_code = _resolve_item_name(row.item_code)
		if not resolved_item_code:
			skipped_rows += 1
			_append_rebuild_warning(
				warnings,
				warning_keys,
				item_reference=row.item_code,
				source_doctype="APS Demand Pool",
				source_name=row.name,
			)
			continue
		if resolved_item_code != row.item_code:
			frappe.db.set_value("APS Demand Pool", row.name, "item_code", resolved_item_code, update_modified=False)
			row.item_code = resolved_item_code
		grouped[(row.company, row.customer, resolved_item_code, row.demand_date)].append(row)

	stock_map = _get_available_stock_map(company)
	open_work_order_map = _get_open_work_order_map(company)
	settings = get_settings_dict()

	created_names = []
	for (row_company, customer, item_code, demand_date), rows in grouped.items():
		demand_qty = sum(flt(row.qty) for row in rows)
		available_stock_qty = flt(stock_map.get(item_code))
		open_work_order_qty = flt(open_work_order_map.get(item_code))
		safety_stock_qty = flt(_get_item_mapping_value(item_code, settings["item_safety_stock_field"]))
		max_stock_qty = flt(_get_item_mapping_value(item_code, settings["item_max_stock_field"]))
		minimum_batch_qty = flt(_get_item_mapping_value(item_code, settings["item_min_batch_field"]))
		safety_gap = max(safety_stock_qty - available_stock_qty, 0)
		overstock_qty = max(available_stock_qty - max_stock_qty, 0) if max_stock_qty else 0
		net_qty = max(demand_qty - available_stock_qty - open_work_order_qty + safety_gap - overstock_qty, 0)
		planning_qty = max(net_qty, minimum_batch_qty) if net_qty > 0 and minimum_batch_qty > 0 else net_qty
		reason_text = _build_net_requirement_reason(
			demand_qty=demand_qty,
			available_stock_qty=available_stock_qty,
			open_work_order_qty=open_work_order_qty,
			safety_gap=safety_gap,
			overstock_qty=overstock_qty,
			minimum_batch_qty=minimum_batch_qty,
			planning_qty=planning_qty,
		)

		doc = frappe.get_doc(
			{
				"doctype": "APS Net Requirement",
				"company": row_company,
				"customer": customer,
				"item_code": item_code,
				"demand_date": demand_date,
				"demand_qty": demand_qty,
				"available_stock_qty": available_stock_qty,
				"open_work_order_qty": open_work_order_qty,
				"safety_stock_gap_qty": safety_gap,
				"max_stock_qty": max_stock_qty,
				"overstock_qty": overstock_qty,
				"minimum_batch_qty": minimum_batch_qty,
				"planning_qty": planning_qty,
				"net_requirement_qty": net_qty,
				"reason_text": reason_text,
				"is_system_generated": 1,
			}
		).insert(ignore_permissions=True)
		created_names.append(doc.name)

	return {
		"created_rows": len(created_names),
		"rows": created_names,
		"warning_count": len(warnings),
		"warnings": warnings[:MAX_REBUILD_WARNINGS],
		"skipped_rows": skipped_rows,
	}


def run_planning_run(
	run_name: str | None = None,
	company: str | None = None,
	plant_floor: str | None = None,
	horizon_days: int | None = None,
) -> dict[str, Any]:
	settings = get_settings_dict()
	horizon_days = cint(horizon_days or settings["planning_horizon_days"] or 14)
	horizon_start = get_datetime(now_datetime())
	horizon_end = get_datetime(add_days(horizon_start, horizon_days))

	if run_name:
		run_doc = frappe.get_doc("APS Planning Run", run_name)
	else:
		run_doc = frappe.get_doc(
			{
				"doctype": "APS Planning Run",
				"company": company or settings["default_company"],
				"plant_floor": plant_floor or settings["default_plant_floor"],
				"planning_date": today(),
				"horizon_days": horizon_days,
				"horizon_start": horizon_start,
				"horizon_end": horizon_end,
				"run_type": "Trial",
				"status": "Draft",
				"approval_state": "Pending",
			}
		).insert(ignore_permissions=True)

	demand_rebuild = rebuild_demand_pool(company=run_doc.company)
	net_rebuild = rebuild_net_requirements(company=run_doc.company)

	for name in frappe.get_all("APS Schedule Result", filters={"planning_run": run_doc.name}, pluck="name"):
		frappe.delete_doc("APS Schedule Result", name, force=1, ignore_permissions=True)
	for name in frappe.get_all("APS Exception Log", filters={"planning_run": run_doc.name}, pluck="name"):
		frappe.delete_doc("APS Exception Log", name, force=1, ignore_permissions=True)

	net_rows = frappe.get_all(
		"APS Net Requirement",
		filters={
			"company": run_doc.company,
			"net_requirement_qty": (">", 0),
			"demand_date": ("between", [getdate(horizon_start), getdate(horizon_end)]),
		},
		fields=[
			"name",
			"customer",
			"item_code",
			"demand_date",
			"demand_qty",
			"planning_qty",
			"minimum_batch_qty",
			"net_requirement_qty",
			"reason_text",
		],
		order_by="demand_date asc, modified asc",
	)

	capability_rows = _get_machine_capability_rows(plant_floor=run_doc.plant_floor)
	workstation_state = _build_workstation_state_map(capability_rows)
	locked_segments = _get_locked_segments(run_doc.plant_floor)
	_apply_locked_segments_to_state(workstation_state, locked_segments)

	result_names = []
	exception_names = []
	total_scheduled_qty = 0
	total_unscheduled_qty = 0

	for row in net_rows:
		planning_qty = flt(row.planning_qty or row.net_requirement_qty)
		item_context = _get_item_context(row.item_code, settings)
		demand_source = _get_primary_demand_source(row.item_code, row.customer, row.demand_date)
		candidates = _select_machine_candidates(
			item_code=row.item_code,
			item_context=item_context,
			capability_rows=capability_rows,
			plant_floor=run_doc.plant_floor,
		)

		best = _choose_best_slot(
			item_code=row.item_code,
			item_context=item_context,
			qty=planning_qty,
			demand_date=row.demand_date,
			horizon_start=horizon_start,
			horizon_end=horizon_end,
			workstation_state=workstation_state,
			candidates=candidates,
			settings=settings,
		)

		result_doc = frappe.get_doc(
			{
				"doctype": "APS Schedule Result",
				"planning_run": run_doc.name,
				"company": run_doc.company,
				"plant_floor": run_doc.plant_floor,
				"net_requirement": row.name,
				"customer": row.customer,
				"item_code": row.item_code,
				"requested_date": row.demand_date,
				"demand_source": demand_source,
				"planned_qty": planning_qty,
				"scheduled_qty": best["scheduled_qty"],
				"unscheduled_qty": best["unscheduled_qty"],
				"status": best["result_status"],
				"risk_status": best["risk_status"],
				"is_urgent": 1 if item_context["is_urgent"] else 0,
				"is_locked": 0,
				"is_manual": 0,
				"notes": row.reason_text,
				"segments": best["segments"],
			}
		).insert(ignore_permissions=True)
		result_names.append(result_doc.name)
		total_scheduled_qty += flt(best["scheduled_qty"])
		total_unscheduled_qty += flt(best["unscheduled_qty"])

		for error in best["exceptions"]:
			exception_doc = _create_exception(
				planning_run=run_doc.name,
				severity=error["severity"],
				exception_type=error["exception_type"],
				message=error["message"],
				item_code=row.item_code,
				customer=row.customer,
				workstation=error.get("workstation"),
				source_doctype="APS Net Requirement",
				source_name=row.name,
				resolution_hint=error.get("resolution_hint"),
				is_blocking=error.get("is_blocking", 1),
			)
			exception_names.append(exception_doc.name)

	run_doc.db_set(
		{
			"horizon_days": horizon_days,
			"horizon_start": horizon_start,
			"horizon_end": horizon_end,
			"status": "Planned",
			"approval_state": "Pending",
			"total_net_requirement_qty": sum(flt(row.planning_qty or row.net_requirement_qty) for row in net_rows),
			"total_scheduled_qty": total_scheduled_qty,
			"total_unscheduled_qty": total_unscheduled_qty,
			"exception_count": len(exception_names),
			"result_count": len(result_names),
		}
	)

	return {
		"run": run_doc.name,
		"results": result_names,
		"exceptions": exception_names,
		"preflight_warning_count": cint(demand_rebuild.get("warning_count")) + cint(net_rebuild.get("warning_count")),
		"preflight_warnings": (demand_rebuild.get("warnings") or []) + (net_rebuild.get("warnings") or []),
	}


def approve_planning_run(run_name: str) -> dict[str, Any]:
	run_doc = frappe.get_doc("APS Planning Run", run_name)
	result_names = frappe.get_all("APS Schedule Result", filters={"planning_run": run_name}, pluck="name")
	run_doc.db_set(
		{
			"status": "Approved",
			"approval_state": "Approved",
			"approved_by": frappe.session.user,
			"approved_on": now_datetime(),
		}
	)
	for result_name in result_names:
		frappe.db.set_value("APS Schedule Result", result_name, "status", "Approved")
	if result_names:
		for segment_name in frappe.get_all(
			"APS Schedule Segment",
			filters={"parenttype": "APS Schedule Result", "parent": ("in", result_names)},
			pluck="name",
		):
			frappe.db.set_value("APS Schedule Segment", segment_name, "segment_status", "Approved")
	return {"run": run_name, "status": "Approved"}


def sync_planning_run_to_execution(run_name: str) -> dict[str, Any]:
	run_doc = frappe.get_doc("APS Planning Run", run_name)
	if run_doc.approval_state != "Approved":
		frappe.throw(_("Approve the APS Planning Run before syncing it downstream."))

	delivery_plan_name = _sync_delivery_plan(run_doc)
	work_order_scheduling_name = _sync_existing_work_orders_to_scheduling(run_doc)

	run_doc.db_set("status", "Synced")
	for result_name in frappe.get_all("APS Schedule Result", filters={"planning_run": run_name}, pluck="name"):
		frappe.db.set_value("APS Schedule Result", result_name, "status", "Synced")
	return {
		"run": run_name,
		"delivery_plan": delivery_plan_name,
		"work_order_scheduling": work_order_scheduling_name,
	}


def release_planning_run(run_name: str, release_horizon_days: int | None = None) -> dict[str, Any]:
	run_doc = frappe.get_doc("APS Planning Run", run_name)
	settings = get_settings_dict()
	release_horizon_days = cint(release_horizon_days or settings["release_horizon_days"] or 3)
	release_to = getdate(add_days(today(), release_horizon_days))

	batch = frappe.get_doc(
		{
			"doctype": "APS Release Batch",
			"planning_run": run_name,
			"company": run_doc.company,
			"release_from_date": today(),
			"release_to_date": release_to,
			"status": "Draft",
		}
	).insert(ignore_permissions=True)

	results = frappe.get_all(
		"APS Schedule Result",
		filters={
			"planning_run": run_name,
			"requested_date": ("<=", release_to),
			"scheduled_qty": (">", 0),
		},
		fields=[
			"name",
			"customer",
			"item_code",
			"requested_date",
			"scheduled_qty",
			"demand_source",
			"is_urgent",
		],
	)

	created_work_orders = []
	scheduling_items = []
	for result in results:
		segments = frappe.get_all(
			"APS Schedule Segment",
			filters={"parent": result.name, "parenttype": "APS Schedule Result"},
			fields=[
				"name",
				"workstation",
				"start_time",
				"end_time",
				"planned_qty",
				"mould_reference",
			],
			order_by="sequence_no asc, idx asc",
		)
		for segment in segments:
			work_order_name = _ensure_released_work_order(
				run_doc=run_doc,
				result=result,
				segment=segment,
				settings=settings,
			)
			if work_order_name:
				created_work_orders.append(work_order_name)
				scheduling_items.append(
					{
						"work_order": work_order_name,
						"scheduling_qty": segment.planned_qty,
						"workstation": segment.workstation,
						"planned_start_date": segment.start_time,
						"planned_end_date": segment.end_time,
						"remarks": result.name,
					}
				)

	work_order_scheduling_name = _create_release_work_order_scheduling(
		run_doc=run_doc,
		release_batch=batch.name,
		scheduling_items=scheduling_items,
	)

	batch.db_set(
		{
			"status": "Released",
			"generated_work_orders": len(set(created_work_orders)),
			"work_order_scheduling": work_order_scheduling_name,
		}
	)
	run_doc.db_set("status", "Partially Released" if created_work_orders else run_doc.status)
	released_result_names = [row.name for row in results]
	for result_name in released_result_names:
		frappe.db.set_value("APS Schedule Result", result_name, "status", "Released")
	segment_filters = {"name": "__missing__"}
	if released_result_names:
		segment_filters = {"parenttype": "APS Schedule Result", "parent": ("in", released_result_names)}
	for segment_name in frappe.get_all(
		"APS Schedule Segment",
		filters=segment_filters,
		pluck="name",
	):
		frappe.db.set_value("APS Schedule Segment", segment_name, "segment_status", "Released")
	return {
		"release_batch": batch.name,
		"work_orders": sorted(set(created_work_orders)),
		"work_order_scheduling": work_order_scheduling_name,
	}


def analyze_insert_order_impact(
	company: str,
	plant_floor: str,
	item_code: str,
	qty: float,
	required_date: str,
	customer: str | None = None,
) -> dict[str, Any]:
	settings = get_settings_dict()
	item_code = _require_item_name(item_code)
	item_context = _get_item_context(item_code, settings)
	capability_rows = _get_machine_capability_rows(plant_floor=plant_floor)
	workstation_state = _build_workstation_state_map(capability_rows)
	locked_segments = _get_locked_segments(plant_floor)
	_apply_locked_segments_to_state(workstation_state, locked_segments)
	candidates = _select_machine_candidates(
		item_code=item_code,
		item_context=item_context,
		capability_rows=capability_rows,
		plant_floor=plant_floor,
	)
	best = _choose_best_slot(
		item_code=item_code,
		item_context=item_context,
		qty=qty,
		demand_date=required_date,
		horizon_start=get_datetime(now_datetime()),
		horizon_end=get_datetime(add_days(required_date, 7)),
		workstation_state=workstation_state,
		candidates=candidates,
		settings=settings,
	)
	impacted = []
	impacted_customers = set()
	changeover_minutes = sum(flt(segment.get("changeover_minutes")) for segment in best.get("segments") or [])
	if best["segments"]:
		first_segment = best["segments"][0]
		overlap_segments = frappe.get_all(
			"APS Schedule Segment",
			filters={
				"workstation": first_segment.get("workstation"),
				"start_time": ("<", first_segment.get("end_time")),
				"end_time": (">", first_segment.get("start_time")),
			},
			fields=["name", "parent", "workstation", "start_time", "end_time", "planned_qty"],
			order_by="start_time asc",
		)
		result_meta = {
			row.name: row
			for row in frappe.get_all(
				"APS Schedule Result",
				filters={"name": ("in", [row.parent for row in overlap_segments])} if overlap_segments else {"name": "__missing__"},
				fields=["name", "customer", "item_code", "requested_date"],
			)
		}
		for row in overlap_segments:
			parent = result_meta.get(row.parent)
			if parent and parent.customer:
				impacted_customers.add(parent.customer)
			impacted.append(
				{
					"workstation": row.get("workstation"),
					"segment_name": row.get("name"),
					"result_name": row.get("parent"),
					"item_code": parent.item_code if parent else None,
					"customer": parent.customer if parent else None,
					"requested_date": parent.requested_date if parent else None,
					"start_time": row.get("start_time"),
					"end_time": row.get("end_time"),
					"planned_qty": row.get("planned_qty"),
				}
			)

	return {
		"item_code": item_code,
		"customer": customer,
		"required_date": required_date,
		"scheduled_qty": best["scheduled_qty"],
		"unscheduled_qty": best["unscheduled_qty"],
		"candidate_workstations": [row.get("workstation") for row in candidates],
		"impacted_segments": impacted,
		"impacted_customers": sorted(impacted_customers),
		"changeover_minutes": changeover_minutes,
		"missing_machine": any(error.get("exception_type") == "Machine Unavailable" for error in best["exceptions"]),
		"missing_mould": 0 if _get_preferred_mold_row(item_code) else 1,
		"exceptions": best["exceptions"],
	}


def rebuild_exceptions(run_name: str) -> dict[str, Any]:
	for name in frappe.get_all("APS Exception Log", filters={"planning_run": run_name}, pluck="name"):
		frappe.delete_doc("APS Exception Log", name, force=1, ignore_permissions=True)

	recreated = []
	for row in frappe.get_all(
		"APS Schedule Result",
		filters={"planning_run": run_name, "risk_status": ("in", ["Attention", "Critical", "Blocked"])},
		fields=["name", "customer", "item_code", "status", "risk_status", "unscheduled_qty"],
	):
		severity = "Critical" if row.risk_status in ("Critical", "Blocked") else "Warning"
		doc = _create_exception(
			planning_run=run_name,
			severity=severity,
			exception_type="Scheduling Risk",
			message=_("Result {0} has risk state {1} and unscheduled qty {2}.").format(
				row.name, row.risk_status, row.unscheduled_qty
			),
			item_code=row.item_code,
			customer=row.customer,
			source_doctype="APS Schedule Result",
			source_name=row.name,
			resolution_hint=_("Review the planned sequence, capacity and frozen segments."),
			is_blocking=1 if row.risk_status == "Blocked" else 0,
		)
		recreated.append(doc.name)
	return {"run": run_name, "exceptions": recreated}


def detach_standard_references(dry_run: bool = True) -> dict[str, Any]:
	rows = []
	for doctype, fieldnames in {
		"Work Order": [
			"custom_aps_run",
			"custom_aps_source",
			"custom_aps_required_delivery_date",
			"custom_aps_is_urgent",
			"custom_aps_release_status",
			"custom_aps_locked_for_reschedule",
			"custom_aps_schedule_reference",
		],
		"Work Order Scheduling": [
			"custom_aps_run",
			"custom_aps_freeze_state",
			"custom_aps_approval_state",
		],
		"Delivery Plan": [
			"custom_aps_version",
			"custom_aps_source",
		],
	}.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		names = _get_records_with_any_field_set(doctype, fieldnames)
		rows.append({"doctype": doctype, "count": len(names), "names": names[:20]})
		if not dry_run and names:
			for name in names:
				values = {fieldname: None for fieldname in fieldnames if frappe.get_meta(doctype).has_field(fieldname)}
				frappe.db.set_value(doctype, name, values)
	return {"dry_run": cint(dry_run), "rows": rows}


def get_settings_dict() -> dict[str, Any]:
	settings = frappe.get_cached_doc("APS Settings", "APS Settings")
	return {
		"default_company": settings.default_company,
		"default_plant_floor": settings.default_plant_floor,
		"planning_horizon_days": cint(settings.planning_horizon_days or 14),
		"release_horizon_days": cint(settings.release_horizon_days or 3),
		"freeze_days": cint(settings.freeze_days or 2),
		"default_setup_minutes": flt(settings.default_setup_minutes or 30),
		"default_first_article_minutes": flt(settings.default_first_article_minutes or 45),
		"default_hourly_capacity_qty": flt(settings.default_hourly_capacity_qty or 120),
		"item_food_grade_field": settings.item_food_grade_field or "custom_food_grade",
		"item_first_article_field": settings.item_first_article_field or "custom_is_first_article",
		"item_color_field": settings.item_color_field or "color",
		"item_material_field": settings.item_material_field or "material",
		"item_safety_stock_field": settings.item_safety_stock_field or "safety_stock",
		"item_max_stock_field": settings.item_max_stock_field or "max_stock_qty",
		"item_min_batch_field": settings.item_min_batch_field or "min_order_qty",
		"customer_short_name_field": settings.customer_short_name_field or "custom_customer_short_name",
		"workstation_risk_field": settings.workstation_risk_field or "custom_production_risk_category",
		"scheduling_item_risk_field": settings.scheduling_item_risk_field or "custom_workstation_risk_category_",
		"plant_floor_source_warehouse_field": settings.plant_floor_source_warehouse_field or "custom_default_source_warehouse",
		"plant_floor_wip_warehouse_field": settings.plant_floor_wip_warehouse_field or "warehouse",
		"plant_floor_fg_warehouse_field": settings.plant_floor_fg_warehouse_field or "custom_default_finished_goods_warehouse",
		"plant_floor_scrap_warehouse_field": settings.plant_floor_scrap_warehouse_field or "custom_default_scrap_warehouse",
	}


def _normalize_schedule_rows(
	file_url: str | None = None,
	rows_json: str | list[dict] | None = None,
) -> list[dict[str, Any]]:
	if file_url:
		raw_rows = read_xlsx_file_from_attached_file(file_url=file_url)
		if not raw_rows:
			return []
		headers = [_normalize_header(cell) for cell in raw_rows[0]]
		data_rows = [
			{headers[idx]: row[idx] for idx in range(min(len(headers), len(row)))}
			for row in raw_rows[1:]
			if any(cell not in (None, "") for cell in row)
		]
	elif isinstance(rows_json, str):
		data_rows = json.loads(rows_json or "[]")
	else:
		data_rows = rows_json or []

	normalized = []
	for row in data_rows:
		item_code = row.get("item_code") or row.get("item") or row.get("item code")
		if not item_code:
			continue
		item_code = _resolve_item_name(item_code) or item_code
		schedule_date = row.get("schedule_date") or row.get("schedule date") or row.get("delivery_date") or row.get("delivery date")
		normalized.append(
			{
				"sales_order": row.get("sales_order") or row.get("sales order"),
				"item_code": item_code,
				"customer_part_no": row.get("customer_part_no") or row.get("customer part no"),
				"schedule_date": getdate(schedule_date) if schedule_date else getdate(today()),
				"qty": flt(row.get("qty") or row.get("quantity")),
				"remark": row.get("remark") or row.get("remarks"),
			}
		)
	return normalized


def _normalize_header(value: Any) -> str:
	return str(value or "").strip().lower().replace("_", " ")


def _resolve_item_name(item_reference: str | None) -> str | None:
	if not item_reference or not frappe.db.exists("DocType", "Item"):
		return None

	reference = str(item_reference).strip()
	if not reference:
		return None

	cache = _get_request_cache("injection_aps_item_resolution_cache")
	if reference in cache:
		return cache[reference] or None

	item_name = None
	if frappe.db.exists("Item", reference):
		item_name = reference
	else:
		item_name = frappe.db.get_value("Item", {"item_code": reference}, "name")

	cache[reference] = item_name or ""
	return item_name or None


def _require_item_name(item_reference: str | None) -> str:
	item_name = _resolve_item_name(item_reference)
	if item_name:
		return item_name
	raise APSItemReferenceError(_("Item reference {0} could not be resolved to an Item record.").format(item_reference or ""))


def _get_request_cache(cache_key: str) -> dict[str, Any]:
	cache = getattr(frappe.local, cache_key, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, cache_key, cache)
	return cache


def _append_rebuild_warning(
	warnings: list[dict[str, Any]],
	warning_keys: set[tuple[str, str, str, str]],
	*,
	item_reference: str | None,
	source_doctype: str,
	source_name: str | None = None,
	row_name: str | None = None,
):
	key = (
		source_doctype or "",
		source_name or "",
		row_name or "",
		str(item_reference or ""),
	)
	if key in warning_keys:
		return
	warning_keys.add(key)
	message = _("Skipped {0} {1} because item reference {2} could not be resolved to an Item record.").format(
		source_doctype,
		source_name or row_name or "",
		item_reference or _("(blank)"),
	)
	warnings.append(
		{
			"source_doctype": source_doctype,
			"source_name": source_name,
			"row_name": row_name,
			"item_reference": item_reference,
			"message": message,
		}
	)


def _schedule_row_key(row: dict[str, Any]) -> tuple:
	return (
		row.get("sales_order") or "",
		row.get("item_code") or "",
		str(getdate(row.get("schedule_date"))),
		row.get("customer_part_no") or "",
	)


def _schedule_identity_key(row: dict[str, Any]) -> tuple:
	return (
		row.get("sales_order") or "",
		row.get("item_code") or "",
		row.get("customer_part_no") or "",
	)


def _detect_change_type(previous: dict[str, Any], current: dict[str, Any]) -> str:
	if not previous and flt(current.get("qty")) > 0:
		return "Added"
	if previous and flt(current.get("qty")) <= 0:
		return "Cancelled"
	if previous and getdate(current.get("schedule_date")) < getdate(previous.get("schedule_date")):
		return "Advanced"
	if previous and getdate(current.get("schedule_date")) > getdate(previous.get("schedule_date")):
		return "Delayed"
	if flt(current.get("qty")) > flt(previous.get("qty")):
		return "Increased"
	if flt(current.get("qty")) < flt(previous.get("qty")):
		return "Reduced"
	return "Unchanged"


def _summarize_change_types(rows: list[dict[str, Any]]) -> dict[str, int]:
	summary = defaultdict(int)
	for row in rows:
		summary[row.get("change_type") or "Unknown"] += 1
	return dict(summary)


def _build_demand_row(
	company: str,
	customer: str | None,
	item_code: str,
	demand_source: str,
	demand_date,
	qty: float,
	source_doctype: str,
	source_name: str,
	sales_order: str | None = None,
	remark: str | None = None,
	customer_part_no: str | None = None,
	is_urgent: int = 0,
) -> frappe.model.document.Document:
	settings = get_settings_dict()
	item_code = _require_item_name(item_code)
	item_context = _get_item_context(item_code, settings)
	return frappe.get_doc(
		{
			"doctype": "APS Demand Pool",
			"company": company,
			"customer": customer,
			"sales_order": sales_order,
			"item_code": item_code,
			"customer_part_no": customer_part_no,
			"demand_source": demand_source,
			"demand_date": demand_date,
			"qty": qty,
			"status": "Open",
			"priority_score": _score_demand(
				demand_source=demand_source,
				demand_date=demand_date,
				is_urgent=is_urgent,
			),
			"is_urgent": is_urgent,
			"food_grade": item_context["food_grade"],
			"color_code": item_context["color_code"],
			"material_code": item_context["material_code"],
			"is_first_article": 1 if item_context["is_first_article"] else 0,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"remark": remark,
			"is_system_generated": 1,
		}
	)


def _append_sales_order_backlog(
	company: str | None = None,
	warnings: list[dict[str, Any]] | None = None,
	warning_keys: set[tuple[str, str, str, str]] | None = None,
) -> dict[str, Any]:
	if not frappe.db.exists("DocType", "Sales Order Item"):
		return {"rows": [], "skipped_rows": 0}

	query = """
		select
			so.company,
			so.customer,
			soi.parent as sales_order,
			soi.item_code,
			soi.delivery_date,
			greatest(ifnull(soi.qty, 0) - ifnull(soi.delivered_qty, 0), 0) as open_qty
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		where so.docstatus = 1
			and ifnull(so.status, '') not in ('Closed', 'Completed', 'Cancelled')
			and greatest(ifnull(soi.qty, 0) - ifnull(soi.delivered_qty, 0), 0) > 0
	"""
	params = []
	if company:
		query += " and so.company = %s"
		params.append(company)

	rows = frappe.db.sql(query, params, as_dict=True)
	active_schedule_pairs = set()
	for schedule_row in frappe.db.sql(
		"""
		select cdsi.name, cdsi.parent, cdsi.sales_order, cdsi.item_code
		from `tabCustomer Delivery Schedule Item` cdsi
		inner join `tabCustomer Delivery Schedule` cds on cds.name = cdsi.parent
		where cds.status = 'Active'
		""",
		as_dict=True,
	):
		resolved_item_code = _resolve_item_name(schedule_row.item_code)
		if not resolved_item_code:
			if warnings is not None and warning_keys is not None:
				_append_rebuild_warning(
					warnings,
					warning_keys,
					item_reference=schedule_row.item_code,
					source_doctype="Customer Delivery Schedule",
					source_name=schedule_row.parent,
					row_name=schedule_row.name,
				)
			continue
		if resolved_item_code != schedule_row.item_code:
			frappe.db.set_value(
				"Customer Delivery Schedule Item",
				schedule_row.name,
				"item_code",
				resolved_item_code,
				update_modified=False,
			)
		active_schedule_pairs.add((schedule_row.sales_order, resolved_item_code))
	created = []
	skipped_rows = 0
	for row in rows:
		resolved_item_code = _resolve_item_name(row.item_code)
		if not resolved_item_code:
			skipped_rows += 1
			if warnings is not None and warning_keys is not None:
				_append_rebuild_warning(
					warnings,
					warning_keys,
					item_reference=row.item_code,
					source_doctype="Sales Order",
					source_name=row.sales_order,
				)
			continue
		if (row.sales_order, resolved_item_code) in active_schedule_pairs:
			continue
		demand = _build_demand_row(
			company=row.company,
			customer=row.customer,
			item_code=resolved_item_code,
			demand_source="Sales Order Backlog",
			demand_date=row.delivery_date or today(),
			qty=row.open_qty,
			source_doctype="Sales Order",
			source_name=row.sales_order,
			sales_order=row.sales_order,
		)
		created.append(demand.insert(ignore_permissions=True).name)
	return {"rows": created, "skipped_rows": skipped_rows}


def _append_safety_stock_demands(company: str | None = None) -> list[str]:
	settings = get_settings_dict()
	fieldname = settings["item_safety_stock_field"]
	if not fieldname or not frappe.db.exists("DocType", "Item"):
		return []
	item_meta = frappe.get_meta("Item")
	if not item_meta.has_field(fieldname):
		return []

	created = []
	stock_map = _get_available_stock_map(company)
	item_rows = frappe.get_all(
		"Item",
		filters={"disabled": 0},
		fields=["name", fieldname],
	)
	for item in item_rows:
		safety_stock = flt(item.get(fieldname))
		if not safety_stock:
			continue
		shortage = max(safety_stock - flt(stock_map.get(item.name)), 0)
		if shortage <= 0:
			continue
		demand = _build_demand_row(
			company=company or frappe.defaults.get_user_default("Company"),
			customer=None,
			item_code=item.name,
			demand_source="Safety Stock",
			demand_date=today(),
			qty=shortage,
			source_doctype="Item",
			source_name=item.name,
		)
		created.append(demand.insert(ignore_permissions=True).name)
	return created


def _score_demand(demand_source: str, demand_date, is_urgent: int = 0) -> int:
	days_to_due = (getdate(demand_date) - getdate(today())).days
	urgency_bonus = 250 if cint(is_urgent) else 0
	date_bonus = max(60 - max(days_to_due, -30), 0)
	return cint(DEMAND_SOURCE_PRIORITY.get(demand_source, 100) + urgency_bonus + date_bonus)


def _get_available_stock_map(company: str | None) -> dict[str, float]:
	if not frappe.db.exists("DocType", "Bin"):
		return {}
	query = """
		select
			bin.item_code,
			sum(ifnull(bin.actual_qty, 0) - ifnull(bin.reserved_qty, 0)) as available_qty
		from `tabBin` bin
		inner join `tabWarehouse` wh on wh.name = bin.warehouse
		where wh.is_group = 0
	"""
	params = []
	if company:
		query += " and wh.company = %s"
		params.append(company)
	query += " group by bin.item_code"
	return {row.item_code: flt(row.available_qty) for row in frappe.db.sql(query, params, as_dict=True)}


def _get_open_work_order_map(company: str | None) -> dict[str, float]:
	if not frappe.db.exists("DocType", "Work Order"):
		return {}
	query = """
		select
			production_item as item_code,
			sum(greatest(ifnull(qty, 0) - ifnull(produced_qty, 0), 0)) as open_qty
		from `tabWork Order`
		where docstatus = 1
			and ifnull(status, '') not in ('Completed', 'Closed', 'Cancelled')
	"""
	params = []
	if company:
		query += " and company = %s"
		params.append(company)
	query += " group by production_item"
	return {row.item_code: flt(row.open_qty) for row in frappe.db.sql(query, params, as_dict=True)}


def _build_net_requirement_reason(
	demand_qty: float,
	available_stock_qty: float,
	open_work_order_qty: float,
	safety_gap: float,
	overstock_qty: float,
	minimum_batch_qty: float,
	planning_qty: float,
) -> str:
	return _(
		"Demand {0} - available stock {1} - open work orders {2} + safety gap {3} - overstock suppression {4}; minimum batch {5}; planning qty {6}."
	).format(
		demand_qty,
		available_stock_qty,
		open_work_order_qty,
		safety_gap,
		overstock_qty,
		minimum_batch_qty,
		planning_qty,
	)


def _get_item_mapping_value(item_code: str, fieldname: str | None):
	if not fieldname or not frappe.db.exists("DocType", "Item") or not frappe.get_meta("Item").has_field(fieldname):
		return None
	item_code = _resolve_item_name(item_code)
	if not item_code:
		return None
	return frappe.db.get_value("Item", item_code, fieldname)


def _get_item_context(item_code: str, settings: dict[str, Any]) -> dict[str, Any]:
	item_code = _require_item_name(item_code)
	meta = frappe.get_meta("Item")
	item_doc = frappe.get_cached_doc("Item", item_code)
	food_grade = item_doc.get(settings["item_food_grade_field"]) if meta.has_field(settings["item_food_grade_field"]) else ""
	color_code = item_doc.get(settings["item_color_field"]) if meta.has_field(settings["item_color_field"]) else ""
	material_code = item_doc.get(settings["item_material_field"]) if meta.has_field(settings["item_material_field"]) else ""
	first_article = item_doc.get(settings["item_first_article_field"]) if meta.has_field(settings["item_first_article_field"]) else 0

	if (not color_code or not material_code) and frappe.db.exists("DocType", "Mold"):
		mold_row = _get_preferred_mold_row(item_code)
		if mold_row and (not color_code or not material_code):
			material_row = frappe.db.sql(
				"""
				select material_item, color_spec
				from `tabMold Default Material`
				where parent = %s and parenttype = 'Mold'
				order by idx asc
				limit 1
				""",
				(mold_row.get("mold"),),
				as_dict=True,
			)
			if material_row:
				color_code = color_code or material_row[0].get("color_spec")
				material_code = material_code or material_row[0].get("material_item")

	return {
		"food_grade": food_grade or "",
		"color_code": color_code or "",
		"material_code": material_code or "",
		"is_first_article": cint(first_article),
		"is_urgent": 0,
	}


def _get_preferred_mold_row(item_code: str) -> dict[str, Any] | None:
	if not frappe.db.exists("DocType", "Mold"):
		return None
	item_code = _resolve_item_name(item_code)
	if not item_code:
		return None
	rows = frappe.db.sql(
		"""
		select
			m.name as mold,
			m.machine_tonnage,
			m.status as mold_status,
			mp.priority,
			mp.output_qty,
			mp.cycle_time_seconds
		from `tabMold` m
		inner join `tabMold Product` mp on mp.parent = m.name and mp.parenttype = 'Mold'
		where m.docstatus = 1
			and mp.item_code = %s
			and ifnull(m.status, '') not in ('Under Maintenance', 'Under External Maintenance', 'Scrapped')
		order by mp.is_default_product desc, mp.priority asc, m.modified desc
		limit 1
		""",
		(item_code,),
		as_dict=True,
	)
	return rows[0] if rows else None


def _get_primary_demand_source(item_code: str, customer: str | None, demand_date) -> str:
	item_code = _resolve_item_name(item_code) or item_code
	row = frappe.get_all(
		"APS Demand Pool",
		filters={
			"item_code": item_code,
			"customer": customer,
			"demand_date": demand_date,
			"status": ("!=", "Cancelled"),
		},
		fields=["demand_source", "priority_score"],
		order_by="priority_score desc, modified asc",
		limit=1,
	)
	return row[0].get("demand_source") if row else ""


def _get_machine_capability_rows(plant_floor: str | None) -> list[dict[str, Any]]:
	rows = frappe.get_all(
		"APS Machine Capability",
		filters=_strip_none({"plant_floor": plant_floor, "is_active": 1}),
		fields=[
			"name",
			"workstation",
			"plant_floor",
			"machine_tonnage",
			"risk_category",
			"hourly_capacity_qty",
			"daily_capacity_qty",
			"queue_sequence",
			"machine_status",
			"max_run_hours",
		],
		order_by="queue_sequence asc, workstation asc",
	)
	if rows:
		return rows

	if not frappe.db.exists("DocType", "Workstation"):
		return []

	settings = get_settings_dict()
	workstation_meta = frappe.get_meta("Workstation")
	workstation_fields = ["name", "plant_floor", "status"]
	if settings["workstation_risk_field"] and workstation_meta.has_field(settings["workstation_risk_field"]):
		workstation_fields.append(settings["workstation_risk_field"])
	workstation_rows = frappe.get_all(
		"Workstation",
		filters=_strip_none({"plant_floor": plant_floor}),
		fields=workstation_fields,
		order_by="name asc",
	)
	fallback = []
	for idx, row in enumerate(workstation_rows, start=1):
		fallback.append(
			{
				"name": f"fallback::{row.name}",
				"workstation": row.name,
				"plant_floor": row.plant_floor,
				"machine_tonnage": _extract_tonnage_from_name(row.name),
				"risk_category": row.get(settings["workstation_risk_field"]) or "",
				"hourly_capacity_qty": 0,
				"daily_capacity_qty": 0,
				"queue_sequence": idx,
				"machine_status": row.status or "Available",
				"max_run_hours": 0,
			}
		)
	return fallback


def _build_workstation_state_map(capability_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
	state = {}
	for row in capability_rows:
		state[row["workstation"]] = {
			"next_available": get_datetime(now_datetime()),
			"last_color_code": "",
			"last_material_code": "",
			"last_mould_reference": "",
			"last_end_time": None,
			"capability": row,
		}
	return state


def _get_locked_segments(plant_floor: str | None) -> list[dict[str, Any]]:
	if not frappe.db.exists("DocType", "APS Schedule Segment"):
		return []
	return frappe.get_all(
		"APS Schedule Segment",
		filters=_strip_none(
			{
				"segment_status": ("in", LOCKED_SEGMENT_STATUSES),
				"is_locked": 1,
				"plant_floor": plant_floor,
			}
		),
		fields=[
			"name",
			"workstation",
			"start_time",
			"end_time",
			"planned_qty",
			"color_code",
			"material_code",
			"mould_reference",
		],
	)


def _apply_locked_segments_to_state(
	workstation_state: dict[str, dict[str, Any]],
	locked_segments: list[dict[str, Any]],
):
	for row in locked_segments:
		state = workstation_state.get(row.get("workstation"))
		if not state:
			continue
		end_time = get_datetime(row.get("end_time"))
		if end_time > state["next_available"]:
			state["next_available"] = end_time
			state["last_color_code"] = row.get("color_code") or ""
			state["last_material_code"] = row.get("material_code") or ""
			state["last_mould_reference"] = row.get("mould_reference") or ""
			state["last_end_time"] = end_time


def _select_machine_candidates(
	item_code: str,
	item_context: dict[str, Any],
	capability_rows: list[dict[str, Any]],
	plant_floor: str | None,
) -> list[dict[str, Any]]:
	mold_row = _get_preferred_mold_row(item_code)
	rules = frappe.get_all(
		"APS Mould-Machine Rule",
		filters=_strip_none({"item_code": item_code, "is_active": 1}),
		fields=["workstation", "priority", "preferred", "mould_reference", "min_tonnage", "max_tonnage"],
		order_by="preferred desc, priority asc",
	)
	rule_map = {row.workstation: row for row in rules}
	candidates = []
	for capability in capability_rows:
		if plant_floor and capability.get("plant_floor") and capability.get("plant_floor") != plant_floor:
			continue
		if capability.get("machine_status") in ("Unavailable", "Fault", "Maintenance", "Disabled"):
			continue
		if mold_row and capability.get("machine_tonnage") and mold_row.get("machine_tonnage"):
			if flt(capability.get("machine_tonnage")) < flt(mold_row.get("machine_tonnage")):
				continue
		rule = rule_map.get(capability.get("workstation"))
		if rule and rule.get("min_tonnage") and capability.get("machine_tonnage") and flt(capability.get("machine_tonnage")) < flt(rule.get("min_tonnage")):
			continue
		if rule and rule.get("max_tonnage") and capability.get("machine_tonnage") and flt(capability.get("machine_tonnage")) > flt(rule.get("max_tonnage")):
			continue
		candidate = dict(capability)
		candidate["preferred"] = cint(rule.get("preferred")) if rule else 0
		candidate["priority"] = cint(rule.get("priority")) if rule else cint(capability.get("queue_sequence") or 999)
		candidate["mould_reference"] = (rule.get("mould_reference") if rule else None) or (mold_row.get("mold") if mold_row else "")
		candidate["cycle_time_seconds"] = flt(mold_row.get("cycle_time_seconds")) if mold_row else 0
		candidate["output_qty"] = flt(mold_row.get("output_qty")) if mold_row else 0
		candidates.append(candidate)
	return sorted(candidates, key=lambda row: (-cint(row.get("preferred")), cint(row.get("priority") or 999), row.get("workstation")))


def _choose_best_slot(
	item_code: str,
	item_context: dict[str, Any],
	qty: float,
	demand_date,
	horizon_start,
	horizon_end,
	workstation_state: dict[str, dict[str, Any]],
	candidates: list[dict[str, Any]],
	settings: dict[str, Any],
) -> dict[str, Any]:
	if not candidates:
		return {
			"scheduled_qty": 0,
			"unscheduled_qty": qty,
			"result_status": "Blocked",
			"risk_status": "Blocked",
			"segments": [],
			"exceptions": [
				{
					"severity": "Critical",
					"exception_type": "Machine Unavailable",
					"message": _("No eligible APS machine capability rows were found for {0}.").format(item_code),
					"resolution_hint": _("Maintain APS Machine Capability or relax mould-machine constraints."),
					"is_blocking": 1,
				}
			],
		}

	best = None
	exceptions = []
	for candidate in candidates:
		state = workstation_state.get(candidate.get("workstation")) or {}
		start_time = max(get_datetime(horizon_start), get_datetime(state.get("next_available") or horizon_start))
		setup_minutes, candidate_exceptions = _estimate_setup_penalty(
			candidate=candidate,
			state=state,
			item_context=item_context,
			settings=settings,
		)
		if _has_fda_conflict(item_context, candidate):
			candidate_exceptions.append(
				{
					"severity": "Critical",
					"exception_type": "FDA Conflict",
					"message": _("Workstation {0} risk category {1} cannot run FDA requirement for {2}.").format(
						candidate.get("workstation"),
						candidate.get("risk_category") or "",
						item_code,
					),
					"workstation": candidate.get("workstation"),
					"resolution_hint": _("Select an FDA-capable workstation or change the risk mapping."),
					"is_blocking": 1,
				}
			)
			exceptions.extend(candidate_exceptions)
			continue

		duration_hours = _estimate_run_hours(qty=qty, candidate=candidate, settings=settings)
		start_time = start_time + timedelta(minutes=setup_minutes)
		end_time = start_time + timedelta(hours=duration_hours)
		scheduled_qty = qty
		unscheduled_qty = 0
		risk_status = "Normal"
		result_status = "Planned"

		if end_time > get_datetime(demand_date):
			risk_status = "Attention"
		if end_time > get_datetime(horizon_end):
			available_hours = max((get_datetime(horizon_end) - start_time).total_seconds() / 3600, 0)
			hourly_capacity = max(duration_hours and (qty / duration_hours), 1)
			scheduled_qty = min(qty, flt(available_hours * hourly_capacity, 0))
			unscheduled_qty = max(qty - scheduled_qty, 0)
			end_time = get_datetime(horizon_end)
			risk_status = "Critical"
			result_status = "Risk"
			candidate_exceptions.append(
				{
					"severity": "Critical",
					"exception_type": "Late Delivery Risk",
					"message": _("Only {0} of {1} can be scheduled before the current horizon for {2}.").format(
						scheduled_qty, qty, item_code
					),
					"workstation": candidate.get("workstation"),
					"resolution_hint": _("Extend the horizon, rebalance machines or split the requirement."),
					"is_blocking": 0,
				}
			)

		score = (
			end_time,
			setup_minutes,
			-cint(candidate.get("preferred")),
			cint(candidate.get("priority") or 999),
		)
		proposal = {
			"score": score,
			"scheduled_qty": scheduled_qty,
			"unscheduled_qty": unscheduled_qty,
			"result_status": result_status,
			"risk_status": risk_status,
			"segments": [
				{
					"workstation": candidate.get("workstation"),
					"plant_floor": candidate.get("plant_floor"),
					"start_time": start_time,
					"end_time": end_time,
					"planned_qty": scheduled_qty,
					"sequence_no": 1,
					"setup_minutes": setup_minutes,
					"changeover_minutes": setup_minutes,
					"mould_reference": candidate.get("mould_reference"),
					"risk_flags": "\n".join(error.get("exception_type") for error in candidate_exceptions),
					"segment_status": result_status,
					"color_code": item_context.get("color_code"),
					"material_code": item_context.get("material_code"),
					"is_locked": 0,
					"is_manual": 0,
				}
			],
			"exceptions": candidate_exceptions,
		}
		if best is None or proposal["score"] < best["score"]:
			best = proposal

	if not best:
		return {
			"scheduled_qty": 0,
			"unscheduled_qty": qty,
			"result_status": "Blocked",
			"risk_status": "Blocked",
			"segments": [],
			"exceptions": exceptions,
		}

	segment = best["segments"][0]
	state = workstation_state.get(segment["workstation"])
	if state:
		state["next_available"] = get_datetime(segment["end_time"])
		state["last_color_code"] = segment.get("color_code") or ""
		state["last_material_code"] = segment.get("material_code") or ""
		state["last_mould_reference"] = segment.get("mould_reference") or ""
		state["last_end_time"] = get_datetime(segment["end_time"])

	best.pop("score", None)
	return best


def _estimate_setup_penalty(candidate, state, item_context, settings):
	setup_minutes = flt(settings["default_setup_minutes"])
	exceptions = []
	transition_rule = _get_color_transition_rule(state.get("last_color_code"), item_context.get("color_code"))
	if transition_rule:
		setup_minutes = max(setup_minutes, flt(transition_rule.get("setup_minutes") or setup_minutes))
		if transition_rule.get("penalty_score"):
			exceptions.append(
				{
					"severity": "Warning",
					"exception_type": "Color Transition",
					"message": _("Color transition {0} -> {1} has penalty {2}.").format(
						state.get("last_color_code") or "-",
						item_context.get("color_code") or "-",
						transition_rule.get("penalty_score"),
					),
					"workstation": candidate.get("workstation"),
					"resolution_hint": _("Group similar colors to reduce changeover cost."),
					"is_blocking": 0,
				}
			)

	if state.get("last_material_code") and state.get("last_material_code") != item_context.get("material_code"):
		setup_minutes += 15
		exceptions.append(
			{
				"severity": "Warning",
				"exception_type": "Material Changeover",
				"message": _("Material changeover is required on workstation {0}.").format(candidate.get("workstation")),
				"workstation": candidate.get("workstation"),
				"resolution_hint": _("Group the same material family where possible."),
				"is_blocking": 0,
			}
		)

	if cint(item_context.get("is_first_article")):
		setup_minutes += flt(settings["default_first_article_minutes"])
		exceptions.append(
			{
				"severity": "Warning",
				"exception_type": "First Article Confirmation",
				"message": _("First article confirmation time was added for {0}.").format(candidate.get("workstation")),
				"workstation": candidate.get("workstation"),
				"resolution_hint": _("Keep QA review slots visible in the short horizon."),
				"is_blocking": 0,
			}
		)

	if state.get("last_mould_reference") and candidate.get("mould_reference") and state.get("last_mould_reference") != candidate.get("mould_reference"):
		setup_minutes += 30

	return setup_minutes, exceptions


def _estimate_run_hours(qty: float, candidate: dict[str, Any], settings: dict[str, Any]) -> float:
	hourly_capacity_qty = flt(candidate.get("hourly_capacity_qty"))
	if hourly_capacity_qty <= 0 and flt(candidate.get("daily_capacity_qty")) > 0:
		hourly_capacity_qty = flt(candidate.get("daily_capacity_qty")) / 24
	if hourly_capacity_qty <= 0 and flt(candidate.get("cycle_time_seconds")) > 0 and flt(candidate.get("output_qty")) > 0:
		hourly_capacity_qty = (3600 / flt(candidate.get("cycle_time_seconds"))) * flt(candidate.get("output_qty"))
	if hourly_capacity_qty <= 0:
		hourly_capacity_qty = flt(settings["default_hourly_capacity_qty"])
	return max(flt(qty) / max(hourly_capacity_qty, 1), 0.25)


def _has_fda_conflict(item_context: dict[str, Any], candidate: dict[str, Any]) -> bool:
	food_grade_value = item_context.get("food_grade")
	food_grade = str(food_grade_value or "").upper()
	risk_category = (candidate.get("risk_category") or "").strip()
	requires_fda = cint(food_grade_value) or food_grade in ("YES", "TRUE", "1") or "FDA" in food_grade
	return bool(requires_fda) and risk_category == BLOCKING_WORKSTATION_RISK


def _get_color_transition_rule(from_color: str | None, to_color: str | None) -> dict[str, Any] | None:
	if not from_color or not to_color:
		return None
	rows = frappe.get_all(
		"APS Color Transition Rule",
		filters={"from_color": from_color, "to_color": to_color, "is_active": 1},
		fields=["penalty_score", "setup_minutes"],
		limit=1,
	)
	return rows[0] if rows else None


def _create_exception(
	planning_run: str,
	severity: str,
	exception_type: str,
	message: str,
	item_code: str | None = None,
	customer: str | None = None,
	workstation: str | None = None,
	source_doctype: str | None = None,
	source_name: str | None = None,
	resolution_hint: str | None = None,
	is_blocking: int = 0,
):
	return frappe.get_doc(
		{
			"doctype": "APS Exception Log",
			"planning_run": planning_run,
			"severity": severity,
			"exception_type": exception_type,
			"message": message,
			"item_code": item_code,
			"customer": customer,
			"workstation": workstation,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"resolution_hint": resolution_hint,
			"is_blocking": is_blocking,
			"status": "Open",
		}
	).insert(ignore_permissions=True)


def _sync_delivery_plan(run_doc) -> str | None:
	if not frappe.db.exists("DocType", "Delivery Plan"):
		return None

	result_rows = frappe.get_all(
		"APS Schedule Result",
		filters={"planning_run": run_doc.name, "scheduled_qty": (">", 0)},
		fields=["customer", "item_code", "requested_date", "scheduled_qty"],
		order_by="requested_date asc, item_code asc",
	)
	if not result_rows:
		return None

	customer = next((row.customer for row in result_rows if row.customer), None)
	if not customer:
		return None

	dp = frappe.get_doc(
		{
			"doctype": "Delivery Plan",
			"customer": customer,
			"company": run_doc.company,
			"delivery_date": getdate(run_doc.horizon_start),
			"arrival_date": getdate(run_doc.horizon_start),
			"remark": _("Generated by Injection APS run {0}").format(run_doc.name),
			"custom_aps_version": run_doc.name,
			"custom_aps_source": "APS Planning Run",
			"item_qties": [
				{
					"item_code": row.item_code,
					"planned_delivery_qty": row.scheduled_qty,
					"staging_qty": row.scheduled_qty,
					"required_arrival_date": row.requested_date,
				}
				for row in result_rows
			],
		}
	).insert(ignore_permissions=True)
	return dp.name


def _sync_existing_work_orders_to_scheduling(run_doc) -> str | None:
	if not frappe.db.exists("DocType", "Work Order Scheduling"):
		return None

	result_rows = frappe.get_all(
		"APS Schedule Result",
		filters={"planning_run": run_doc.name, "scheduled_qty": (">", 0)},
		fields=["name", "item_code"],
	)
	items = []
	for result in result_rows:
		work_orders = frappe.get_all(
			"Work Order",
			filters={
				"production_item": result.item_code,
				"docstatus": 1,
				"status": ("not in", ["Completed", "Closed", "Cancelled"]),
			},
			fields=["name", "qty", "produced_qty"],
			order_by="planned_start_date asc, creation asc",
			limit=1,
		)
		if not work_orders:
			continue
		segments = frappe.get_all(
			"APS Schedule Segment",
			filters={"parent": result.name, "parenttype": "APS Schedule Result"},
			fields=["workstation", "start_time", "end_time", "planned_qty"],
			limit=1,
			order_by="sequence_no asc, idx asc",
		)
		if not segments:
			continue
		segment = segments[0]
		items.append(
			{
				"work_order": work_orders[0].name,
				"scheduling_qty": segment.planned_qty,
				"workstation": segment.workstation,
				"planned_start_date": segment.start_time,
				"planned_end_date": segment.end_time,
				"remarks": result.name,
			}
		)

	if not items:
		return None

	scheduling = frappe.get_doc(
		{
			"doctype": "Work Order Scheduling",
			"posting_date": today(),
			"company": run_doc.company,
			"plant_floor": run_doc.plant_floor,
			"purpose": "Manufacture",
			"status": "",
			"custom_aps_run": run_doc.name,
			"custom_aps_freeze_state": "Open",
			"custom_aps_approval_state": "Approved",
			"scheduling_items": items,
		}
	).insert(ignore_permissions=True)
	return scheduling.name


def _ensure_released_work_order(run_doc, result: dict[str, Any], segment: dict[str, Any], settings: dict[str, Any]) -> str | None:
	item_code = _resolve_item_name(result["item_code"]) or result["item_code"]
	existing = frappe.get_all(
		"Work Order",
		filters={
			"production_item": item_code,
			"custom_aps_run": run_doc.name,
			"docstatus": 1,
			"status": ("not in", ["Completed", "Closed", "Cancelled"]),
		},
		fields=["name"],
		limit=1,
	)
	if existing:
		return existing[0].name

	bom_no = frappe.db.get_value("Item", item_code, "default_bom")
	if not bom_no:
		bom_no = frappe.db.get_value("BOM", {"item": item_code, "is_default": 1, "is_active": 1}, "name")
	if not bom_no:
		_create_exception(
			planning_run=run_doc.name,
			severity="Critical",
			exception_type="Missing BOM",
			message=_("No BOM was found for {0}, so APS could not release a work order.").format(item_code),
			item_code=item_code,
			customer=result.get("customer"),
			source_doctype="APS Schedule Result",
			source_name=result["name"],
			resolution_hint=_("Set a default BOM before attempting release."),
			is_blocking=1,
		)
		return None

	plant_floor_doc = None
	if run_doc.plant_floor and frappe.db.exists("DocType", "Plant Floor"):
		plant_floor_doc = frappe.get_doc("Plant Floor", run_doc.plant_floor)

	work_order = frappe.get_doc(
		{
			"doctype": "Work Order",
			"production_item": item_code,
			"bom_no": bom_no,
			"qty": segment["planned_qty"],
			"company": run_doc.company,
			"planned_start_date": segment["start_time"],
			"planned_end_date": segment["end_time"],
			"wip_warehouse": _get_doc_field_value(
				plant_floor_doc, settings.get("plant_floor_wip_warehouse_field")
			),
			"source_warehouse": _get_doc_field_value(
				plant_floor_doc, settings.get("plant_floor_source_warehouse_field")
			),
			"fg_warehouse": _get_doc_field_value(
				plant_floor_doc, settings.get("plant_floor_fg_warehouse_field")
			),
			"scrap_warehouse": _get_doc_field_value(
				plant_floor_doc, settings.get("plant_floor_scrap_warehouse_field")
			),
			"custom_aps_run": run_doc.name,
			"custom_aps_source": result.get("demand_source") or "APS Planning Run",
			"custom_aps_required_delivery_date": result.get("requested_date"),
			"custom_aps_is_urgent": result.get("is_urgent"),
			"custom_aps_release_status": "Released",
			"custom_aps_locked_for_reschedule": 1,
			"custom_aps_schedule_reference": result["name"],
		}
	)
	work_order.flags.ignore_mandatory = True
	work_order.insert(ignore_permissions=True)
	work_order.submit()
	return work_order.name


def _create_release_work_order_scheduling(run_doc, release_batch: str, scheduling_items: list[dict[str, Any]]) -> str | None:
	if not scheduling_items or not frappe.db.exists("DocType", "Work Order Scheduling"):
		return None
	doc = frappe.get_doc(
		{
			"doctype": "Work Order Scheduling",
			"posting_date": today(),
			"company": run_doc.company,
			"plant_floor": run_doc.plant_floor,
			"purpose": "Manufacture",
			"status": "",
			"remarks": _("APS Release Batch {0}").format(release_batch),
			"custom_aps_run": run_doc.name,
			"custom_aps_freeze_state": "Locked",
			"custom_aps_approval_state": "Approved",
			"scheduling_items": scheduling_items,
		}
	).insert(ignore_permissions=True)
	return doc.name


def _extract_tonnage_from_name(workstation_name: str | None) -> float:
	if not workstation_name:
		return 0
	digits = []
	for token in str(workstation_name).replace("/", " ").replace("_", " ").split():
		filtered = "".join(ch for ch in token if ch.isdigit())
		if filtered:
			digits.append(filtered)
	if not digits:
		return 0
	return flt(max(digits, key=len))


def _get_records_with_any_field_set(doctype: str, fieldnames: list[str]) -> list[str]:
	meta = frappe.get_meta(doctype)
	available = [fieldname for fieldname in fieldnames if meta.has_field(fieldname)]
	if not available:
		return []

	conditions = []
	for fieldname in available:
		field = meta.get_field(fieldname)
		if field.fieldtype in ("Check", "Int", "Float", "Currency", "Percent"):
			conditions.append(f"ifnull(`{fieldname}`, 0) != 0")
		else:
			conditions.append(f"ifnull(`{fieldname}`, '') != ''")

	query = f"select name from `tab{doctype}` where {' or '.join(conditions)}"
	return [row.name for row in frappe.db.sql(query, as_dict=True)]


def _get_doc_field_value(doc, fieldname: str | None):
	if not doc or not fieldname:
		return None
	return doc.get(fieldname) if doc.meta.has_field(fieldname) else None


def _delete_system_generated_rows(doctype: str, company: str | None = None):
	if not frappe.db.exists("DocType", doctype):
		return
	filters = {"is_system_generated": 1}
	if company and frappe.get_meta(doctype).has_field("company"):
		filters["company"] = company
	for name in frappe.get_all(doctype, filters=filters, pluck="name"):
		frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)


def _strip_none(values: dict[str, Any]) -> dict[str, Any]:
	return {key: value for key, value in values.items() if value not in (None, "")}
