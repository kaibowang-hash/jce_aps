frappe.pages["aps-net-requirement-workbench"].on_page_load = function (wrapper) {
	frappe.require("/assets/injection_aps/js/injection_aps_shared.js", () => {
		if (!wrapper.injection_aps_controller) {
			wrapper.injection_aps_controller = new InjectionAPSNetRequirementWorkbench(wrapper);
		}
		wrapper.injection_aps_controller.refresh();
	});
};

frappe.pages["aps-net-requirement-workbench"].on_page_show = function (wrapper) {
	wrapper.injection_aps_controller?.refresh();
};

class InjectionAPSNetRequirementWorkbench {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Net Requirement Workbench"),
			single_column: true,
		});
		this.companyField = this.page.add_field({
			fieldtype: "Link",
			fieldname: "company",
			options: "Company",
			label: __("Company"),
			default: frappe.defaults.get_user_default("Company"),
			change: () => this.refresh(),
		});
		this.itemField = this.page.add_field({
			fieldtype: "Link",
			fieldname: "item_code",
			options: "Item",
			label: __("Item"),
			change: () => this.refresh(),
		});
		this.page.set_primary_action(__("Rebuild Demand Pool"), () => this.rebuildDemandPool());
		this.page.set_secondary_action(__("Recalculate Net Requirements"), () => this.rebuildNetRequirements());

		this.page.main.html(`
			<div class="ia-page">
				<div class="ia-banner">
					<h3>${__("Net Requirement Workbench")}</h3>
					<p>${__("Demand pool, inventory, WIP, safety stock and minimum batch uplift are all visible here before a planning run starts.")}</p>
				</div>
				<div class="ia-card-grid ia-summary"></div>
				<div class="ia-feedback"></div>
				<div class="ia-panel">
					<div class="ia-table-target"></div>
				</div>
			</div>
		`);
		this.summary = this.page.main.find(".ia-summary")[0];
		this.feedback = this.page.main.find(".ia-feedback")[0];
		this.table = this.page.main.find(".ia-table-target")[0];
	}

	async refresh() {
		injection_aps.ui.ensure_styles();
		injection_aps.ui.set_feedback(this.feedback, __("Loading net requirements..."));
		try {
			const data = await frappe.xcall("injection_aps.api.app.get_net_requirement_page_data", {
				company: this.companyField.get_value() || undefined,
				item_code: this.itemField.get_value() || undefined,
			});
			injection_aps.ui.render_cards(this.summary, [
				{ label: __("Rows"), value: data.summary.rows || 0 },
				{ label: __("Net Qty"), value: frappe.format(data.summary.net_requirement_qty || 0, { fieldtype: "Float" }) },
				{ label: __("Planning Qty"), value: frappe.format(data.summary.planning_qty || 0, { fieldtype: "Float" }), note: __("Includes minimum batch uplift") },
			]);
			injection_aps.ui.render_table(
				this.table,
				[
					{ label: __("Item"), fieldname: "item_code" },
					{ label: __("Customer"), fieldname: "customer" },
					{ label: __("Demand Date"), fieldname: "demand_date" },
					{ label: __("Demand"), fieldname: "demand_qty" },
					{ label: __("Stock"), fieldname: "available_stock_qty" },
					{ label: __("Open WO"), fieldname: "open_work_order_qty" },
					{ label: __("Safety Gap"), fieldname: "safety_stock_gap_qty" },
					{ label: __("Min Batch"), fieldname: "minimum_batch_qty" },
					{ label: __("Planning Qty"), fieldname: "planning_qty" },
					{ label: __("Net Qty"), fieldname: "net_requirement_qty" },
					{ label: __("Reason"), fieldname: "reason_text" },
				],
				data.rows || [],
				(column, value) => {
					if (["demand_qty", "available_stock_qty", "open_work_order_qty", "safety_stock_gap_qty", "minimum_batch_qty", "planning_qty", "net_requirement_qty"].includes(column.fieldname)) {
						return frappe.format(value || 0, { fieldtype: "Float" });
					}
					if (column.fieldname === "demand_date") {
						return injection_aps.ui.format_date(value);
					}
					return frappe.utils.escape_html(value == null ? "" : String(value));
				}
			);
			injection_aps.ui.set_feedback(this.feedback, __("Net requirement workbench refreshed."));
		} catch (error) {
			console.error(error);
			injection_aps.ui.set_feedback(this.feedback, __("Failed to load net requirements."), "error");
		}
	}

	async rebuildDemandPool() {
		const result = await frappe.xcall("injection_aps.api.app.rebuild_demand_pool", {
			company: this.companyField.get_value() || undefined,
		});
		showApsWarnings(result, __("Demand Pool Warnings"));
		frappe.show_alert({ message: __("Demand pool rebuilt."), indicator: "green" });
		await this.rebuildNetRequirements();
	}

	async rebuildNetRequirements() {
		const result = await frappe.xcall("injection_aps.api.app.rebuild_net_requirements", {
			company: this.companyField.get_value() || undefined,
		});
		showApsWarnings(result, __("Net Requirement Warnings"));
		frappe.show_alert({ message: __("Net requirements recalculated."), indicator: "green" });
		await this.refresh();
	}
}

function showApsWarnings(result, title) {
	if (!result || !result.warning_count) {
		return;
	}

	const warnings = result.warnings || [];
	const extraCount = Math.max((result.warning_count || 0) - warnings.length, 0);
	const rows = warnings
		.map((row) => `<li>${frappe.utils.escape_html(row.message || "")}</li>`)
		.join("");

	frappe.msgprint({
		title: title || __("APS Warnings"),
		message: `
			<div>${__("Skipped Rows")}: <b>${result.skipped_rows || result.warning_count || 0}</b></div>
			<ul style="margin-top:8px; padding-left:18px;">${rows}</ul>
			${extraCount ? `<div class="text-muted" style="margin-top:8px;">${__("Additional warnings")}: ${extraCount}</div>` : ""}
		`,
		wide: true,
	});
}
