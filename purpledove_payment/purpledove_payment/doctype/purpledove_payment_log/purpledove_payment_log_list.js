// Copyright (c) 2026, Ejiroghene Douglas Dominic and contributors
// For license information, please see license.txt

const STATEMENT_REPORT = "Wallet Statement of Account";
// Same roles as the report's own role list
const STATEMENT_ROLES = ["System Manager", "Accounts User", "Accounts Manager"];

frappe.listview_settings["Purpledove Payment Log"] = {
	onload(listview) {
		if (!frappe.user.has_role(STATEMENT_ROLES)) return;
		listview.page.add_menu_item(__("Statement of Account"), () => show_statement_dialog());
	},
};

function show_statement_dialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Statement of Account"),
		fields: [
			{
				fieldname: "wallet",
				fieldtype: "Link",
				label: __("Virtual Wallet"),
				options: "Virtual Wallet",
				reqd: 1,
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
				reqd: 1,
				default: frappe.datetime.month_start(),
			},
			{
				fieldname: "to_date",
				fieldtype: "Date",
				label: __("To Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "show",
				fieldtype: "Select",
				label: __("Show"),
				options: ["Settled only", "All events"],
				default: "Settled only",
				reqd: 1,
				description: __("'All events' also lists pending and failed transfers, which don't affect the balance."),
			},
		],
		primary_action_label: __("Download PDF"),
		primary_action(values) {
			if (!validate_range(values)) return;
			open_url_post("/api/method/purpledove_payment.statement.wallet_statement", {
				wallet: values.wallet,
				from_date: values.from_date,
				to_date: values.to_date,
				show: values.show,
			});
			dialog.hide();
		},
		secondary_action_label: __("View Report"),
		secondary_action() {
			const values = dialog.get_values();
			if (!values || !validate_range(values)) return;
			dialog.hide();
			frappe.set_route("query-report", STATEMENT_REPORT, values);
		},
	});

	// Most sites have a single wallet; preselect it to save a step
	frappe.db.get_list("Virtual Wallet", { fields: ["name"], limit: 2 }).then((wallets) => {
		if (wallets.length === 1 && !dialog.get_value("wallet")) {
			dialog.set_value("wallet", wallets[0].name);
		}
	});

	dialog.show();
}

function validate_range({ from_date, to_date }) {
	if (frappe.datetime.str_to_obj(from_date) > frappe.datetime.str_to_obj(to_date)) {
		frappe.msgprint(__("From Date cannot be after To Date"));
		return false;
	}
	return true;
}
