# Copyright (c) 2026, Purpledove and contributors
# For license information, please see license.txt

import base64
import html as html_lib
import os

import frappe
from frappe.utils import fmt_money, formatdate, now_datetime
from frappe.utils.pdf import get_pdf

REPORT_NAME = "Wallet Statement of Account"


@frappe.whitelist()
def wallet_statement(wallet, from_date, to_date):
    """Download a bank-style PDF statement for a Virtual Wallet."""
    result = frappe.desk.query_report.run(
        REPORT_NAME,
        filters={"wallet": wallet, "from_date": from_date, "to_date": to_date},
    )
    rows = result.get("result") or []
    wallet_doc = frappe.get_doc("Virtual Wallet", wallet)

    pdf = get_pdf(
        build_html(wallet_doc, rows, from_date, to_date),
        {"orientation": "Portrait", "margin-top": "12mm", "margin-bottom": "14mm",
         "margin-left": "10mm", "margin-right": "10mm"},
    )

    frappe.local.response.filecontent = pdf
    frappe.local.response["type"] = "download"
    frappe.local.response["doctype"] = "Virtual Wallet"
    frappe.local.response["name"] = wallet_doc.name
    frappe.local.response["filename"] = (
        f"statement-{frappe.scrub(wallet_doc.name)}-{from_date}-to-{to_date}.pdf"
    )


def build_html(wallet, rows, from_date, to_date):
    e = html_lib.escape
    cur = wallet.currency or "NGN"
    logo = _logo_data_uri()

    body_rows = []
    for r in rows:
        summary = bool(r.get("description", "").startswith(("Opening Balance", "Closing Balance")))
        cells = "".join(
            f"<td class='{cls}'>{val}</td>"
            for cls, val in (
                ("dt", e(str(r.get("date_time") or "")[:16])),
                ("desc", e(str(r.get("description") or ""))),
                ("ref", e(str(r.get("reference") or ""))),
                ("status", e(str(r.get("status") or ""))),
                ("num", fmt_money(r.get("debit") or 0, currency=cur) if r.get("debit") else ""),
                ("num", fmt_money(r.get("credit") or 0, currency=cur) if r.get("credit") else ""),
                ("num bal", fmt_money(r.get("balance") or 0, currency=cur)),
            )
        )
        body_rows.append(f"<tr class='{'summary' if summary else ''}'>{cells}</tr>")

    closing = rows[-1] if rows else {}
    opening = rows[0] if rows else {}
    total_debit = sum(flt_or_zero(r.get("debit")) for r in rows[1:-1]) if len(rows) > 2 else 0
    total_credit = sum(flt_or_zero(r.get("credit")) for r in rows[1:-1]) if len(rows) > 2 else 0

    return f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 9.5px; color: #1a1a1a; }}
  .head {{ display: flex; justify-content: space-between; align-items: center;
           border-bottom: 3px solid #123c6b; padding-bottom: 8px; }}
  .head img {{ max-height: 52px; }}
  .head h1 {{ font-size: 19px; color: #123c6b; margin: 0; letter-spacing: 1.5px; }}
  .meta {{ margin: 12px 0 4px; width: 100%; }}
  .meta td {{ padding: 2px 10px 2px 0; font-size: 10px; }}
  .meta .lbl {{ color: #5a6a7a; width: 110px; }}
  .meta .val {{ font-weight: bold; }}
  table.txns {{ width: 100%; border-collapse: collapse; margin-top: 10px;
                table-layout: fixed; }}
  table.txns th {{ background: #123c6b; color: #fff; font-size: 9px; text-align: left;
                   padding: 5px 6px; }}
  table.txns td {{ border-bottom: 1px solid #dfe5ec; padding: 4px 6px; vertical-align: top;
                   overflow-wrap: anywhere; }}
  td.dt {{ white-space: nowrap; width: 88px; }}
  td.desc {{ width: 36%; }}
  td.ref {{ font-family: monospace; font-size: 8px; width: 158px; }}
  td.num, th.num {{ text-align: right; white-space: nowrap; width: 92px; }}
  td.status {{ width: 72px; }}
  tr.summary td {{ background: #eef2f7; font-weight: bold; border-top: 1.5px solid #123c6b;
                   border-bottom: 1.5px solid #123c6b; }}
  .summary-boxes {{ margin-top: 14px; width: 100%; }}
  .summary-boxes td {{ width: 25%; background: #f4f7fa; border: 1px solid #d5dde6;
                       padding: 7px 9px; text-align: center; }}
  .summary-boxes .k {{ font-size: 8px; color: #5a6a7a; text-transform: uppercase;
                       letter-spacing: 0.5px; }}
  .summary-boxes .v {{ font-size: 12px; font-weight: bold; color: #123c6b; margin-top: 2px; }}
  .foot {{ margin-top: 18px; font-size: 8px; color: #8a97a5; text-align: center;
           border-top: 1px solid #dfe5ec; padding-top: 6px; }}
</style></head>
<body>
  <div class="head">
    {f'<img src="{logo}"/>' if logo else ''}
    <h1>STATEMENT OF ACCOUNT</h1>
  </div>
  <table class="meta">
    <tr><td class="lbl">Account Name</td><td class="val">{e(wallet.wallet_name or wallet.name)}</td>
        <td class="lbl">Statement Period</td><td class="val">{e(str(formatdate(from_date)))} to {e(str(formatdate(to_date)))}</td></tr>
    <tr><td class="lbl">Account Number</td><td class="val">{e(wallet.account_number or '')}</td>
        <td class="lbl">Generated At</td><td class="val">{e(now_datetime().strftime('%d %b %Y %H:%M UTC'))}</td></tr>
    <tr><td class="lbl">Bank</td><td class="val">{e(wallet.bank_name or 'BuyPower MFB')}</td>
        <td class="lbl">Currency</td><td class="val">{e(cur)}</td></tr>
  </table>
  <table class="txns">
    <thead><tr>
      <th>Date</th><th>Description</th><th>Reference</th><th>Status</th>
      <th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th>
    </tr></thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table>
  <table class="summary-boxes"><tr>
    <td><div class="k">Opening Balance</div><div class="v">{fmt_money(opening.get('balance') or 0, currency=cur)}</div></td>
    <td><div class="k">Total Debits</div><div class="v">{fmt_money(total_debit, currency=cur)}</div></td>
    <td><div class="k">Total Credits</div><div class="v">{fmt_money(total_credit, currency=cur)}</div></td>
    <td><div class="k">Closing Balance</div><div class="v">{fmt_money(closing.get('balance') or 0, currency=cur)}</div></td>
  </tr></table>
  <div class="foot">
    This statement is computer generated from the transaction records of {e(wallet.wallet_name or wallet.name)}
    and reflects movements captured as at the generation time. Please report any discrepancy promptly.
  </div>
</body></html>
"""


def flt_or_zero(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0


def _logo_data_uri():
    path = frappe.db.get_single_value("Navbar Settings", "app_logo")
    if not path:
        return ""
    sites_dir = os.path.dirname(frappe.get_site_path())
    full = os.path.join(sites_dir, path.lstrip("/"))
    if not os.path.exists(full):
        return ""
    with open(full, "rb") as f:
        return "data:image/svg+xml;base64," + base64.b64encode(f.read()).decode()
