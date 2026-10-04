# Copyright (c) 2026, Purpledove and contributors
# For license information, please see license.txt

import base64
import html as html_lib
import mimetypes
import os

import frappe
from frappe.desk.query_report import run as run_report
from frappe.utils import flt, fmt_money, format_time, formatdate, get_datetime, now_datetime
from frappe.utils.data import get_system_timezone
from frappe.utils.pdf import get_pdf

REPORT_NAME = "Wallet Statement of Account"
COLUMNS = ("date_time", "reference", "description", "status", "debit", "credit", "balance")

# Single accent colour for the whole document; change here to rebrand
ACCENT = "#123c6b"
ACCENT_SOFT = "#eef2f7"
DEBIT_COLOR = "#a12b2b"
CREDIT_COLOR = "#1d6b3a"


@frappe.whitelist()
def wallet_statement(wallet, from_date, to_date, show="Settled only", print_view=0):
    """Download a bank-style PDF statement for a Virtual Wallet.

    With print_view set, the PDF is served inline so the browser can print it.
    """
    result = run_report(
        REPORT_NAME,
        filters={"wallet": wallet, "from_date": from_date, "to_date": to_date, "show": show},
    )
    rows = [_as_dict(r) for r in (result.get("result") or [])]
    wallet_doc = frappe.get_doc("Virtual Wallet", wallet)

    pdf = get_pdf(
        build_html(wallet_doc, rows, from_date, to_date, show_status=show == "All events"),
        {
            "orientation": "Portrait",
            "margin-top": "12mm",
            "margin-bottom": "16mm",
            "margin-left": "10mm",
            "margin-right": "10mm",
            "footer-center": "Page [page] of [topage]",
            "footer-font-size": "7",
            "footer-spacing": "4",
        },
    )

    frappe.local.response.filecontent = pdf
    frappe.local.response["type"] = "pdf" if frappe.utils.cint(print_view) else "download"
    frappe.local.response["doctype"] = "Virtual Wallet"
    frappe.local.response["name"] = wallet_doc.name
    frappe.local.response["filename"] = (
        f"statement-{frappe.scrub(wallet_doc.name)}-{from_date}-to-{to_date}.pdf"
    )


@frappe.whitelist()
def wallet_statement_header(wallet):
    """Account details for the on-screen statement header.

    Finance roles can run the report but can't read Virtual Wallet directly, so this
    exposes just the header fields to whoever the report itself permits.
    """
    if not frappe.get_cached_doc("Report", REPORT_NAME).is_permitted():
        frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

    details = frappe.db.get_value(
        "Virtual Wallet",
        wallet,
        ["name", "wallet_name", "account_number", "bank_name", "currency"],
        as_dict=True,
    )
    if not details:
        frappe.throw(frappe._("Virtual Wallet not found"), frappe.DoesNotExistError)
    details.currency = details.currency or "NGN"
    return details


def build_html(wallet, rows, from_date, to_date, show_status=False):
    """Render the statement in the conventional layout, matching the on-screen report.

    The report returns an Opening Balance row followed by the transactions; period totals
    and the closing balance appear in the account summary, not as ledger rows.
    """
    e = html_lib.escape
    cur = wallet.currency or "NGN"
    company = _company_details()

    opening = next((r for r in rows if not r.get("reference")), {})
    txns = [r for r in rows if r.get("reference")]
    n_debits = sum(1 for r in txns if flt(r.get("debit")))
    n_credits = sum(1 for r in txns if flt(r.get("credit")))
    total_debit = flt(sum(flt(r.get("debit")) for r in txns), 2)
    total_credit = flt(sum(flt(r.get("credit")) for r in txns), 2)
    closing_balance = flt(flt(opening.get("balance")) + total_credit - total_debit, 2)
    n_unsettled = len(txns) - n_debits - n_credits

    def money(v):
        return fmt_money(flt(v), precision=2)

    def amount(v):
        return money(v) if flt(v) else ""

    def count(n):
        return f"{n} transaction{'' if n == 1 else 's'}"

    body = [
        f"<tr class='summary'><td class='dt'>{e(formatdate(from_date))}</td><td></td>"
        "<td>Opening Balance</td><td></td><td></td><td></td>"
        f"<td class='num'>{money(opening.get('balance'))}</td></tr>"
    ]
    for r in txns:
        dt = get_datetime(r.get("date_time"))
        settled = flt(r.get("debit")) or flt(r.get("credit"))
        status = str(r.get("status") or "")
        row_class = "" if settled else " class='unsettled'"
        body.append(
            f"<tr{row_class}>"
            f"<td class='dt'>{e(formatdate(dt))}<div class='time'>{e(format_time(dt, 'HH:mm'))}</div></td>"
            f"<td class='ref'>{e(str(r.get('reference') or ''))}</td>"
            f"<td class='desc'>{e(str(r.get('description') or ''))}</td>"
            f"<td class='status'><span class='badge {e(status.lower())}'>{e(status)}</span></td>"
            f"<td class='num debit'>{amount(r.get('debit'))}</td>"
            f"<td class='num credit'>{amount(r.get('credit'))}</td>"
            f"<td class='num'>{money(r.get('balance'))}</td>"
            "</tr>"
        )
    if not txns:
        body.append("<tr><td></td><td></td><td class='empty' colspan='5'>No transactions in this period.</td></tr>")

    note = (
        f"<div class='note'>Includes {n_unsettled} pending or failed transfer{'' if n_unsettled == 1 else 's'}, "
        "which do not affect the balance.</div>"
        if show_status and n_unsettled
        else ""
    )

    logo = f"<img class='logo' src='{company.logo}'/>" if company.logo else ""
    company_lines = "".join(f"<div>{line}</div>" for line in company.lines)
    generated_at = now_datetime()
    generated_by = frappe.utils.get_fullname(frappe.session.user)

    return f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 9.5px; color: #1a1a1a; margin: 0; }}
  table {{ border-collapse: collapse; }}
  .head {{ width: 100%; border-bottom: 2px solid {ACCENT}; }}
  .head td {{ vertical-align: bottom; padding-bottom: 8px; }}
  .logo {{ max-height: 48px; max-width: 180px; display: block; margin-bottom: 6px; }}
  .co-name {{ font-size: 13px; font-weight: bold; color: {ACCENT}; }}
  .co-lines {{ color: #4a5866; font-size: 8.5px; line-height: 1.45; margin-top: 2px; }}
  .title {{ text-align: right; }}
  .title h1 {{ font-size: 17px; color: {ACCENT}; margin: 0; letter-spacing: 1.5px; }}
  .title .period {{ color: #4a5866; font-size: 9px; margin-top: 3px; line-height: 1.5; }}
  .k {{ color: #5a6a7a; font-size: 7.5px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .meta {{ width: 100%; margin: 12px 0 0; }}
  .meta td {{ padding: 0 10px 0 0; width: 25%; vertical-align: top; }}
  .meta .v {{ font-weight: bold; font-size: 10px; margin-top: 2px; }}
  .summary-box {{ width: 100%; margin-top: 12px; table-layout: fixed; }}
  .summary-box th, .summary-box td {{ border: 1px solid #c9d3de; padding: 5px 8px; text-align: right; }}
  .summary-box th {{ background: {ACCENT_SOFT}; font-weight: bold; }}
  .summary-box td {{ font-size: 11px; font-weight: bold; }}
  .summary-box td .n {{ font-size: 7.5px; font-weight: normal; color: #8a97a5; margin-top: 1px; }}
  .summary-box td.debit {{ color: {DEBIT_COLOR}; }}
  .summary-box td.credit {{ color: {CREDIT_COLOR}; }}
  .summary-box td.closing {{ background: {ACCENT}; border-color: {ACCENT}; color: #fff; }}
  .note {{ color: #5a6a7a; font-size: 8px; margin-top: 5px; }}
  table.txns {{ width: 100%; margin-top: 12px; table-layout: fixed; }}
  table.txns thead {{ display: table-header-group; }}
  table.txns tr {{ page-break-inside: avoid; }}
  table.txns th {{ background: {ACCENT}; color: #fff; font-size: 8.5px; text-align: left;
                   padding: 5px 6px; font-weight: bold; border: 1px solid {ACCENT};
                   border-right-color: #3a5f8a; }}
  table.txns th:last-child {{ border-right-color: {ACCENT}; }}
  /* Column and row rules, like the on-screen ledger */
  table.txns td {{ border: 1px solid #d5dde6; padding: 5px 6px; vertical-align: top;
                   word-wrap: break-word; }}
  th.dt, td.dt {{ width: 62px; white-space: nowrap; }}
  th.ref, td.ref {{ width: 92px; }}
  td.dt .time {{ color: #8a97a5; font-size: 8px; }}
  td.ref {{ font-family: Courier, monospace; font-size: 8px; color: #4a5866; }}
  th.status, td.status {{ width: 58px; }}
  table.txns th.num, td.num {{ text-align: right; white-space: nowrap; width: 84px; }}
  td.empty {{ color: #8a97a5; font-style: italic; padding: 14px 6px; }}
  td.num.debit {{ color: {DEBIT_COLOR}; }}
  td.num.credit {{ color: {CREDIT_COLOR}; }}
  tr.unsettled td {{ color: #8a97a5; }}
  .badge {{ font-size: 7.5px; padding: 1px 5px; white-space: nowrap; border-radius: 3px; }}
  .badge {{ background: #e8ecf0; color: #4a5866; }}
  .badge.paid, .badge.successful {{ background: #e3f3e8; color: {CREDIT_COLOR}; }}
  .badge.pending {{ background: #fdf3dc; color: #8a5d00; }}
  .badge.failed {{ background: #fbe5e5; color: {DEBIT_COLOR}; }}
  tr.summary td {{ background: {ACCENT_SOFT}; font-weight: bold; }}
  .end {{ text-align: center; color: #5a6a7a; font-size: 8px; letter-spacing: 1px; margin-top: 12px; }}
  .foot {{ margin-top: 14px; font-size: 7.5px; color: #8a97a5; border-top: 1px solid #dfe5ec;
           padding-top: 6px; line-height: 1.5; }}
</style></head>
<body>
  <table class="head"><tr>
    <td>
      {logo}
      <div class="co-name">{e(company.name)}</div>
      <div class="co-lines">{company_lines}</div>
    </td>
    <td class="title">
      <h1>STATEMENT OF ACCOUNT</h1>
      <div class="period">
        Period: {e(formatdate(from_date))} &ndash; {e(formatdate(to_date))}<br>
        Statement date: {e(formatdate(generated_at))}
      </div>
    </td>
  </tr></table>

  <table class="meta"><tr>
    <td><div class="k">Account Name</div><div class="v">{e(wallet.wallet_name or wallet.name)}</div></td>
    <td><div class="k">Account Number</div><div class="v">{e(wallet.account_number or '')}</div></td>
    <td><div class="k">Bank</div><div class="v">{e(wallet.bank_name or 'BuyPower MFB')}</div></td>
    <td><div class="k">Currency</div><div class="v">{e(cur)}</div></td>
  </tr></table>

  <table class="summary-box">
    <tr><th class="k">Opening Balance</th><th class="k">Total Debits</th>
        <th class="k">Total Credits</th><th class="k">Closing Balance</th></tr>
    <tr>
      <td>{money(opening.get('balance'))}</td>
      <td class="debit">{money(total_debit)}<div class="n">{count(n_debits)}</div></td>
      <td class="credit">{money(total_credit)}<div class="n">{count(n_credits)}</div></td>
      <td class="closing">{money(closing_balance)}</td>
    </tr>
  </table>
  {note}

  <table class="txns">
    <thead><tr>
      <th class="dt">Date / Time</th><th class="ref">Reference</th><th>Narration</th><th class="status">Status</th>
      <th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th>
    </tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
  <div class="end">*** END OF STATEMENT ***</div>

  <div class="foot">
    All amounts are in {e(cur)}. Generated on {e(formatdate(generated_at))} at {e(format_time(generated_at, 'HH:mm'))}
    ({e(get_system_timezone())}) by {e(generated_by)}.
    This statement is computer generated from the transaction records of {e(wallet.wallet_name or wallet.name)}
    and does not require a signature. Please report any discrepancy within 30 days of receipt.
  </div>
</body></html>
"""


def _as_dict(row):
    return row if isinstance(row, dict) else dict(zip(COLUMNS, row))


def _company_details():
    """Letterhead details from the default Company; every field is optional."""
    name = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
    company = frappe.get_cached_doc("Company", name) if name and frappe.db.exists("Company", name) else None

    lines = []
    if company:
        from frappe.contacts.doctype.address.address import get_company_address

        address = get_company_address(company.name).get("company_address_display") or ""
        # Rendered address HTML uses <br> line breaks; collapse to one compact line
        address = ", ".join(
            html_lib.escape(html_lib.unescape(part.strip()))
            for part in frappe.utils.strip_html_tags(address.replace("<br>", "\n")).splitlines()
            if part.strip()
        )
        if address:
            lines.append(address)
        contact = " &middot; ".join(html_lib.escape(v) for v in (company.phone_no, company.email, company.website) if v)
        if contact:
            lines.append(contact)
        # registration_details is free text (e.g. "RC 123456"), so print it as entered
        registration = " ".join((company.registration_details or "").split())
        ids = " &middot; ".join(
            v for v in (
                html_lib.escape(registration),
                f"TIN: {html_lib.escape(company.tax_id)}" if company.tax_id else "",
            ) if v
        )
        if ids:
            lines.append(ids)

    logo_url = (company and company.company_logo) or frappe.db.get_single_value("Navbar Settings", "app_logo")
    return frappe._dict(
        name=(company and company.company_name) or name or "",
        lines=lines,
        logo=_data_uri(logo_url),
    )


def _data_uri(file_url):
    """Embed an image as a data URI so wkhtmltopdf never has to fetch it."""
    if not file_url:
        return ""
    try:
        if file_url.startswith("/assets/"):
            sites_dir = os.path.dirname(os.path.abspath(frappe.get_site_path()))
            with open(os.path.join(sites_dir, file_url.lstrip("/")), "rb") as f:
                content = f.read()
        else:
            content = frappe.get_doc("File", {"file_url": file_url}).get_content()
    except Exception:
        return ""
    if isinstance(content, str):
        content = content.encode()
    mime = mimetypes.guess_type(file_url)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"
