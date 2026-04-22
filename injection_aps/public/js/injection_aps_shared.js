frappe.provide("injection_aps.ui");

(function () {
	if (injection_aps.ui.__initialized) {
		return;
	}

	injection_aps.ui.__initialized = true;

	injection_aps.ui.ensure_styles = function () {
		if (document.getElementById("injection-aps-page-style")) {
			return;
		}
		const link = document.createElement("link");
		link.id = "injection-aps-page-style";
		link.rel = "stylesheet";
		link.href = "/assets/injection_aps/css/injection_aps.css";
		document.head.appendChild(link);
	};

	injection_aps.ui.pill = function (label, tone) {
		return `<span class="ia-pill ${tone || "blue"}">${frappe.utils.escape_html(label || "")}</span>`;
	};

	injection_aps.ui.translate = function (value) {
		if (value == null || value === "") {
			return "";
		}
		return __(String(value));
	};

	injection_aps.ui.route_link = function (label, route) {
		return `<a href="/app/${route}" class="ia-link">${frappe.utils.escape_html(label || "")}</a>`;
	};

	injection_aps.ui.format_datetime = function (value) {
		if (!value) {
			return "";
		}
		return frappe.datetime.str_to_user(value);
	};

	injection_aps.ui.format_date = function (value) {
		if (!value) {
			return "";
		}
		return frappe.datetime.str_to_user(value);
	};

	injection_aps.ui.render_cards = function (target, cards) {
		target.innerHTML = cards
			.map(
				(card) => `
			<div class="ia-card">
				<span class="ia-card-label">${frappe.utils.escape_html(card.label || "")}</span>
				<div class="ia-card-value">${frappe.utils.escape_html(String(card.value ?? ""))}</div>
				${card.note ? `<div class="ia-muted" style="margin-top:6px;">${frappe.utils.escape_html(card.note)}</div>` : ""}
			</div>
		`
			)
			.join("");
	};

	injection_aps.ui.render_table = function (target, columns, rows, formatter) {
		if (!rows || !rows.length) {
			target.innerHTML = `<div class="ia-table-shell"><div class="ia-muted" style="padding:14px 16px;">${__("No rows found.")}</div></div>`;
			return;
		}

		let body = rows
			.map((row) => {
				const cells = columns
					.map((column) => {
						const rawValue = row[column.fieldname];
						const value = formatter ? formatter(column, rawValue, row) : frappe.utils.escape_html(rawValue == null ? "" : String(rawValue));
						return `<td>${value}</td>`;
					})
					.join("");
				return `<tr>${cells}</tr>`;
			})
			.join("");

		target.innerHTML = `
			<div class="ia-table-shell">
				<table class="ia-table">
					<thead>
						<tr>${columns.map((column) => `<th>${frappe.utils.escape_html(column.label)}</th>`).join("")}</tr>
					</thead>
					<tbody>${body}</tbody>
				</table>
			</div>
		`;
	};

	injection_aps.ui.set_feedback = function (target, message, tone) {
		if (!target) {
			return;
		}
		target.className = `ia-feedback ${tone || ""}`.trim();
		target.textContent = message || "";
	};
})();
