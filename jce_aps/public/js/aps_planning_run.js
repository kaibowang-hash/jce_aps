
frappe.ui.form.on('APS Planning Run', {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Run APS Planning'), function() {
                frappe.call({
                    method: 'jce_aps.api.run_planning_run',
                    args: { docname: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Running APS planning...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frm.reload_doc();
                            frappe.show_alert({
                                message: __('APS planning completed'),
                                indicator: 'green'
                            });
                        }
                    }
                });
            }, __('Actions'));
        }
    }
});
