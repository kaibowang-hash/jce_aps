frappe.pages["aps-release-center"].on_page_load = function (wrapper) {
	frappe.require("/assets/injection_aps/js/injection_aps_shared.js", () => {
		if (!wrapper.injection_aps_controller) {
			wrapper.injection_aps_controller = new InjectionAPSReleaseCenter(wrapper);
		}
		wrapper.injection_aps_controller.refresh();
	});
};

frappe.pages["aps-release-center"].on_page_show = function (wrapper) {
	wrapper.injection_aps_controller?.refresh();
};

class InjectionAPSReleaseCenter {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Release & Exception Center"),
			single_column: true,
		});
		this.runField = this.page.add_field({
			fieldtype: "Link",
			fieldname: "run_name",
			options: "APS Planning Run",
			label: __("Planning Run"),
			change: () => this.refresh(),
		});
		this.page.set_primary_action(__("Sync Approved Run"), () => this.syncRun());
		this.page.set_secondary_action(__("Release Window"), () => this.releaseRun());
		this.page.add_action_item(__("Rebuild Exceptions"), () => this.rebuildExceptions());
		this.page.add_action_item(__("Impact Analysis"), () => this.openImpactDialog());

		this.page.main.html(`
			<div class="ia-page">
				<div class="ia-banner">
					<h3>${__("Release & Exception Center")}</h3>
					<p>${__("Release only the near-term window, keep the downstream execution layer intact, and make exception review visible for PMC, Sales and Warehouse.")}</p>
				</div>
				<div class="ia-card-grid ia-summary"></div>
				<div class="ia-feedback"></div>
				<div class="ia-panel">
					<h4>${__("Release Batches")}</h4>
					<div class="ia-release-table" style="margin-top: 12px;"></div>
				</div>
				<div class="ia-panel">
					<h4>${__("Open Exceptions")}</h4>
					<div class="ia-exception-table" style="margin-top: 12px;"></div>
				</div>
				<div class="ia-panel">
					<h4>${__("Latest Impact Analysis")}</h4>
					<div class="ia-impact-summary ia-card-grid" style="margin-top: 10px;"></div>
					<div class="ia-impact-table" style="margin-top: 12px;"></div>
				</div>
			</div>
		`);
		this.summary = this.page.main.find(".ia-summary")[0];
		this.feedback = this.page.main.find(".ia-feedback")[0];
		this.releaseTable = this.page.main.find(".ia-release-table")[0];
		this.exceptionTable = this.page.main.find(".ia-exception-table")[0];
		this.impactSummary = this.page.main.find(".ia-impact-summary")[0];
		this.impactTable = this.page.main.find(".ia-impact-table")[0];
		this.lastImpact = null;
	}

	async refresh() {
		injection_aps.ui.ensure_styles();
		injection_aps.ui.set_feedback(this.feedback, __("Loading release batches and exceptions..."));
		try {
			const data = await frappe.xcall("injection_aps.api.app.get_release_center_data", {
				run_name: this.runField.get_value() || undefined,
			});
			const exceptions = data.exceptions || [];
			const blocking = exceptions.filter((row) => Number(row.is_blocking || 0)).length;
			injection_aps.ui.render_cards(this.summary, [
				{ label: __("Release Batches"), value: (data.release_batches || []).length },
				{ label: __("Open Exceptions"), value: exceptions.length },
				{ label: __("Blocking"), value: blocking, note: __("Highest-priority exceptions") },
			]);
			this.renderReleaseTable(data.release_batches || []);
			this.renderExceptionTable(exceptions);
			this.renderImpact();
			injection_aps.ui.set_feedback(this.feedback, __("Release center refreshed."));
		} catch (error) {
			console.error(error);
			injection_aps.ui.set_feedback(this.feedback, __("Failed to load release center."), "error");
		}
	}

	renderReleaseTable(rows) {
		injection_aps.ui.render_table(
			this.releaseTable,
			[
				{ label: __("Batch"), fieldname: "name" },
				{ label: __("Run"), fieldname: "planning_run" },
				{ label: __("Status"), fieldname: "status" },
				{ label: __("From"), fieldname: "release_from_date" },
				{ label: __("To"), fieldname: "release_to_date" },
				{ label: __("Work Orders"), fieldname: "generated_work_orders" },
				{ label: __("Scheduling"), fieldname: "work_order_scheduling" },
			],
			rows,
			(column, value) => {
				if (column.fieldname === "planning_run" && value) {
					return injection_aps.ui.route_link(value, `aps-planning-run/${encodeURIComponent(value)}`);
				}
				if (column.fieldname === "status") {
					return injection_aps.ui.pill(injection_aps.ui.translate(value), value === "Released" ? "green" : "orange");
				}
				if (["release_from_date", "release_to_date"].includes(column.fieldname)) {
					return injection_aps.ui.format_date(value);
				}
				return frappe.utils.escape_html(value == null ? "" : String(value));
			}
		);
	}

	renderExceptionTable(rows) {
		injection_aps.ui.render_table(
			this.exceptionTable,
			[
				{ label: __("Severity"), fieldname: "severity" },
				{ label: __("Type"), fieldname: "exception_type" },
				{ label: __("Item"), fieldname: "item_code" },
				{ label: __("Customer"), fieldname: "customer" },
				{ label: __("Machine / Workstation"), fieldname: "workstation" },
				{ label: __("Message"), fieldname: "message" },
			],
			rows,
			(column, value, row) => {
				if (column.fieldname === "severity") {
					const tone = row.is_blocking ? "red" : value === "Critical" ? "orange" : "blue";
					return injection_aps.ui.pill(injection_aps.ui.translate(value), tone);
				}
				if (column.fieldname === "exception_type") {
					return frappe.utils.escape_html(injection_aps.ui.translate(value));
				}
				return frappe.utils.escape_html(value == null ? "" : String(value));
			}
		);
	}

	renderImpact() {
		if (!this.lastImpact) {
			injection_aps.ui.render_cards(this.impactSummary, [
				{ label: __("Impact"), value: __("None"), note: __("Run insert-order analysis to see displaced segments and changeover cost.") },
			]);
			injection_aps.ui.render_table(this.impactTable, [{ label: __("Info"), fieldname: "message" }], []);
			return;
		}

		injection_aps.ui.render_cards(this.impactSummary, [
			{ label: __("Scheduled Qty"), value: frappe.format(this.lastImpact.scheduled_qty || 0, { fieldtype: "Float" }) },
			{ label: __("Unscheduled Qty"), value: frappe.format(this.lastImpact.unscheduled_qty || 0, { fieldtype: "Float" }) },
			{ label: __("Changeover Minutes"), value: frappe.format(this.lastImpact.changeover_minutes || 0, { fieldtype: "Float" }) },
			{ label: __("Impacted Customers"), value: (this.lastImpact.impacted_customers || []).join(", ") || "-" },
		]);
		injection_aps.ui.render_table(
			this.impactTable,
			[
				{ label: __("Result"), fieldname: "result_name" },
				{ label: __("Item"), fieldname: "item_code" },
				{ label: __("Customer"), fieldname: "customer" },
				{ label: __("Machine / Workstation"), fieldname: "workstation" },
				{ label: __("Start"), fieldname: "start_time" },
				{ label: __("End"), fieldname: "end_time" },
				{ label: __("Qty"), fieldname: "planned_qty" },
			],
			this.lastImpact.impacted_segments || [],
			(column, value) => {
				if (["start_time", "end_time"].includes(column.fieldname)) {
					return injection_aps.ui.format_datetime(value);
				}
				if (column.fieldname === "planned_qty") {
					return frappe.format(value || 0, { fieldtype: "Float" });
				}
				return frappe.utils.escape_html(value == null ? "" : String(value));
			}
		);
	}

	getSelectedRun() {
		const runName = this.runField.get_value();
		if (!runName) {
			frappe.show_alert({ message: __("Choose a planning run first."), indicator: "orange" });
			return null;
		}
		return runName;
	}

	async syncRun() {
		const runName = this.getSelectedRun();
		if (!runName) {
			return;
		}
		await frappe.xcall("injection_aps.api.app.sync_planning_run_to_execution", { run_name: runName });
		frappe.show_alert({ message: __("Run synced to Delivery Plan / Work Order Scheduling."), indicator: "green" });
		await this.refresh();
	}

	async releaseRun() {
		const runName = this.getSelectedRun();
		if (!runName) {
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Release Short-Term Window"),
			fields: [{ fieldname: "release_horizon_days", fieldtype: "Int", label: __("Release Horizon Days"), default: 3, reqd: 1 }],
			primary_action_label: __("Release"),
			primary_action: async (values) => {
				await frappe.xcall("injection_aps.api.app.release_planning_run", {
					run_name: runName,
					release_horizon_days: values.release_horizon_days,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Work order release completed."), indicator: "green" });
				await this.refresh();
			},
		});
		dialog.show();
	}

	async rebuildExceptions() {
		const runName = this.getSelectedRun();
		if (!runName) {
			return;
		}
		await frappe.xcall("injection_aps.api.app.rebuild_exceptions", { run_name: runName });
		frappe.show_alert({ message: __("Exceptions recalculated."), indicator: "green" });
		await this.refresh();
	}

	openImpactDialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Insert Order Impact Analysis"),
			fields: [
				{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1, default: frappe.defaults.get_user_default("Company") },
				{ fieldname: "plant_floor", fieldtype: "Link", options: "Plant Floor", label: __("Plant Floor"), reqd: 1 },
				{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), reqd: 1 },
				{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), reqd: 1 },
				{ fieldname: "required_date", fieldtype: "Date", label: __("Required Date"), reqd: 1 },
				{ fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer") },
			],
			primary_action_label: __("Analyze"),
			primary_action: async (values) => {
				this.lastImpact = await frappe.xcall("injection_aps.api.app.analyze_insert_order_impact", values);
				dialog.hide();
				this.renderImpact();
				frappe.show_alert({ message: __("Impact analysis completed."), indicator: "green" });
			},
		});
		dialog.show();
	}
}
