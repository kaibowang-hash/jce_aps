frappe.ui.form.on("APS Planning Run", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Run Planning"), async () => {
			const result = await frappe.xcall("injection_aps.api.app.run_planning_run", {
				run_name: frm.doc.name,
			});
			showApsWarnings(result, __("Planning Precheck Warnings"));
			await frm.reload_doc();
			frappe.show_alert({ message: __("Planning run completed."), indicator: "green" });
		});

		if (frm.doc.approval_state !== "Approved") {
			frm.add_custom_button(__("Approve"), async () => {
				await frappe.xcall("injection_aps.api.app.approve_planning_run", {
					run_name: frm.doc.name,
				});
				await frm.reload_doc();
				frappe.show_alert({ message: __("Planning run approved."), indicator: "green" });
			});
		}

		if (frm.doc.approval_state === "Approved") {
			frm.add_custom_button(__("Sync Downstream"), async () => {
				await frappe.xcall("injection_aps.api.app.sync_planning_run_to_execution", {
					run_name: frm.doc.name,
				});
				await frm.reload_doc();
				frappe.show_alert({ message: __("Run synced downstream."), indicator: "green" });
			});
		}

		if (["Approved", "Synced", "Partially Released"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Release Window"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Release Short-Term Window"),
					fields: [
						{
							fieldname: "release_horizon_days",
							fieldtype: "Int",
							label: __("Release Horizon Days"),
							default: 3,
							reqd: 1,
						},
					],
					primary_action_label: __("Release"),
					primary_action: async (values) => {
						await frappe.xcall("injection_aps.api.app.release_planning_run", {
							run_name: frm.doc.name,
							release_horizon_days: values.release_horizon_days,
						});
						dialog.hide();
						await frm.reload_doc();
						frappe.show_alert({ message: __("Release completed."), indicator: "green" });
					},
				});
				dialog.show();
			});
		}

		frm.add_custom_button(__("Rebuild Exceptions"), async () => {
			await frappe.xcall("injection_aps.api.app.rebuild_exceptions", {
				run_name: frm.doc.name,
			});
			frappe.show_alert({ message: __("Exceptions rebuilt."), indicator: "green" });
		});
	},
});

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
