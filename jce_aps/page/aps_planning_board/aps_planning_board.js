
frappe.pages['aps-planning-board'].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('APS Planning Board'),
        single_column: true
    });

    $(wrapper).find('.layout-main-section').html(`
        <div class="aps-board-placeholder" style="padding: 24px; background: #fff; border-radius: 12px;">
            <h3 style="margin-top: 0;">${__('JCE APS Planning Board')}</h3>
            <p>${__('This is a starter board page. Next step: add machine timeline / gantt and drag-drop manual adjustment.')}</p>
            <p>${__('Use APS Planning Run for the first scheduling cycle.')}</p>
        </div>
    `);
};
