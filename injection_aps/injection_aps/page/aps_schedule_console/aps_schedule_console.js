frappe.pages["aps-schedule-console"].on_page_load = function (wrapper) {
	frappe.require("/assets/injection_aps/js/injection_aps_shared.js", () => {
		if (!wrapper.injection_aps_controller) {
			wrapper.injection_aps_controller = new InjectionAPSScheduleConsole(wrapper);
		}
		wrapper.injection_aps_controller.refresh();
	});
};

frappe.pages["aps-schedule-console"].on_page_show = function (wrapper) {
	wrapper.injection_aps_controller?.refresh();
};

class InjectionAPSScheduleConsole {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.pendingImport = null;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Schedule Import & Diff"),
			single_column: true,
		});
		this.page.set_primary_action(__("Preview Import"), () => this.openPreviewDialog());
		this.page.set_secondary_action(__("Import Pending"), () => this.importPending());
		this.page.add_action_item(__("Schedule List"), () => frappe.set_route("List", "Customer Delivery Schedule"));
		this.page.add_action_item(__("Import Batches"), () => frappe.set_route("List", "APS Schedule Import Batch"));

		this.page.main.html(`
			<div class="ia-page">
				<div class="ia-banner">
					<h3>${__("Customer Schedule Versions")}</h3>
					<p>${__("Preview Excel or pasted rows first, compare against the current active version, then import the new official version.")}</p>
				</div>
				<div class="ia-card-grid ia-summary"></div>
				<div class="ia-feedback"></div>
				<div class="ia-panel">
					<h4>${__("Pending Preview")}</h4>
					<div class="ia-preview-summary ia-card-grid" style="margin-top: 10px;"></div>
					<div class="ia-preview-table" style="margin-top: 12px;"></div>
				</div>
				<div class="ia-panel">
					<h4>${__("Active Versions")}</h4>
					<div class="ia-active-table" style="margin-top: 12px;"></div>
				</div>
				<div class="ia-panel">
					<h4>${__("Recent Import Batches")}</h4>
					<div class="ia-batch-table" style="margin-top: 12px;"></div>
				</div>
			</div>
		`);

		this.summary = this.page.main.find(".ia-summary")[0];
		this.feedback = this.page.main.find(".ia-feedback")[0];
		this.previewSummary = this.page.main.find(".ia-preview-summary")[0];
		this.previewTable = this.page.main.find(".ia-preview-table")[0];
		this.activeTable = this.page.main.find(".ia-active-table")[0];
		this.batchTable = this.page.main.find(".ia-batch-table")[0];
	}

	async refresh() {
		injection_aps.ui.ensure_styles();
		injection_aps.ui.set_feedback(this.feedback, __("Loading schedule versions..."));

		try {
			const data = await frappe.xcall("injection_aps.api.app.get_schedule_console_data");
			injection_aps.ui.render_cards(this.summary, [
				{ label: __("Active Versions"), value: data.summary.active_versions || 0, note: __("One active version per customer/company") },
				{ label: __("Recent Batches"), value: data.summary.recent_batches || 0, note: __("Latest import attempts") },
				{ label: __("Active Qty"), value: frappe.format(data.summary.active_qty || 0, { fieldtype: "Float" }), note: __("Total qty in active versions") },
			]);
			this.renderScheduleTable(data.active_schedules || []);
			this.renderBatchTable(data.import_batches || []);
			this.renderPreview();
			injection_aps.ui.set_feedback(this.feedback, this.pendingImport ? __("Preview ready. Import pending confirmation.") : __("Schedule console refreshed."));
		} catch (error) {
			console.error(error);
			injection_aps.ui.set_feedback(this.feedback, __("Failed to load schedule versions."), "error");
		}
	}

	renderScheduleTable(rows) {
		const columns = [
			{ label: __("Name"), fieldname: "name" },
			{ label: __("Customer"), fieldname: "customer" },
			{ label: __("Company"), fieldname: "company" },
			{ label: __("Version"), fieldname: "version_no" },
			{ label: __("Source"), fieldname: "source_type" },
			{ label: __("Status"), fieldname: "status" },
			{ label: __("Qty"), fieldname: "schedule_total_qty" },
			{ label: __("Modified"), fieldname: "modified" },
		];
		injection_aps.ui.render_table(this.activeTable, columns, rows, (column, value, row) => {
			if (column.fieldname === "name") {
				return injection_aps.ui.route_link(value, `customer-delivery-schedule/${encodeURIComponent(value)}`);
			}
			if (column.fieldname === "source_type") {
				return frappe.utils.escape_html(injection_aps.ui.translate(value));
			}
			if (column.fieldname === "status") {
				return injection_aps.ui.pill(injection_aps.ui.translate(value), value === "Active" ? "green" : "blue");
			}
			if (column.fieldname === "schedule_total_qty") {
				return frappe.format(value || 0, { fieldtype: "Float" });
			}
			if (column.fieldname === "modified") {
				return injection_aps.ui.format_datetime(value);
			}
			return frappe.utils.escape_html(value == null ? "" : String(value));
		});
	}

	renderBatchTable(rows) {
		const columns = [
			{ label: __("Batch"), fieldname: "name" },
			{ label: __("Customer"), fieldname: "customer" },
			{ label: __("Company"), fieldname: "company" },
			{ label: __("Version"), fieldname: "version_no" },
			{ label: __("Status"), fieldname: "status" },
			{ label: __("Imported"), fieldname: "imported_rows" },
			{ label: __("Effective"), fieldname: "effective_rows" },
			{ label: __("Modified"), fieldname: "modified" },
		];
		injection_aps.ui.render_table(this.batchTable, columns, rows, (column, value) => {
			if (column.fieldname === "status") {
				return injection_aps.ui.pill(injection_aps.ui.translate(value), value === "Imported" ? "green" : "orange");
			}
			if (column.fieldname === "modified") {
				return injection_aps.ui.format_datetime(value);
			}
			return frappe.utils.escape_html(value == null ? "" : String(value));
		});
	}

	renderPreview() {
		const preview = this.pendingImport?.preview;
		if (!preview) {
			injection_aps.ui.render_cards(this.previewSummary, [
				{ label: __("Preview"), value: __("None"), note: __("Run a preview before the formal import.") },
			]);
			injection_aps.ui.render_table(this.previewTable, [{ label: __("Info"), fieldname: "message" }], []);
			return;
		}

		const summaryRows = Object.entries(preview.summary || {}).map(([label, value]) => ({
			label: injection_aps.ui.translate(label),
			value,
		}));
		injection_aps.ui.render_cards(this.previewSummary, [
			{ label: __("Customer"), value: preview.customer || "-" },
			{ label: __("Version"), value: preview.version_no || "-" },
			{ label: __("Rows"), value: preview.row_count || 0 },
			{ label: __("Changes"), value: summaryRows.length || 0, note: summaryRows.map((row) => `${row.label}: ${row.value}`).join(" | ") },
		]);
		injection_aps.ui.render_table(
			this.previewTable,
			[
				{ label: __("Sales Order"), fieldname: "sales_order" },
				{ label: __("Item"), fieldname: "item_code" },
				{ label: __("Part No"), fieldname: "customer_part_no" },
				{ label: __("Schedule Date"), fieldname: "schedule_date" },
				{ label: __("Qty"), fieldname: "qty" },
				{ label: __("Prev Qty"), fieldname: "previous_qty" },
				{ label: __("Change"), fieldname: "change_type" },
			],
			preview.rows || [],
			(column, value, row) => {
				if (column.fieldname === "change_type") {
					const tone = ["Cancelled", "Reduced", "Delayed"].includes(value)
						? "red"
						: ["Advanced", "Added", "Increased"].includes(value)
							? "orange"
							: "green";
					return injection_aps.ui.pill(injection_aps.ui.translate(value), tone);
				}
				if (["qty", "previous_qty"].includes(column.fieldname)) {
					return frappe.format(value || 0, { fieldtype: "Float" });
				}
				if (column.fieldname === "schedule_date") {
					return injection_aps.ui.format_date(value);
				}
				return frappe.utils.escape_html(value == null ? "" : String(value));
			}
		);
	}

	openPreviewDialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Preview Customer Schedule Import"),
			fields: [
				{ fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer"), reqd: 1 },
				{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1, default: frappe.defaults.get_user_default("Company") },
				{ fieldname: "version_no", fieldtype: "Data", label: __("Version No"), reqd: 1 },
				{ fieldname: "file_url", fieldtype: "Attach", label: __("Excel File") },
				{ fieldname: "rows_json", fieldtype: "Small Text", label: __("Rows JSON"), description: __("Optional. Paste JSON rows when no Excel file is available.") },
			],
			primary_action_label: __("Preview"),
			primary_action: async (values) => {
				await this.previewImport(values);
				dialog.hide();
			},
		});
		dialog.show();
	}

	async previewImport(values) {
		const payload = {
			customer: values.customer,
			company: values.company,
			version_no: values.version_no,
			file_url: values.file_url || undefined,
			rows_json: values.rows_json || undefined,
		};
		injection_aps.ui.set_feedback(this.feedback, __("Running import preview..."));
		const preview = await frappe.xcall("injection_aps.api.app.preview_customer_delivery_schedule", payload);
		this.pendingImport = { payload, preview };
		this.renderPreview();
		injection_aps.ui.set_feedback(this.feedback, __("Preview completed. Review the changes and click Import Pending when ready."), "warning");
	}

	async importPending() {
		if (!this.pendingImport) {
			frappe.show_alert({ message: __("No pending preview to import."), indicator: "orange" });
			return;
		}
		const response = await frappe.xcall(
			"injection_aps.api.app.import_customer_delivery_schedule",
			this.pendingImport.payload
		);
		this.pendingImport = null;
		frappe.show_alert({ message: __("Imported schedule {0}.").replace("{0}", response.schedule), indicator: "green" });
		await this.refresh();
	}
}
