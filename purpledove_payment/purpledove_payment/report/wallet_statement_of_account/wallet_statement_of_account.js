// Copyright (c) 2026, Ejiroghene Douglas Dominic and contributors
// For license information, please see license.txt

// Laid out as a conventional statement of account, matching the PDF in
// purpledove_payment/statement.py: account header, account summary, then a ledger of
// Opening Balance -> transactions. Totals and the closing balance live in the summary.
const REPORT_NAME = "Wallet Statement of Account";
const STATUS_COLORS = { Successful: "green", Paid: "green", Pending: "orange", Failed: "red" };

// The statement always uses the full-width layout; leaving the report restores the
// user's own full-width preference.
if (!frappe._wallet_statement_layout_bound) {
	frappe._wallet_statement_layout_bound = true;
	frappe.router.on("change", apply_page_width);
	$(window).on(
		"resize",
		frappe.utils.debounce(() => fill_narration(), 150)
	);
}

frappe.query_reports[REPORT_NAME] = {
	filters: [
		{
			fieldname: "wallet",
			fieldtype: "Link",
			label: __("Virtual Wallet"),
			options: "Virtual Wallet",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			fieldtype: "Date",
			label: __("From Date"),
			reqd: 1,
			default: frappe.datetime.month_start(),
			on_change: refresh_if_valid_range,
		},
		{
			fieldname: "to_date",
			fieldtype: "Date",
			label: __("To Date"),
			reqd: 1,
			default: frappe.datetime.get_today(),
			on_change: refresh_if_valid_range,
		},
		{
			fieldname: "show",
			fieldtype: "Select",
			label: __("Show"),
			options: ["Settled only", "All events"],
			default: "Settled only",
			reqd: 1,
			description: __(
				"'All events' also lists pending and failed transfers, which don't affect the balance."
			),
		},
	],

	onload(report) {
		apply_page_width();
		report.page.set_primary_action(__("Download PDF"), () => download_pdf(report));
		report.page.set_secondary_action(__("Print"), () => print_statement(report), "printer");

		// Most sites have a single wallet; preselect it to save a step
		if (!report.get_filter_value("wallet")) {
			frappe.db
				.get_list("Virtual Wallet", { fields: ["name"], limit: 2 })
				.then((wallets) => {
					if (wallets.length === 1 && !report.get_filter_value("wallet")) {
						report.set_filter_value("wallet", wallets[0].name);
					}
				});
		}
	},

	after_datatable_render() {
		render_statement_header(frappe.query_report);
		fix_text_alignment(frappe.query_report.datatable);
		// Rows render on the next frame; measure after they exist, and once more after the
		// header above the table has settled
		requestAnimationFrame(() => fill_narration());
		setTimeout(() => fill_narration(), 300);
	},

	formatter(value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);

		const fieldname = column.fieldname;
		let formatted;

		if (["debit", "credit", "balance"].includes(fieldname)) {
			// Two-decimal amounts (currency is in the header), blank rather than 0.00 where a
			// transaction has no amount. Debits red, credits green.
			const blank_zero = fieldname !== "balance";
			const tone = fieldname === "balance" ? "" : `ws-${fieldname}`;
			formatted =
				value == null || (blank_zero && !flt(value))
					? ""
					: `<div class="${["text-right", tone]
							.filter(Boolean)
							.join(" ")}">${format_number(value, null, 2)}</div>`;
		} else if (fieldname === "date_time" && value) {
			// Transactions show date and time (HH:mm); the opening row the date only
			const [date, time = ""] = String(value).split(" ");
			const day = frappe.datetime.str_to_user(date);
			formatted = is_ledger_row(data)
				? day
				: `${day} <span class="ws-time">${time.slice(0, 5)}</span>`;
		} else {
			formatted = default_formatter(value, row, column, data);
		}

		if (is_ledger_row(data)) return formatted && `<strong>${formatted}</strong>`;

		if (fieldname === "status" && value) {
			const color = STATUS_COLORS[value] || "gray";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(
				__(value)
			)}</span>`;
		}

		// Pending/failed events (shown under "All events") move no money
		if (!flt(data.debit) && !flt(data.credit) && fieldname !== "date_time") {
			return formatted && `<span class="text-muted">${formatted}</span>`;
		}
		return formatted;
	},
};

function is_ledger_row(data) {
	return !data.reference && data.description === "Opening Balance";
}

const wallet_headers = {};

function render_statement_header(report) {
	const rows = report.data || [];
	const opening = rows.find(is_ledger_row);
	if (!opening) return;

	const txns = rows.filter((r) => !is_ledger_row(r));
	const n_debits = txns.filter((r) => flt(r.debit)).length;
	const n_credits = txns.filter((r) => flt(r.credit)).length;
	const total_debit = flt(
		txns.reduce((sum, r) => sum + flt(r.debit), 0),
		2
	);
	const total_credit = flt(
		txns.reduce((sum, r) => sum + flt(r.credit), 0),
		2
	);
	const closing_balance = flt(flt(opening.balance) + total_credit - total_debit, 2);
	const unsettled = txns.length - n_debits - n_credits;
	const { wallet, from_date, to_date, show } = report.get_filter_values();

	ensure_statement_styles();
	if (!report.$statement_header) {
		report.$statement_header = $(`<div class="wallet-statement-header"></div>`).insertBefore(
			report.$summary
		);
	}

	const draw = (details) => {
		// Ignore a late response for a wallet the user has since switched away from
		if (report.get_filter_value("wallet") !== wallet) return;
		const currency = details?.currency || "NGN";
		const e = frappe.utils.escape_html;
		const fmt = (v) => format_currency(flt(v), currency);
		const field = (label, value) =>
			`<div><div class="ws-label">${label}</div><div class="ws-value">${value}</div></div>`;
		const cell = (label, value, note = "", cls = "") =>
			`<td class="${cls}" data-label="${label}">${value}${
				note && `<span>${note}</span>`
			}</td>`;

		report.$statement_header.html(`
			<div class="ws-title">
				<h3>${__("Statement of Account")}</h3>
				<div class="ws-period">
					${e(frappe.datetime.str_to_user(from_date))} – ${e(frappe.datetime.str_to_user(to_date))}
				</div>
			</div>
			<div class="ws-grid">
				${field(__("Account Name"), e(details?.wallet_name || wallet))}
				${field(__("Account Number"), e(details?.account_number || "—"))}
				${field(__("Bank"), e(details?.bank_name || "—"))}
				${field(__("Currency"), e(currency))}
			</div>
			<table class="ws-summary">
				<thead><tr>
					<th>${__("Opening Balance")}</th>
					<th>${__("Total Debits")}</th>
					<th>${__("Total Credits")}</th>
					<th>${__("Closing Balance")}</th>
				</tr></thead>
				<tbody><tr>
					${cell(__("Opening Balance"), fmt(opening.balance))}
					${cell(__("Total Debits"), fmt(total_debit), count(n_debits), "ws-debit")}
					${cell(__("Total Credits"), fmt(total_credit), count(n_credits), "ws-credit")}
					${cell(__("Closing Balance"), fmt(closing_balance), "", "ws-closing")}
				</tr></tbody>
			</table>
			${
				show === "All events" && unsettled
					? `<div class="ws-note">${__(
							"Includes {0} pending or failed transfer(s), which do not affect the balance.",
							[unsettled]
					  )}</div>`
					: ""
			}
		`);
	};

	draw(wallet_headers[wallet]);
	if (!wallet_headers[wallet]) {
		frappe
			.xcall("purpledove_payment.statement.wallet_statement_header", { wallet })
			.then((details) => {
				wallet_headers[wallet] = details;
				draw(details);
			})
			.catch(() => {}); // header falls back to the wallet name alone
	}
}

function count(n) {
	return n === 1 ? __("1 transaction") : __("{0} transactions", [n]);
}

function ensure_statement_styles() {
	if (document.getElementById("wallet-statement-styles")) return;
	$(`<style id="wallet-statement-styles">
		.wallet-statement-header {
			margin: var(--margin-md);
			padding-bottom: var(--padding-md);
			border-bottom: 1px solid var(--border-color);
			font-variant-numeric: tabular-nums;
		}
		.wallet-statement-header .ws-title {
			display: flex;
			flex-wrap: wrap;
			justify-content: space-between;
			align-items: baseline;
			gap: var(--padding-sm);
		}
		.wallet-statement-header h3 {
			margin: 0;
			font-size: var(--text-lg);
			font-weight: 700;
			letter-spacing: 0.04em;
			text-transform: uppercase;
			color: var(--heading-color, var(--text-color));
		}
		.wallet-statement-header .ws-period { color: var(--text-muted); font-size: var(--text-sm); }
		.wallet-statement-header .ws-grid {
			display: grid;
			grid-template-columns: repeat(4, minmax(0, 1fr));
			gap: var(--padding-md);
			margin-top: var(--margin-md);
		}
		.wallet-statement-header .ws-label {
			font-size: var(--text-xs);
			text-transform: uppercase;
			letter-spacing: 0.05em;
			color: var(--text-muted);
		}
		.wallet-statement-header .ws-value {
			font-weight: 600;
			color: var(--text-color);
			margin-top: 2px;
			overflow-wrap: anywhere;
		}
		.wallet-statement-header .ws-summary {
			width: 100%;
			margin-top: var(--margin-md);
			border-collapse: collapse;
			table-layout: fixed;
		}
		.wallet-statement-header .ws-summary th,
		.wallet-statement-header .ws-summary td {
			border: 1px solid var(--border-color);
			padding: 6px 10px;
			text-align: right;
		}
		.wallet-statement-header .ws-summary th {
			font-size: var(--text-xs);
			font-weight: 600;
			text-transform: uppercase;
			letter-spacing: 0.05em;
			color: var(--text-muted);
			background: var(--subtle-fg, var(--control-bg));
		}
		.wallet-statement-header .ws-summary td {
			font-size: var(--text-md, var(--text-base));
			font-weight: 600;
			color: var(--text-color);
		}
		.wallet-statement-header .ws-summary td span {
			display: block;
			font-size: var(--text-xs);
			font-weight: 400;
			color: var(--text-muted);
		}
		.wallet-statement-header .ws-summary td.ws-closing {
			background: var(--bg-blue);
			color: var(--text-on-blue);
		}
		.wallet-statement-header .ws-summary td.ws-closing span { color: inherit; opacity: 0.8; }
		.ws-debit,
		.wallet-statement-header .ws-summary td.ws-debit { color: var(--text-on-red); }
		.ws-credit,
		.wallet-statement-header .ws-summary td.ws-credit { color: var(--text-on-green); }
		.ws-time { color: var(--text-muted); margin-left: 4px; }
		.wallet-statement-header .ws-note {
			margin-top: var(--margin-sm);
			font-size: var(--text-sm);
			color: var(--text-muted);
		}
		@media (max-width: 767px) {
			.wallet-statement-header .ws-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
			.wallet-statement-header .ws-summary { table-layout: auto; }
			.wallet-statement-header .ws-summary thead { display: none; }
			.wallet-statement-header .ws-summary tr { display: grid; grid-template-columns: 1fr 1fr; }
			.wallet-statement-header .ws-summary td { text-align: left; }
			.wallet-statement-header .ws-summary td::before {
				content: attr(data-label);
				display: block;
				font-size: var(--text-xs);
				font-weight: 400;
				text-transform: uppercase;
				color: var(--text-muted);
			}
		}
	</style>`).appendTo(document.head);
}

function is_statement_route() {
	const [view, name] = frappe.get_route();
	return view === "query-report" && name === REPORT_NAME;
}

function apply_page_width() {
	if (is_statement_route()) {
		document.body.classList.add("full-width");
	} else {
		frappe.ui.toolbar.set_fullwidth_if_enabled();
	}
}

function fix_text_alignment(datatable) {
	// The datatable right-aligns any column whose first-row value passes isNaN(), and the
	// Opening Balance row's empty Reference/Status cells do; keep text columns left-aligned
	if (!datatable) return;
	datatable
		.getColumns()
		.filter((c) => ["date_time", "reference", "description", "status"].includes(c.id))
		.forEach((c) => (c.align = "left"));
	datatable.style.setColumnStyle();
}

function fill_narration() {
	// Give spare width to Narration so the ledger spans the card; at narrow widths it
	// keeps its configured width and the table scrolls.
	const datatable = is_statement_route() && frappe.query_report?.datatable;
	if (!datatable?.datatableWrapper?.isConnected) return;

	const columns = datatable.getColumns();
	const column = columns.find((c) => c.id === "description");
	if (!column) return;

	column._base_width = column._base_width || column.width;
	// Every other column (row index included) plus 1px of border per cell
	const others = columns
		.filter((c) => c !== column && !c.hidden)
		.reduce((sum, c) => sum + (c.width || 0) + 1, 0);
	const scrollbar = datatable.bodyScrollable.offsetWidth - datatable.bodyScrollable.clientWidth;
	const available = datatable.datatableWrapper.clientWidth - others - scrollbar - 4;
	const width = Math.max(column._base_width, Math.floor(available));
	if (width === column.width) return;

	datatable.datamanager.updateColumn(column.colIndex, { width });
	datatable.columnmanager.setColumnWidth(column.colIndex);
	datatable.columnmanager.setColumnHeaderWidth(column.colIndex);
	datatable.style.setBodyStyle();
}

function has_valid_range(report) {
	const from_date = report.get_filter_value("from_date");
	const to_date = report.get_filter_value("to_date");
	if (
		from_date &&
		to_date &&
		frappe.datetime.str_to_obj(from_date) > frappe.datetime.str_to_obj(to_date)
	) {
		frappe.show_alert({ message: __("From Date cannot be after To Date"), indicator: "red" });
		return false;
	}
	return true;
}

function refresh_if_valid_range(report) {
	if (has_valid_range(report)) report.refresh(true);
}

function get_pdf_filters(report) {
	let filters;
	try {
		// Passing true shows "Please set filters" and throws if a mandatory filter is empty
		filters = report.get_filter_values(true);
	} catch (e) {
		return null;
	}
	if (!has_valid_range(report)) return null;
	const { wallet, from_date, to_date, show } = filters;
	return { wallet, from_date, to_date, show };
}

const PDF_METHOD = "/api/method/purpledove_payment.statement.wallet_statement";

function download_pdf(report) {
	const filters = get_pdf_filters(report);
	if (filters) open_url_post(PDF_METHOD, filters);
}

function print_statement(report) {
	// Prints the same PDF as Download, so the paper copy matches it exactly
	const filters = get_pdf_filters(report);
	if (!filters) return;

	const url = `${PDF_METHOD}?${new URLSearchParams({ ...filters, print_view: 1 })}`;
	const $btn = report.page.btn_secondary.prop("disabled", true);
	frappe.show_alert({ message: __("Preparing statement for printing…"), indicator: "blue" });

	document.getElementById("wallet-statement-print-frame")?.remove();
	const frame = Object.assign(document.createElement("iframe"), {
		id: "wallet-statement-print-frame",
		title: __("Statement of Account print preview"),
		src: url,
	});
	// Off-screen rather than display:none, which stops some browsers printing it
	Object.assign(frame.style, {
		position: "fixed",
		right: "0",
		bottom: "0",
		width: "0",
		height: "0",
		border: "0",
	});
	frame.onload = () => {
		$btn.prop("disabled", false);
		// An error (e.g. permission) comes back as a page, not a PDF; don't print that
		const type = frame.contentDocument?.contentType;
		if (type && type !== "application/pdf") {
			frame.remove();
			frappe.msgprint(__("Could not prepare the statement for printing. Please try again."));
			return;
		}
		try {
			frame.contentWindow.focus();
			frame.contentWindow.print();
		} catch (e) {
			// Browsers that can't print an embedded PDF: open it in a tab to print from there
			window.open(url, "_blank");
		}
	};
	document.body.appendChild(frame);
}
