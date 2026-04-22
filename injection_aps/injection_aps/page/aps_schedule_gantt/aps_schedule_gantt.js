frappe.pages["aps-schedule-gantt"].on_page_load = function (wrapper) {
	frappe.require("/assets/injection_aps/js/injection_aps_shared.js", () => {
		if (!wrapper.injection_aps_controller) {
			wrapper.injection_aps_controller = new InjectionAPSScheduleGantt(wrapper);
		}
		wrapper.injection_aps_controller.refresh();
	});
};

frappe.pages["aps-schedule-gantt"].on_page_show = function (wrapper) {
	wrapper.injection_aps_controller?.refresh();
};

class InjectionAPSScheduleGantt {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Machine Schedule Gantt"),
			single_column: true,
		});
		this.runField = this.page.add_field({
			fieldtype: "Link",
			fieldname: "run_name",
			options: "APS Planning Run",
			label: __("Planning Run"),
		});
		this.page.set_primary_action(__("Load Gantt"), () => this.refresh());
		this.page.add_action_item(__("Open Run"), () => {
			const runName = this.runField.get_value();
			if (runName) {
				frappe.set_route("Form", "APS Planning Run", runName);
			}
		});

		this.page.main.html(`
			<div class="ia-page">
				<div class="ia-banner">
					<h3>${__("Machine Schedule View")}</h3>
					<p>${__("This一期版本 keeps the schedule board readable and auditable without enabling drag editing yet.")}</p>
				</div>
				<div class="ia-card-grid ia-summary"></div>
				<div class="ia-feedback"></div>
				<div class="ia-gantt-shell">
					<div class="ia-gantt-grid"></div>
				</div>
			</div>
		`);
		this.summary = this.page.main.find(".ia-summary")[0];
		this.feedback = this.page.main.find(".ia-feedback")[0];
		this.grid = this.page.main.find(".ia-gantt-grid")[0];
	}

	async refresh() {
		injection_aps.ui.ensure_styles();
		const runName = this.runField.get_value();
		if (!runName) {
			injection_aps.ui.render_cards(this.summary, [
				{ label: __("Planning Run"), value: __("Not Selected"), note: __("Choose a run first.") },
			]);
			this.grid.innerHTML = `<div class="ia-muted">${__("Choose a planning run to load the schedule board.")}</div>`;
			return;
		}

		injection_aps.ui.set_feedback(this.feedback, __("Loading Gantt data..."));
		try {
			const data = await frappe.xcall("injection_aps.api.app.get_schedule_gantt_data", {
				run_name: runName,
			});
			this.renderGantt(data.tasks || []);
			injection_aps.ui.set_feedback(this.feedback, __("Gantt refreshed."));
		} catch (error) {
			console.error(error);
			injection_aps.ui.set_feedback(this.feedback, __("Failed to load Gantt data."), "error");
		}
	}

	renderGantt(tasks) {
		if (!tasks.length) {
			injection_aps.ui.render_cards(this.summary, [
				{ label: __("Tasks"), value: 0, note: __("No scheduled segments for this run.") },
			]);
			this.grid.innerHTML = `<div class="ia-muted">${__("No schedule segments were generated for this planning run.")}</div>`;
			return;
		}

		const parsedTasks = tasks.map((task) => ({
			...task,
			startDate: frappe.datetime.str_to_obj(task.start),
			endDate: frappe.datetime.str_to_obj(task.end),
		}));
		const minTime = Math.min(...parsedTasks.map((task) => task.startDate.getTime()));
		const maxTime = Math.max(...parsedTasks.map((task) => task.endDate.getTime()));
		const span = Math.max(maxTime - minTime, 1);
		const byWorkstation = {};

		parsedTasks.forEach((task) => {
			const workstation = task.details?.workstation || __("Unknown");
			if (!byWorkstation[workstation]) {
				byWorkstation[workstation] = [];
			}
			byWorkstation[workstation].push(task);
		});

		injection_aps.ui.render_cards(this.summary, [
			{ label: __("Tasks"), value: parsedTasks.length },
			{ label: __("Machines"), value: Object.keys(byWorkstation).length },
			{ label: __("Window Start"), value: new Date(minTime).toLocaleString() },
			{ label: __("Window End"), value: new Date(maxTime).toLocaleString() },
		]);

		this.grid.innerHTML = Object.entries(byWorkstation)
			.map(([workstation, rows]) => {
				const bars = rows
					.map((task) => {
						const left = ((task.startDate.getTime() - minTime) / span) * 100;
						const width = Math.max(((task.endDate.getTime() - task.startDate.getTime()) / span) * 100, 4);
						const tone = (task.custom_class || "").replace("ia-risk-", "");
						const label = `${task.details?.item_code || ""} / ${frappe.format(task.details?.planned_qty || 0, { fieldtype: "Float" })}`;
						return `<div class="ia-gantt-bar ${tone}" style="left:${left}%; width:${width}%;" title="${frappe.utils.escape_html(label)}">${frappe.utils.escape_html(label)}</div>`;
					})
					.join("");
				return `
					<div class="ia-gantt-row">
						<div class="ia-gantt-label">${frappe.utils.escape_html(workstation)}</div>
						<div class="ia-gantt-track">${bars}</div>
					</div>
				`;
			})
			.join("");
	}
}
