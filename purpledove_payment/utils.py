import json
import requests
import frappe
from dotenv import load_dotenv
import os
import subprocess
from frappe import _


@frappe.whitelist(allow_guest=True)
def wallet_log():
    try:
        # Get the incoming request data
        data = frappe.request.get_data(as_text=True)
        payload = json.loads(data)

        # Extract the "event" and "data" fields
        event = payload.get("event")
        transaction_data = payload.get("data", {})
        transaction_type = transaction_data.get("type")
        amount = float(transaction_data.get("amount", 0))

        # Get or create the Wallet Balance record
        try:
            wallet_balance_doc = frappe.get_single("Wallet Balance")
            current_balance = float(wallet_balance_doc.wallet_balance or 0)
        except frappe.DoesNotExistError:
            current_balance = 0
            wallet_balance_doc = None

        # Update wallet balance for INFLOW transactions
        if transaction_type == "INFLOW":
            new_balance = current_balance + amount
            
            # Update existing balance document
            if wallet_balance_doc:
                wallet_balance_doc.wallet_balance = new_balance
                wallet_balance_doc.save(ignore_permissions=True)
            else:
                # Create new balance record
                wallet_balance = frappe.get_doc({
                    "doctype": "Virtual Wallet Balance",
                    "wallet_balance": new_balance
                })
                wallet_balance.insert(ignore_permissions=True)
            
            frappe.db.commit()
        
        # Create wallet log entry
        wallet_log_doc = frappe.get_doc({
            "doctype": "Wallet Log",
            "event": event,
            "transaction_id": transaction_data.get("transaction_id"),
            "transaction_reference": transaction_data.get("transaction_reference"),
            "account_exchange_reference": transaction_data.get("account_exchange_reference"),
            "session_id": transaction_data.get("session_id"),
            "account_number": transaction_data.get("account_number"),
            "account_type": transaction_data.get("account_type"),
            "amount": amount,
            "source_account_name": transaction_data.get("source_account_name"),
            "source_account_number": transaction_data.get("source_account_number"),
            "source_bank_name": transaction_data.get("source_bank_name"),
            "source_bank_code": transaction_data.get("source_bank_code"),
            "destination_account_number": transaction_data.get("destination_account_number"),
            "destination_account_name": transaction_data.get("destination_account_name"),
            "destination_bank_name": transaction_data.get("destination_bank_name"),
            "destination_bank_code": transaction_data.get("destination_bank_code"),
            "transaction_type": transaction_type,
            "status": transaction_data.get("status"),
            "narration": transaction_data.get("narration"),
            "metadata": json.dumps(transaction_data.get("metadata", {}))
        })
        wallet_log_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return {"success": True, "message": "Wallet log created successfully"}

    except Exception as e:
        frappe.log_error(title="Wallet Log Error", message=str(e))
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def make_payment(**kwargs):
    try:
        # Retrieve parameters safely
        docname = kwargs.get("docname")
        amount = kwargs.get("amount")
        destination_bank_code = kwargs.get("destination_bank_code")
        custom_bank_name = kwargs.get("custom_bank_name")
        destination_account_number = kwargs.get("destination_account_number")
        
        if not all([amount, destination_bank_code, destination_account_number]):
            return {"error": "Missing required parameters"}

        # Convert amount to float
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return {"error": "Invalid amount format"}

        # Load the .env file
        current_path = subprocess.getoutput("pwd")
        env_path = os.path.join(current_path, ".env")
        load_dotenv(dotenv_path=env_path)

        # Retrieve the bearer token
        bearer_token = os.getenv("LIVE_TOKEN")
        if not bearer_token:
            frappe.log_error("Bearer token not found in .env file", "Bank Data Fetch Error")
            return {"error": "Bearer token not found in .env file"}

        # API details
        post_url = "https://api.core.payable.africa/api/banking/virtual/transfers"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

        # Prepare data for POST request
        post_data = {
            "destinationBankCode": destination_bank_code,
            "destinationAccountNumber": destination_account_number,
            "amount": amount,
            "sourceAccountNumber": "9000136910",
            "narration": "Salary Payment"
        }

        # Fetch Wallet Balance
        try:
            wallet = frappe.get_single("Wallet Balance")
            wallet_balance = float(wallet.wallet_balance or 0)
        except (ValueError, TypeError):
            wallet_balance = 0
            frappe.log_error("Invalid wallet balance when making payment", "Payment Error")

        # Validate if enough funds exist in the wallet
        if amount > wallet_balance:
            return {
                "error": f"Insufficient Funds. Your balance is {frappe.format_value(wallet_balance, 'Currency')}, "
                         f"but you are trying to transfer {frappe.format_value(amount, 'Currency')}."
            }

        # Send the API request
        response = requests.post(post_url, headers=headers, json=post_data, timeout=30)

        # Handle the API response
        if response.status_code == 200:
            response_data = response.json().get("data", {})
            if not response_data:
                frappe.log_error("Empty data received from API.", "Payment Data Fetch Error")
                return {"error": "No data received from the API."}
            
            # Deduct the amount from wallet balance after successful payment
            try:
                new_balance = wallet_balance - amount
                wallet.wallet_balance = new_balance
                wallet.save(ignore_permissions=True)
                frappe.db.commit()
                frappe.logger().info(f"Payment successful: Wallet balance updated from {wallet_balance} to {new_balance}")
            except Exception as e:
                frappe.log_error(f"Failed to update wallet balance after payment: {str(e)}", "Wallet Update Error")
            
            return {"info": "Payment made successfully", "data": response_data}
        else:
            error_message = f"Failed to POST data. Status Code: {response.status_code}, Response: {response.text[:200]}"
            frappe.log_error(error_message, "Payment POST Error")
            return {"error": error_message}

    except requests.RequestException as req_err:
        frappe.log_error(f"Request Exception: {str(req_err)}", "Payment Data Fetch Error")
        return {"error": "Request failed while making payment"}
    except Exception as e:
        error_message = str(e)[:200]
        frappe.log_error(error_message, "Payment Data Fetch Error")
        return {
            "error": f"An error occurred while making payment: {error_message}"
        }


@frappe.whitelist(allow_guest=True, xss_safe=True)
def fetch_and_save_banks(site_name=None):
    try:
        # Dynamically get the current working directory
        current_path = subprocess.getoutput("pwd")

        # Load .env file from the current path
        env_path = os.path.join(current_path, ".env")
        load_dotenv(dotenv_path=env_path)

        # Get the bearer token from the .env file
        bearer_token = os.getenv("TOKEN")
        if not bearer_token:
            frappe.log_error("Bearer token not found in .env file", "Bank Data Fetch Error")
            return {"status": "error", "message": "Bearer token not found in .env file"}

        # API details
        api_url = "https://api.core.demo.payable.africa/api/banking/core/banks"
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
                    bank_name = bank.get("bankName")
                    bank_code = bank.get("bankCode")
                    is_new = bank.get("isNew")

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
    
    
@frappe.whitelist(allow_guest=True)
def create_balance(site_name=None):
    try:
        default_company = frappe.defaults.get_default("company")

        if default_company:
            try:
                # Check if wallet already exists to avoid duplicates
                existing_wallet = frappe.db.exists("Wallet Balance", {"wallet_name": default_company})
                if existing_wallet:
                    return {"status": "success", "message": "Wallet already exists"}
                
                # Create and insert new wallet document
                doc = frappe.get_doc({
                    "doctype": "Wallet Balance",
                    "wallet_name": default_company,
                    "wallet_balance": 0.0
                })
                doc.insert(
                    ignore_permissions=True,
                    ignore_links=True,
                    ignore_if_duplicate=True,
                    ignore_mandatory=True
                )
                frappe.db.commit()
                return {"status": "success", "message": "Wallet created successfully"}
            
            except Exception as e:
                # Log error for any insertion failure
                frappe.log_error(f"Insert Error for wallet '{default_company}': {str(e)}", "Wallet Creation Error")
                return {"status": "error", "message": "Wallet creation failed"}

        else:
            return {"status": "error", "message": "Default company not found"}

    except Exception as e:
        # Log the exception message
        frappe.log_error(f"Unexpected Error: {str(e)}", "Wallet Creation Error")
        return {"status": "error", "message": str(e)}