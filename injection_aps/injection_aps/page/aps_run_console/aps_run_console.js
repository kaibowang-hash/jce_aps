frappe.pages["aps-run-console"].on_page_load = function (wrapper) {
	frappe.require("/assets/injection_aps/js/injection_aps_shared.js", () => {
		if (!wrapper.injection_aps_controller) {
			wrapper.injection_aps_controller = new InjectionAPSRunConsole(wrapper);
		}
		wrapper.injection_aps_controller.refresh();
	});
};

frappe.pages["aps-run-console"].on_page_show = function (wrapper) {
	wrapper.injection_aps_controller?.refresh();
};

class InjectionAPSRunConsole {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("APS Run Console"),
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
		this.plantFloorField = this.page.add_field({
			fieldtype: "Link",
			fieldname: "plant_floor",
			options: "Plant Floor",
			label: __("Plant Floor"),
			change: () => this.refresh(),
		});
		this.page.set_primary_action(__("Run Trial"), () => this.openRunDialog());
		this.page.add_action_item(__("Planning Runs"), () => frappe.set_route("List", "APS Planning Run"));

		this.page.main.html(`
			<div class="ia-page">
				<div class="ia-banner">
					<h3>${__("APS Run Console")}</h3>
					<p>${__("Run a planning pass, review the proposed load, then approve and release from the form when the sequence is stable.")}</p>
				</div>
				<div class="ia-feedback"></div>
				<div class="ia-panel">
					<div class="ia-run-table"></div>
				</div>
			</div>
		`);
		this.feedback = this.page.main.find(".ia-feedback")[0];
		this.table = this.page.main.find(".ia-run-table")[0];
	}

	async refresh() {
		injection_aps.ui.ensure_styles();
		injection_aps.ui.set_feedback(this.feedback, __("Loading planning runs..."));
		try {
			const data = await frappe.xcall("injection_aps.api.app.get_run_console_data", {
				company: this.companyField.get_value() || undefined,
				plant_floor: this.plantFloorField.get_value() || undefined,
			});
			injection_aps.ui.render_table(
				this.table,
				[
					{ label: __("Run"), fieldname: "name" },
					{ label: __("Company"), fieldname: "company" },
					{ label: __("Plant Floor"), fieldname: "plant_floor" },
					{ label: __("Planning Date"), fieldname: "planning_date" },
					{ label: __("Status"), fieldname: "status" },
					{ label: __("Approval"), fieldname: "approval_state" },
					{ label: __("Plan Qty"), fieldname: "total_net_requirement_qty" },
					{ label: __("Scheduled"), fieldname: "total_scheduled_qty" },
					{ label: __("Unscheduled"), fieldname: "total_unscheduled_qty" },
					{ label: __("Exceptions"), fieldname: "exception_count" },
				],
				data.runs || [],
				(column, value, row) => {
					if (column.fieldname === "name") {
						return injection_aps.ui.route_link(value, `aps-planning-run/${encodeURIComponent(value)}`);
					}
					if (column.fieldname === "status") {
						const tone = ["Approved", "Synced", "Released", "Partially Released"].includes(value)
							? "green"
							: value === "Planned"
								? "orange"
								: "blue";
						return injection_aps.ui.pill(injection_aps.ui.translate(value), tone);
					}
					if (column.fieldname === "approval_state") {
						return injection_aps.ui.pill(injection_aps.ui.translate(value), value === "Approved" ? "green" : "orange");
					}
					if (["total_net_requirement_qty", "total_scheduled_qty", "total_unscheduled_qty"].includes(column.fieldname)) {
						return frappe.format(value || 0, { fieldtype: "Float" });
					}
					if (column.fieldname === "planning_date") {
						return injection_aps.ui.format_date(value);
					}
					return frappe.utils.escape_html(value == null ? "" : String(value));
				}
			);
			injection_aps.ui.set_feedback(this.feedback, __("Run console refreshed."));
		} catch (error) {
			console.error(error);
			injection_aps.ui.set_feedback(this.feedback, __("Failed to load planning runs."), "error");
		}
	}

	openRunDialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Create Trial Planning Run"),
			fields: [
				{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1, default: this.companyField.get_value() || frappe.defaults.get_user_default("Company") },
				{ fieldname: "plant_floor", fieldtype: "Link", options: "Plant Floor", label: __("Plant Floor"), default: this.plantFloorField.get_value() || undefined },
				{ fieldname: "horizon_days", fieldtype: "Int", label: __("Horizon Days"), default: 14, reqd: 1 },
			],
			primary_action_label: __("Run Trial"),
			primary_action: async (values) => {
				const result = await frappe.xcall("injection_aps.api.app.run_planning_run", values);
				showApsWarnings(result, __("Planning Precheck Warnings"));
				dialog.hide();
				frappe.show_alert({ message: __("Planning run completed."), indicator: "green" });
				await this.refresh();
			},
		});
		dialog.show();
	}
}

function showApsWarnings(result, title) {
	if (!result || !result.preflight_warning_count) {
		return;
	}

	const warnings = result.preflight_warnings || [];
	const extraCount = Math.max((result.preflight_warning_count || 0) - warnings.length, 0);
	const rows = warnings
		.map((row) => `<li>${frappe.utils.escape_html(row.message || "")}</li>`)
		.join("");

	frappe.msgprint({
		title: title || __("APS Warnings"),
		message: `
			<div>${__("Warnings")}: <b>${result.preflight_warning_count || 0}</b></div>
			<ul style="margin-top:8px; padding-left:18px;">${rows}</ul>
			${extraCount ? `<div class="text-muted" style="margin-top:8px;">${__("Additional warnings")}: ${extraCount}</div>` : ""}
		`,
		wide: true,
	});
}
