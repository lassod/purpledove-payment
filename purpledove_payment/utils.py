import json
import hmac
import hashlib
import requests
import frappe
from dotenv import load_dotenv
import os
import subprocess
from frappe import _
from frappe.utils import flt


def _verify_webhook_signature(raw_body):
    """
    Verify a BuyPower MFB webhook signature (HMAC-SHA256 hex over the raw body).

    Behaviour:
      - If a signature header IS present, it MUST be valid (returns False on
        mismatch / missing secret).
      - If NO signature header is present (e.g. a trusted internal call
        forwarded by buypower_admin), verification is skipped and allowed.
    """
    try:
        headers = getattr(frappe.request, "headers", {}) or {}
        signature = headers.get("x-buypower-signature") or headers.get("x-panbox-signature")
    except Exception:
        signature = None

    if not signature:
        # No signature -> treat as a trusted/internal call.
        return True

    secret = frappe.conf.get("buypower_webhook_secret")
    if not secret:
        frappe.logger().warning("Webhook signature present but no buypower_webhook_secret configured")
        return False

    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    computed = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def _handle_inflow(event, data):
    """Credit a Virtual Wallet when its reserved account receives an inflow."""
    amount_obj = data.get("amount", {})
    amount = flt(amount_obj.get("value")) if isinstance(amount_obj, dict) else flt(amount_obj)

    destination = data.get("destination", {}) or {}
    account_number = destination.get("accountNumber") or data.get("accountNumber")
    if not account_number:
        return {"success": False, "error": "No destination account number in payload"}

    wallet_name = frappe.db.get_value("Virtual Wallet", {"account_number": account_number}, "name")
    if not wallet_name:
        frappe.logger().info(f"Inflow ignored: no Virtual Wallet for account {account_number}")
        return {"success": True, "message": "No matching wallet"}

    wallet_doc = frappe.get_doc("Virtual Wallet", wallet_name)
    new_balance = flt(wallet_doc.balance or 0) + amount
    wallet_doc.db_set("balance", new_balance, commit=True)
    return {"success": True, "message": "Wallet credited", "balance": new_balance}


def _reverse_failed_transfer(reference):
    """Credit the source wallet back when a transfer fails (funds reversed)."""
    th = frappe.db.get_value(
        "Transaction History",
        {"transaction_reference": reference},
        ["amount", "source_account_number"],
        as_dict=True,
    )
    if not th or not th.source_account_number:
        return

    wallet_name = frappe.db.get_value(
        "Virtual Wallet", {"account_number": th.source_account_number}, "name"
    )
    if not wallet_name:
        return

    wallet_doc = frappe.get_doc("Virtual Wallet", wallet_name)
    new_balance = flt(wallet_doc.balance or 0) + flt(th.amount or 0)
    wallet_doc.db_set("balance", new_balance, commit=True)
    frappe.logger().info(f"Reversed failed transfer {reference}: +{th.amount} to {wallet_name}")


def _handle_transfer_update(event, data):
    """Update Transaction History (and reverse balance on failure)."""
    from purpledove_payment.purpledove_payment.doctype.transaction_history.transaction_history import (
        TransactionHistory,
    )

    reference = data.get("reference")
    status = (data.get("status") or event.split(".")[-1] or "").lower()
    status_map = {"paid": "Successful", "pending": "Pending", "failed": "Failed"}
    mapped_status = status_map.get(status, "Pending")

    if reference:
        TransactionHistory.update_status(reference, mapped_status, data)
        if status == "failed":
            _reverse_failed_transfer(reference)

    return {"success": True, "message": f"Transfer {status} processed"}


@frappe.whitelist(allow_guest=True)
def wallet_log():
    """
    BuyPower MFB webhook receiver.

    Handles (v2 `{type, data}` and legacy `{event, data}`):
      - static_account.transaction.created / invoice.paid -> credit wallet
      - transfer.pending | transfer.paid | transfer.failed -> update history
    """
    try:
        raw = frappe.request.get_data()  # raw bytes (needed for signature)

        if not _verify_webhook_signature(raw):
            frappe.local.response["http_status_code"] = 401
            return {"success": False, "error": "Invalid webhook signature"}

        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)

        # v2 uses "type"; legacy uses "event"
        event = payload.get("type") or payload.get("event")
        data = payload.get("data", {}) or {}

        if event in ("static_account.transaction.created", "invoice.paid"):
            result = _handle_inflow(event, data)
        elif event in ("transfer.pending", "transfer.paid", "transfer.failed"):
            result = _handle_transfer_update(event, data)
        else:
            frappe.logger().info(f"Unhandled BuyPower webhook event: {event}")
            result = {"success": True, "message": f"Event '{event}' acknowledged"}

        frappe.db.commit()
        return result

    except Exception as e:
        frappe.log_error(title="Wallet Log Error", message=str(e))
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=True, xss_safe=True)
def fetch_and_save_banks(site_name=None):
    try:
        # Dynamically get the current working directory
        current_path = subprocess.getoutput("pwd")

        # Load .env file from the current path
        env_path = os.path.join(current_path, ".env")
        load_dotenv(dotenv_path=env_path)

        # Get the bearer token (BuyPower MFB first, legacy last)
        bearer_token = (
            os.getenv("BUYPOWER_TOKEN")
            or os.getenv("BP_TOKEN")
            or frappe.conf.get("buypower_token")
            or os.getenv("TOKEN")
        )
        if not bearer_token:
            frappe.log_error("Bearer token not found", "Bank Data Fetch Error")
            return {"status": "error", "message": "Bearer token not found"}

        # BuyPower MFB banks list
        base_url = (
            frappe.conf.get("buypower_base_url")
            or os.getenv("BP_BASE")
            or "https://api.buypowermfb.net"
        ).rstrip("/")
        api_url = f"{base_url}/v2/banking/banks"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json"
        }

        # Make the API request
        response = requests.get(api_url, headers=headers, timeout=30)
        if response.status_code == 200:
            try:
                # Parse the response JSON
                response_data = response.json()
                banks = response_data.get("data", [])

                for bank in banks:
                    bank_name = bank.get("name") or bank.get("bankName")
                    bank_code = bank.get("code") or bank.get("bankCode")
                    is_new = bank.get("isNew", 0)

                    if bank_name and bank_code:
                        # Check for duplicate entry using bank_code
                        existing_bank = frappe.db.exists("BanksB", {"bank_code": bank_code})
                        if not existing_bank:
                            try:
                                # Create and insert new bank document
                                doc = frappe.get_doc({
                                    "doctype": "BanksB",
                                    "bank_name": bank_name,
                                    "bank_code": bank_code,
                                    "new": is_new
                                })
                                doc.insert(
                                    ignore_permissions=True,
                                    ignore_links=True,
                                    ignore_if_duplicate=True,
                                    ignore_mandatory=True
                                )
                                frappe.db.commit()
                                
                            except Exception as e:
                                # Log error for any insertion failure
                                frappe.log_error(f"Insert Error for {bank_name} ({bank_code}): {str(e)}", "Bank Data Save Error")
                        else:
                            frappe.log_error(f"Duplicate bank entry skipped: {bank_name} ({bank_code})", "Bank Data Duplicate")
                    else:
                        frappe.log_error(f"Invalid bank data: {bank}", "Bank Data Validation Error")

                # Return success response
                return {
                    "status": "ok",
                    "message": "Banks successfully retrieved and saved",
                    "data_count": len(banks)
                }

            except Exception as e:
                frappe.log_error(f"JSON Parsing Error: {str(e)}", "Bank Data Fetch Error")
                return {"status": "error", "message": "Failed to parse API response"}
        else:
            # Log an error if the API call fails
            error_message = f"API call failed. Status Code: {response.status_code}, Response: {response.text[:200]}"
            frappe.log_error(error_message, "Bank Data Fetch Error")
            return {"status": "error", "message": "Failed to fetch data from API"}

    except Exception as e:
        # Log the exception message
        frappe.log_error(f"Unexpected Error: {str(e)[:200]}", "Bank Data Fetch Error")
        return {"status": "error", "message": str(e)}
    
        return {"status": "error", "message": str(e)}