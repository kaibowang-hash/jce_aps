frappe.ui.form.on("Customer Delivery Schedule", {
	refresh(frm) {
		if (!frm.doc.customer || !frm.doc.company) {
			return;
		}

		frm.add_custom_button(__("Preview Current Rows"), async () => {
			const preview = await frappe.xcall("injection_aps.api.app.preview_customer_delivery_schedule", {
				customer: frm.doc.customer,
				company: frm.doc.company,
				version_no: frm.doc.version_no || frm.doc.name,
				rows_json: JSON.stringify(
					(frm.doc.items || []).map((row) => ({
						sales_order: row.sales_order,
						item_code: row.item_code,
						customer_part_no: row.customer_part_no,
						schedule_date: row.schedule_date,
						qty: row.qty,
						remark: row.remark,
					}))
				),
			});
			frappe.msgprint({
				title: __("Preview Summary"),
				message: `
					<div>${__("Rows")}: <b>${preview.row_count || 0}</b></div>
					<div>${__("Changes")}: <pre style="margin-top:8px;">${frappe.utils.escape_html(JSON.stringify(preview.summary || {}, null, 2))}</pre></div>
				`,
				wide: true,
			});
		});

		frm.add_custom_button(__("Rebuild Demand Pool"), async () => {
			const result = await frappe.xcall("injection_aps.api.app.rebuild_demand_pool", {
				company: frm.doc.company,
			});
			showApsWarnings(result, __("Demand Pool Warnings"));
			frappe.show_alert({ message: __("Demand pool rebuilt."), indicator: "green" });
		});
	},
});

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
