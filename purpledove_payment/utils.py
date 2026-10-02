import json
import hmac
import hashlib
import requests
import frappe
import os
import subprocess
from frappe import _
from frappe.utils import flt

# python-dotenv is an optional convenience for loading a local .env file.
# Never let its absence break this module (webhook receiver + bank fetch):
# fall back to a no-op so credentials can still be read from frappe.conf /
# already-exported environment variables.
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False


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
        # No secret configured — cannot verify. Allow through and warn.
        frappe.logger().warning(
            "Webhook received with signature header but buypower_webhook_secret is not configured — "
            "treating as trusted. Set buypower_webhook_secret in site_config.json to enforce verification."
        )
        return True

    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    computed = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def _handle_inflow(event, data):
    """Credit a Virtual Wallet when its reserved account receives an inflow."""
    # BuyPower MFB amounts are in naira.
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

    # Atomic increment: the single UPDATE holds the row lock, so concurrent
    # webhook workers can no longer clobber each other's credits (the old
    # read-modify-write lost ~65M naira of credits during bulk-inflow bursts).
    frappe.db.sql(
        "UPDATE `tabVirtual Wallet` SET balance = ROUND(balance + %s, 2), modified = %s WHERE name = %s",
        (amount, frappe.utils.now_datetime(), wallet_name),
    )
    new_balance = frappe.db.get_value("Virtual Wallet", wallet_name, "balance")
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

    frappe.db.sql(
        "UPDATE `tabVirtual Wallet` SET balance = ROUND(balance + %s, 2), modified = %s WHERE name = %s",
        (flt(th.amount or 0), frappe.utils.now_datetime(), wallet_name),
    )
    frappe.logger().info(f"Reversed failed transfer {reference}: +{th.amount} to {wallet_name}")


def _handle_transfer_update(event, data):
    """Update Transaction History (and reverse balance on failure)."""
    from purpledove_payment.purpledove_payment.doctype.transaction_history.transaction_history import (
        TransactionHistory,
    )

    reference = data.get("reference")
    status = (data.get("status") or event.split(".")[-1] or "").lower()
    status_map = {"paid": "Successful", "pending": "Pending", "failed": "Failed", "confirmed": "Successful", "successful": "Successful"}
    mapped_status = status_map.get(status, "Pending")

    if reference:
        TransactionHistory.update_status(reference, mapped_status, data)
        if status == "failed":
            _reverse_failed_transfer(reference)

    return {"success": True, "message": f"Transfer {status} processed"}


def _record_payment_log(event, data, payload):
    """
    Persist a Purpledove Payment Log entry for the webhook event.
    Uses same structure as Purpledove Admin Log - accepts any event type.

    Defensive by design: any failure here MUST NOT break webhook processing,
    so all errors are swallowed (and logged) rather than raised.
    """
    try:
        source = data.get("source", {}) or {}
        destination = data.get("destination", {}) or {}
        amount_obj = data.get("amount", {})
        amount = float(amount_obj.get("value", 0)) if isinstance(amount_obj, dict) else float(amount_obj or 0)
        metadata = data.get("metadata", {}) or {}

        # Accept any event type - no restrictions. Same precedence rule as the
        # event routing below: 'transfer.paid' contains 'paid' and must not be
        # classified as an inflow.
        event_name = (event or "").lower()
        is_transfer = "transfer" in event_name or "outflow" in event_name
        is_inflow = not is_transfer and (
            "inflow" in event_name or "created" in event_name or "paid" in event_name
        )
        transaction_type = "OUTFLOW" if is_transfer else ("INFLOW" if is_inflow else "")

        # Use raw status from webhook (no mapping)
        log_status = data.get("status") or (event.split(".")[-1] if event else "")

        # Determine our account number (same logic as admin)
        if is_inflow:
            our_account = destination.get("accountNumber")
        else:
            our_account = source.get("accountNumber") or metadata.get("source_account_number")
        our_account = our_account or data.get("accountNumber")

        frappe.get_doc({
            "doctype": "Purpledove Payment Log",
            "event": event,
            "transaction_id": data.get("transactionId", 0),
            "transaction_reference": data.get("reference") or data.get("transactionReference"),
            "account_exchange_reference": data.get("accountExchangeReference"),
            "session_id": data.get("sessionId"),
            "account_number": our_account,
            "account_type": data.get("type") or data.get("accountType"),
            "amount": amount,
            "source_account_name": source.get("accountName") or data.get("sourceAccountName"),
            "source_account_number": source.get("accountNumber") or data.get("sourceAccountNumber"),
            "source_bank_name": source.get("bankName") or data.get("sourceBankName"),
            "source_bank_code": source.get("bankCode") or data.get("sourceBankCode"),
            "destination_account_number": destination.get("accountNumber") or data.get("destinationAccountNumber"),
            "destination_account_name": destination.get("accountName") or data.get("destinationAccountName"),
            "destination_bank_name": destination.get("bankName") or data.get("destinationBankName"),
            "destination_bank_code": destination.get("bankCode") or data.get("destinationBankCode"),
            "transaction_type": transaction_type,
            "status": log_status,
            "narration": data.get("narration"),
            "created_at": data.get("createdAt"),
            "updated_at": data.get("updatedAt"),
            "metadata": json.dumps(metadata),
            "data_details": json.dumps(payload),
        }).insert(ignore_permissions=True)
    except Exception as log_error:
        frappe.log_error(title="Payment Log Insert Error", message=str(log_error))


@frappe.whitelist(allow_guest=True)
def wallet_log():
    """
    BuyPower MFB webhook receiver.
    Accepts any event type - no restrictions.
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

        # Idempotency: BuyPower and buypower_admin may redeliver events
        # (retries, manual resends). Dedupe on (reference, event) so a
        # redelivered inflow cannot double-credit a wallet and a redelivered
        # failure cannot double-reverse. Distinct events for one reference
        # (transfer.pending -> transfer.paid) still process normally.
        reference = data.get("reference") or data.get("transactionReference")
        if reference and event and frappe.db.exists(
            "Purpledove Payment Log",
            {"transaction_reference": reference, "event": event},
        ):
            _record_payment_log(event, data, payload)
            frappe.db.commit()
            return {"success": True, "message": "Duplicate event ignored"}

        # Keep an audit trail of every webhook on the client side.
        _record_payment_log(event, data, payload)

        # Process wallet operations based on event type. Transfer events are
        # checked FIRST: 'transfer.paid' contains the substring 'paid', which
        # would otherwise match the inflow test and route status updates to
        # the (wrong) inflow handler — that is why Transaction History rows
        # stayed Pending forever.
        event_name = (event or "").lower()
        is_transfer = "transfer" in event_name or "outflow" in event_name
        is_inflow = not is_transfer and (
            "inflow" in event_name or "created" in event_name or "paid" in event_name
        )

        if is_transfer:
            result = _handle_transfer_update(event, data)
        elif is_inflow:
            result = _handle_inflow(event, data)
        else:
            # Acknowledge any other event type
            result = {"success": True, "message": f"Event '{event}' logged"}

        frappe.db.commit()
        return result

    except Exception as e:
        frappe.log_error(title="Wallet Log Error", message=str(e))
        return {"success": False, "error": str(e)}


def _seed_required_banks():
    """Ensure critical banks that may be missing from the API response are present."""
    required = [
        {"bank_name": "BuyPower Microfinance Bank", "bank_code": "090682", "new": 0},
    ]
    for bank in required:
        if not frappe.db.exists("BanksB", {"bank_code": bank["bank_code"]}):
            try:
                frappe.get_doc({"doctype": "BanksB", **bank}).insert(
                    ignore_permissions=True,
                    ignore_links=True,
                    ignore_if_duplicate=True,
                    ignore_mandatory=True,
                )
                frappe.db.commit()
            except Exception as e:
                frappe.log_error(title="Bank Seed Error", message=str(e))


@frappe.whitelist(allow_guest=True, xss_safe=True)
def fetch_and_save_banks(app_name=None, *args, **kwargs):
    # `after_app_install` passes the installed app's name as the first
    # positional argument; `after_migrate` passes nothing; manual calls pass
    # nothing. Accept all of them. When triggered by another app's install,
    # skip so we only run for our own app.
    if app_name and isinstance(app_name, str) and app_name not in ("purpledove_payment",):
        return {"status": "skipped", "message": f"Not triggered for purpledove_payment (got '{app_name}')"}

    _seed_required_banks()

    try:
        # Look for a .env beside the bench root (cwd) and inside the sites dir.
        candidate_env_paths = [
            os.path.join(os.getcwd(), ".env"),
            os.path.join(os.getcwd(), "sites", ".env"),
        ]
        for env_path in candidate_env_paths:
            if os.path.exists(env_path):
                load_dotenv(dotenv_path=env_path)
                break

        # Get the bearer token. The default base URL is production, so prefer
        # the live token over the sandbox TOKEN. Explicit overrides
        # (BUYPOWER_TOKEN / BP_TOKEN / site config) still win.
        bearer_token = (
            os.getenv("BUYPOWER_TOKEN")
            or os.getenv("BP_TOKEN")
            or frappe.conf.get("buypower_token")
            or os.getenv("LIVE_TOKEN")
            or os.getenv("TOKEN")
        )
        # Values loaded from .env may carry surrounding quotes/whitespace.
        if bearer_token:
            bearer_token = bearer_token.strip().strip('"').strip("'").strip()
        if not bearer_token:
            frappe.log_error(message="Bearer token not found", title="Bank Data Fetch Error")
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
                                frappe.log_error(message=f"Insert Error for {bank_name} ({bank_code}): {str(e)}", title="Bank Data Save Error")
                        else:
                            frappe.log_error(message=f"Duplicate bank entry skipped: {bank_name} ({bank_code})", title="Bank Data Duplicate")
                    else:
                        frappe.log_error(message=f"Invalid bank data: {bank}", title="Bank Data Validation Error")

                # Return success response
                return {
                    "status": "ok",
                    "message": "Banks successfully retrieved and saved",
                    "data_count": len(banks)
                }

            except Exception as e:
                frappe.log_error(message=f"JSON Parsing Error: {str(e)}", title="Bank Data Fetch Error")
                return {"status": "error", "message": "Failed to parse API response"}
        else:
            # Log an error if the API call fails
            error_message = f"API call failed. Status Code: {response.status_code}, Response: {response.text[:200]}"
            frappe.log_error(message=error_message, title="Bank Data Fetch Error")
            return {"status": "error", "message": "Failed to fetch data from API"}

    except Exception as e:
        # Log the exception message
        frappe.log_error(message=f"Unexpected Error: {str(e)[:200]}", title="Bank Data Fetch Error")
        return {"status": "error", "message": str(e)}

        return {"status": "error", "message": str(e)}


def reconcile_wallet_balances():
    """
    Sync every wallet's balance from BuyPower MFB. Runs daily via
    scheduler_events so residual drift (missed webhooks, races predating the
    atomic-credit fix) self-heals within a day.
    """
    wallets = frappe.get_all("Virtual Wallet", fields=["name"])
    ok = fail = 0
    for row in wallets:
        try:
            doc = frappe.get_doc("Virtual Wallet", row["name"])
            result = doc.fetch_remote_balance(update=True)
            if result.get("success"):
                ok += 1
            else:
                fail += 1
                frappe.log_error(
                    title="Wallet Reconciliation Failed",
                    message=f"Wallet '{row['name']}': {result.get('error')}",
                )
        except Exception as e:
            fail += 1
            frappe.log_error(
                title="Wallet Reconciliation Error",
                message=f"Wallet '{row['name']}': {str(e)}",
            )
    frappe.logger().info(f"reconcile_wallet_balances: {ok} synced, {fail} failed")
    return {"synced": ok, "failed": fail}


def re_register_all_wallets(app_name=None, *args, **kwargs):
    """
    Re-register every Virtual Wallet that has an account_number with buypower_admin.
    Called automatically on `bench migrate` via the after_migrate hook.
    """
    if app_name and isinstance(app_name, str) and app_name not in ("purpledove_payment",):
        return

    wallets = frappe.get_all(
        "Virtual Wallet",
        filters={"account_number": ["!=", ""]},
        fields=["name"],
    )

    ok = fail = 0
    for row in wallets:
        try:
            doc = frappe.get_doc("Virtual Wallet", row["name"])
            result = doc.re_register_with_admin()
            if result.get("success"):
                ok += 1
            else:
                fail += 1
                frappe.log_error(
                    title="Admin Re-registration Failed",
                    message=f"Wallet '{row['name']}': {result.get('message')}",
                )
        except Exception as e:
            fail += 1
            frappe.log_error(
                title="Admin Re-registration Error",
                message=f"Wallet '{row['name']}': {str(e)}",
            )

    frappe.logger().info(f"re_register_all_wallets: {ok} succeeded, {fail} failed")