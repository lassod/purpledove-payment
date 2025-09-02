# Copyright (c) 2025, Ejiroghene Douglas Dominic and contributors
# For license information, please see license.txt

import os
import json
import time
import requests
import frappe
from frappe.model.document import Document
from frappe.utils import get_site_name, flt, fmt_money

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If dotenv is not available, continue without it
    pass


class VirtualPayment(Document):
    """Virtual Payment document for processing bank transfers"""
    
    # API Configuration
    API_BASE_URL = "https://api.core.payable.africa/api/banking"
    DEFAULT_WALLET_ACCOUNT = "9000136910"
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_DELAYS = [2, 5, 10]
    
    def __init__(self, *args, **kwargs):
        """Initialize the VirtualPayment document"""
        super().__init__(*args, **kwargs)
    
    def _get_bearer_token(self):
        """Get bearer token from environment variables"""
        # Try multiple ways to get the token
        token = os.environ.get('LIVE_TOKEN') or os.environ.get('PAYABLE_LIVE_TOKEN')
        
        if not token:
            # Fallback to None if no token found - will trigger error
            token = None
        
        if not token:
            # Try with getattr on frappe.conf (Frappe's config)
            token = getattr(frappe.conf, 'live_token', None)
        
        if not token:
            # Check if it's in Frappe's site config
            token = frappe.db.get_single_value("System Settings", "live_token") if frappe.db else None
        
        if not token:
            frappe.log_error("LIVE_TOKEN not found in environment variables, frappe.conf, or System Settings", "Token Configuration Error")
            frappe.logger().error("Available environment variables: " + str(list(os.environ.keys())))
            return None
        
        frappe.logger().info(f"Successfully retrieved LIVE_TOKEN: {'*' * (len(str(token)) - 10) + str(token)[-10:]}")
        return token
    
    def _get_bank_code(self, bank_name):
        """
        Get bank code from bank name
        
        Args:
            bank_name: Name of the bank
            
        Returns:
            str: Bank code
            
        Raises:
            ValueError: If bank code not found
        """
        try:
            bank_doc = frappe.get_doc("BanksB", bank_name)
            if not bank_doc or not bank_doc.bank_code:
                raise ValueError(f"Bank code not found for: {bank_name}")
            return bank_doc.bank_code
        except Exception as e:
            frappe.log_error(f"Error retrieving bank info: {str(e)}", "Bank Retrieval Error")
            raise
    
    # ========== Wallet Management ==========
    
    
    # ========== Bank Verification ==========
    
    @frappe.whitelist(allow_guest=True, xss_safe=True)
    def process_bank_verification(self):
        """
        Process bank account verification using Payable Africa API
        
        Returns:
            dict: Verification result with account details
        """
        try:
            # Clear existing account name
            doc = frappe.get_doc(self.doctype, self.name)
            doc.db_set('destination_account_name', '', commit=True)
            
            # Get bearer token
            bearer_token = self._get_bearer_token()
            if not bearer_token:
                return {
                    "success": False,
                    "error": "Bearer token not found. Please contact administrator."
                }
            
            # Validate inputs
            if not all([hasattr(self, 'destination_bank'), 
                       hasattr(self, 'destination_account_number')]):
                return {
                    "success": False,
                    "error": "Bank and account number are required"
                }
            
            # Get bank code
            try:
                bank_code = self._get_bank_code(self.destination_bank)
            except Exception:
                return {
                    "success": False,
                    "error": "Unable to retrieve bank information"
                }
            
            # Validate account number
            account_number = str(self.destination_account_number)
            if len(account_number) < 10:
                return {
                    "success": False,
                    "error": "Invalid account number format"
                }
            
            # Make API request
            return self._verify_bank_account(bearer_token, bank_code, account_number, doc)
            
        except Exception as e:
            frappe.log_error(f"Bank verification error: {str(e)}", "Verification Process Error")
            return {
                "success": False,
                "error": f"Verification error: {str(e)}"
            }
    
    def _verify_bank_account(self, bearer_token, bank_code, account_number, doc):
        """Make bank verification API request"""
        url = f"{self.API_BASE_URL}/core/bank/resolve"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }
        params = {
            "bankCode": bank_code,
            "accountNumber": account_number
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                response_data = response.json()
                data = response_data.get('data', {})
                account_name = data.get('accountName', '').strip()
                bank_name = data.get('bankName', '').strip()
                
                if not account_name:
                    return {
                        "success": False,
                        "error": "Unable to retrieve account name"
                    }
                
                # Update document
                doc.db_set('destination_account_name', account_name, commit=True)
                
                # Notify clients
                frappe.publish_realtime(
                    'refresh_field',
                    {
                        'doctype': self.doctype,
                        'name': self.name,
                        'fieldname': 'destination_account_name'
                    }
                )
                
                return {
                    "success": True,
                    "message": "Account verification completed successfully.",
                    "account_name": account_name,
                    "bank_name": bank_name
                }
            else:
                frappe.log_error(f"Verification failed: {response.text}", "Bank Verification API Error")
                return {
                    "success": False,
                    "error": f"Verification failed with status code {response.status_code}"
                }
                
        except requests.RequestException as e:
            frappe.log_error(f"API request error: {str(e)}", "Network Error")
            return {
                "success": False,
                "error": "Network error occurred during verification"
            }
    
    # ========== Payment Processing ==========
    
    @frappe.whitelist(allow_guest=True, xss_safe=True)
    def make_virtual_payment(self, transaction_pin=None, virtual_wallet=None):
        """
        Process virtual payment with balance validation
        
        Args:
            transaction_pin: PIN for transaction authorization
            virtual_wallet: Selected virtual wallet for the payment
            
        Returns:
            dict: Payment processing result
        """
        try:
            # Use the provided virtual wallet or fall back to document's virtual wallet
            if virtual_wallet:
                payment_wallet = virtual_wallet
            else:
                # Get the first available virtual wallet
                wallet_list = frappe.get_list("Virtual Wallet", limit=1)
                if not wallet_list:
                    return {
                        "success": False,
                        "error": "No virtual wallets found. Please create a virtual wallet first."
                    }
                payment_wallet = wallet_list[0].name
            
            
            # Step 1: Verify transaction PIN first
            if not transaction_pin:
                return {
                    "success": False,
                    "error": "Transaction PIN is required for payment authorization"
                }
            
            pin_verification = self.verify_transaction_pin(payment_wallet, transaction_pin)
            if not pin_verification["success"]:
                return pin_verification
            
            # Step 2: Validate balance for the specific virtual wallet
            validation_result = self.validate_balance_for_wallet(payment_wallet)
            if not validation_result["success"]:
                return validation_result
            
            # Extract validated data
            current_balance = validation_result["current_balance"]
            payment_amount = validation_result["payment_amount"]
            wallet_doc = validation_result["wallet_doc"]
            account_number = validation_result["account_number"]
            
            # Step 3: Get bearer token
            bearer_token = self._get_bearer_token()
            if not bearer_token:
                return {"success": False, "error": "Bearer token not found"}
            
            # Step 4: Get bank code
            try:
                bank_code = self._get_bank_code(self.destination_bank)
            except Exception:
                return {"success": False, "error": "Bank code not found"}
            
            # Step 5: Process payment
            payment_result = self._process_payment_request(
                bearer_token, bank_code, payment_amount, account_number
            )
            
            if not payment_result["success"]:
                return payment_result
            
            # Step 6: Update virtual wallet balance
            new_balance = self._update_specific_wallet_balance(
                wallet_doc, current_balance, payment_amount
            )
            
            # Step 7: Create transaction history record
            transaction_ref = payment_result["response_data"].get("transactionReference")
            if transaction_ref:
                # Save transaction reference to document
                doc = frappe.get_doc(self.doctype, self.name)
                doc.db_set('transaction_reference', transaction_ref, commit=True)
                
                # Create transaction history record
                from purpledove_payment.purpledove_payment.doctype.transaction_history.transaction_history import TransactionHistory
                TransactionHistory.create_transaction_record(
                    payment_result["response_data"], 
                    self.name
                )
            
            return {
                "success": True,
                "message": (
                    f"Transfer of {fmt_money(payment_amount, currency='NGN')} completed successfully from virtual wallet {payment_wallet}. "
                    f"New balance: {fmt_money(new_balance, currency='NGN')}"
                ),
                "new_balance": new_balance,
                "transaction_data": payment_result["response_data"],
                "wallet_used": payment_wallet
            }
            
        except Exception as e:
            frappe.log_error(f"Payment Error: {str(e)}", "VirtualPayment Error")
            return {
                "success": False,
                "error": f"Payment error: {str(e)}"
            }
    
    def validate_balance_for_wallet(self, wallet_name):
        """
        Validate balance for a specific virtual wallet
        
        Args:
            wallet_name: Name of the virtual wallet to validate
            
        Returns:
            dict: Validation result with virtual wallet information
        """
        try:
            # Get the specific virtual wallet document
            wallet_doc = frappe.get_doc("Virtual Wallet", wallet_name)
            
            if not wallet_doc:
                return {
                    "success": False,
                    "error": f"Virtual wallet {wallet_name} not found"
                }
            
            # Get virtual wallet balance from the balance field
            current_balance = flt(wallet_doc.balance or 0.0)
                
            payment_amount = flt(self.amount or 0.0)
            
            # Validate payment amount
            if payment_amount <= 0:
                return {
                    "success": False,
                    "error": "Payment amount must be greater than zero."
                }
            
            # Check sufficient funds
            if payment_amount > current_balance:
                return {
                    "success": False,
                    "error": (
                        f"Insufficient Funds in virtual wallet {wallet_name}. "
                        f"Current balance is {fmt_money(current_balance, currency='NGN')}, "
                        f"but you are trying to transfer {fmt_money(payment_amount, currency='NGN')}. "
                        f"Please top up your virtual wallet or reduce the transfer amount."
                    )
                }
            
            account_number = wallet_doc.account_number or self.DEFAULT_WALLET_ACCOUNT
            
            return {
                "success": True,
                "current_balance": current_balance,
                "payment_amount": payment_amount,
                "wallet_doc": wallet_doc,
                "account_number": account_number
            }
            
        except Exception as e:
            frappe.log_error(f"Error validating virtual wallet balance: {str(e)}", "Virtual Wallet Validation Error")
            return {
                "success": False,
                "error": f"Error validating virtual wallet balance: {str(e)}"
            }
    
    def _update_specific_wallet_balance(self, wallet_doc, current_balance, payment_amount):
        """Update balance for a specific virtual wallet after successful payment"""
        try:
            new_balance = current_balance - payment_amount
            wallet_doc.balance = new_balance
            wallet_doc.save(ignore_permissions=True)
            
            frappe.logger().info(f"Virtual wallet balance updated: {current_balance} -> {new_balance}")
            return new_balance
            
        except Exception as e:
            frappe.log_error(f"Error updating wallet balance: {str(e)}", "Wallet Balance Update Error")
            raise Exception(f"Payment processed but failed to update wallet balance: {str(e)}")
    
    def _process_payment_request(self, bearer_token, bank_code, payment_amount, account_number):
        """Process the payment API request with retry logic"""
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }
        
        # Get bank code - try from field first, then from bank document
        destination_bank_code = self.destination_bank_code
        frappe.logger().info(f"Initial destination_bank_code from field: {destination_bank_code}")
        
        if not destination_bank_code and self.destination_bank:
            try:
                frappe.logger().info(f"Fetching bank code for bank: {self.destination_bank}")
                destination_bank_code = self._get_bank_code(self.destination_bank)
                frappe.logger().info(f"Retrieved bank code: {destination_bank_code}")
                
                # Update the field for future reference
                self.destination_bank_code = destination_bank_code
                
            except Exception as e:
                frappe.log_error(f"Could not get bank code for '{self.destination_bank}': {str(e)}", "Bank Code Error")
                frappe.logger().error(f"Bank code retrieval failed: {str(e)}")
        
        # Get source account number - use from field or default
        source_account = self.source_account_number or "9000136910"
        
        post_data = {
            "destinationBankCode": str(destination_bank_code) if destination_bank_code else "",
            "destinationAccountNumber": str(self.destination_account_number) if self.destination_account_number else "",
            "amount": float(self.amount) if self.amount else 0.0,
            "sourceAccountNumber": str(source_account),
            "narration": str(self.narration) if self.narration else "Payment Transfer"
        }
        
        # Validate request data and log any issues
        validation_errors = []
        if not destination_bank_code:
            validation_errors.append("destination_bank_code is missing or could not be retrieved")
        if not self.destination_account_number:
            validation_errors.append("destination_account_number is missing") 
        if not self.amount or self.amount <= 0:
            validation_errors.append(f"amount is invalid: {self.amount}")
        if len(str(self.destination_account_number)) != 10 if self.destination_account_number else True:
            validation_errors.append(f"destination_account_number should be 10 digits: {self.destination_account_number}")
            
        if validation_errors:
            error_msg = "Request validation failed: " + ", ".join(validation_errors)
            frappe.log_error(f"{error_msg}\nRequest data: {post_data}\nForm data: destination_bank={self.destination_bank}, destination_bank_code={self.destination_bank_code}, destination_account_number={self.destination_account_number}, amount={self.amount}, narration={self.narration}", "Payment Validation Error")
            frappe.logger().error(error_msg)
            return {"success": False, "error": error_msg}
        
        url = "https://api.core.payable.africa/api/banking/virtual/transfers"
        
        # Enhanced logging for debugging 502 errors
        frappe.logger().info("=== PAYMENT REQUEST DEBUG INFO ===")
        frappe.logger().info(f"URL: {url}")
        frappe.logger().info(f"Bearer Token: {bearer_token}")
        frappe.logger().info(f"Headers: {headers}")
        frappe.logger().info(f"Request payload: {json.dumps(post_data, indent=2)}")
        
        # Log exactly what Postman shows
        postman_equivalent = {
            "destinationBankCode": "100004",
            "destinationAccountNumber": "8169246969", 
            "amount": 100,
            "sourceAccountNumber": "9000136910",
            "narration": "[[randomLoremSentence]]"
        }
        frappe.logger().info(f"Postman equivalent would be: {json.dumps(postman_equivalent, indent=2)}")
        frappe.logger().info("=== END DEBUG INFO ===")
        
        # Validate that all required fields have valid values
        if not all([
            destination_bank_code,
            self.destination_account_number,
            self.amount and self.amount > 0,
            source_account
        ]):
            missing_fields = []
            if not destination_bank_code: missing_fields.append("destinationBankCode")
            if not self.destination_account_number: missing_fields.append("destinationAccountNumber")
            if not self.amount or self.amount <= 0: missing_fields.append("amount")
            if not source_account: missing_fields.append("sourceAccountNumber")
            
            return {
                "success": False, 
                "error": f"Missing or invalid required fields: {', '.join(missing_fields)}"
            }
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    url, headers=headers, json=post_data
                )
                
                frappe.logger().info(f"Response status: {response.status_code}")
                frappe.logger().info(f"Response content: {response.text}")
                
                result = self._handle_payment_response(response, attempt)
                
                if result.get("retry"):
                    time.sleep(self.RETRY_DELAYS[attempt])
                    continue
                    
                return result
                
            except requests.exceptions.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAYS[attempt])
                    continue
                return {"success": False, "error": "Payment request timed out"}
                
            except requests.exceptions.ConnectionError as e:
                frappe.log_error(f"Connection error on attempt {attempt + 1}: {str(e)}", "Payment Connection Error")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAYS[attempt])
                    continue
                return {"success": False, "error": f"Connection error occurred: {str(e)}"}
                
            except requests.RequestException as e:
                frappe.log_error(f"Request error on attempt {attempt + 1}: {str(e)}", "Payment Request Error")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAYS[attempt])
                    continue
                return {"success": False, "error": f"Network error occurred: {str(e)}"}
        
        return {"success": False, "error": "Max retries exceeded"}
    
    def _handle_payment_response(self, response, attempt):
        """Handle payment API response"""
        if response.status_code == 200:
            try:
                response_json = response.json()
                response_data = response_json.get("data", response_json)
                frappe.logger().info(f"Payment successful: {response_json}")
                return {"success": True, "response_data": response_data}
            except json.JSONDecodeError as e:
                frappe.log_error(f"Invalid JSON in successful response: {response.text}", "Payment JSON Error")
                return {"success": False, "error": "Invalid response format from payment gateway"}
        
        elif response.status_code == 502 and attempt < self.MAX_RETRIES - 1:
            frappe.logger().warning(f"502 error on attempt {attempt + 1}, will retry")
            return {"retry": True}
        
        else:
            error_message = f"Payment failed with status {response.status_code}"
            error_details = {
                "status_code": response.status_code,
                "response_text": response.text,
                "headers": dict(response.headers)
            }
            
            try:
                error_data = response.json()
                error_message = error_data.get('message', error_message)
                error_details["response_json"] = error_data
                
                # Log detailed error for debugging
                frappe.log_error(
                    f"Payment API Error: Status {response.status_code}\n"
                    f"Error message: {error_message}\n"
                    f"Full response: {response.text}\n"
                    f"Request headers: {response.request.headers}\n"
                    f"Request body: {response.request.body}",
                    "Payment API Error"
                )
                
            except json.JSONDecodeError:
                frappe.log_error(
                    f"Payment failed with status {response.status_code}\n"
                    f"Response: {response.text}\n"
                    f"Request headers: {response.request.headers}\n"
                    f"Request body: {response.request.body}",
                    "Payment API Error"
                )
            
            return {
                "success": False,
                "error": error_message,
                "status_code": response.status_code,
                "details": error_details
            }
    
    
    
    # ========== Utility Methods ==========
    
    @frappe.whitelist(allow_guest=True, xss_safe=True)
    def check_wallet_balance(self, wallet_name=None):
        """
        Check balance for a specific virtual wallet
        
        Args:
            wallet_name: Name of the virtual wallet to check
            
        Returns:
            dict: Current balance information for the wallet
        """
        try:
            # If no wallet specified, get first available wallet
            if not wallet_name:
                wallet_list = frappe.get_list("Virtual Wallet", limit=1)
                if not wallet_list:
                    return {
                        "success": False,
                        "error": "No virtual wallets found"
                    }
                wallet_name = wallet_list[0].name
            
            # Get the virtual wallet document
            wallet_doc = frappe.get_doc("Virtual Wallet", wallet_name)
            current_balance = flt(wallet_doc.balance or 0.0)
            
            return {
                "success": True,
                "current_balance": current_balance,
                "formatted_balance": fmt_money(current_balance, currency='NGN'),
                "message": f"Balance for {wallet_name}: {fmt_money(current_balance, currency='NGN')}",
                "wallet_name": wallet_name
            }
            
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "error": f"Virtual wallet '{wallet_name}' not found"
            }
        except Exception as e:
            frappe.log_error(f"Error checking wallet balance: {str(e)}", "Balance Check Error")
            return {
                "success": False,
                "error": f"Error checking wallet balance: {str(e)}"
            }    
    def verify_transaction_pin(self, wallet_name, transaction_pin):
        """
        Verify the transaction PIN for the specified virtual wallet
        
        Args:
            wallet_name: Name of the virtual wallet
            transaction_pin: PIN entered by the user
            
        Returns:
            dict: Verification result
        """
        try:
            # First check if the wallet exists and user has access
            try:
                wallet_doc = frappe.get_doc("Virtual Wallet", wallet_name)
                
                # Check role-based access
                if wallet_doc.role:
                    user_roles = frappe.get_roles(frappe.session.user)
                    if wallet_doc.role not in user_roles:
                        return {
                            "success": False,
                            "error": f"You don't have permission to access this wallet. Required role: {wallet_doc.role}"
                        }
            except frappe.DoesNotExistError:
                return {
                    "success": False,
                    "error": f"Virtual wallet '{wallet_name}' not found"
                }
            
            # Get the Payment Pin record for this wallet
            pin_records = frappe.get_list(
                "Payment Pin",
                filters={"wallet": wallet_name},
                fields=["name"],
                limit=1
            )
            
            if not pin_records:
                return {
                    "success": False,
                    "error": "No PIN found for this wallet. Please set up a PIN first."
                }
            
            # Get the Payment Pin document
            pin_doc = frappe.get_doc("Payment Pin", pin_records[0].name)
            
            # Check if PIN exists in plain text (not encrypted yet)
            if pin_doc.pin:
                # Compare with plain text PIN
                if str(transaction_pin).strip() == str(pin_doc.pin).strip():
                    return {
                        "success": True,
                        "message": "PIN verified successfully"
                    }
                else:
                    return {
                        "success": False,
                        "error": "Incorrect PIN. Please try again."
                    }
            
            # Try to get the decrypted PIN if encrypted
            try:
                stored_pin = pin_doc.get_decrypted_pin()
                if stored_pin:
                    # Verify the PIN
                    if str(transaction_pin).strip() == str(stored_pin).strip():
                        return {
                            "success": True,
                            "message": "PIN verified successfully"
                        }
                    else:
                        return {
                            "success": False,
                            "error": "Incorrect PIN. Please try again."
                        }
                else:
                    return {
                        "success": False,
                        "error": "PIN not properly configured. Please reset your PIN."
                    }
            except Exception as e:
                frappe.log_error(f"PIN decryption error: {str(e)}", "PIN Decryption Error")
                return {
                    "success": False,
                    "error": "Unable to verify PIN. Please contact administrator or reset your PIN."
                }
                
        except Exception as e:
            frappe.log_error(f"PIN verification error: {str(e)}", "PIN Verification Error")
            return {
                "success": False,
                "error": f"PIN verification failed: {str(e)}"
            }
    
    @frappe.whitelist(allow_guest=True, xss_safe=True)
    def check_transaction_status_api(self, transaction_reference):
        """
        Check transaction status using Payable Africa API
        
        Args:
            transaction_reference: Transaction reference to check
            
        Returns:
            dict: Transaction status information
        """
        try:
            if not transaction_reference:
                return {
                    "success": False,
                    "error": "Transaction reference is required"
                }
            
            # Get bearer token
            bearer_token = self._get_bearer_token()
            if not bearer_token:
                return {
                    "success": False,
                    "error": "Bearer token not found"
                }
            
            # API endpoint for checking transaction status
            url = f"{self.API_BASE_URL}/virtual/transfers/status"
            
            headers = {
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json",
            }
            
            params = {
                "transactionReference": transaction_reference
            }
            
            frappe.logger().info(f"Checking transaction status for: {transaction_reference}")
            
            try:
                response = requests.get(url, headers=headers, params=params)
                
                frappe.logger().info(f"Status check response: {response.status_code}")
                frappe.logger().info(f"Status check content: {response.text}")
                
                if response.status_code == 200:
                    response_data = response.json()
                    data = response_data.get('data', response_data)
                    
                    # Update Transaction History status if found
                    try:
                        from purpledove_payment.purpledove_payment.doctype.transaction_history.transaction_history import TransactionHistory
                        
                        # Map API status to our status options
                        status_mapping = {
                            'SUCCESSFUL': 'Successful',
                            'SUCCESS': 'Successful',
                            'PENDING': 'Pending', 
                            'PROCESSING': 'Processing',
                            'FAILED': 'Failed',
                            'CANCELLED': 'Cancelled'
                        }
                        
                        api_status = (data.get('status') or data.get('transactionStatus') or '').upper()
                        mapped_status = status_mapping.get(api_status, 'Pending')
                        
                        TransactionHistory.update_status(
                            transaction_reference, 
                            mapped_status, 
                            data
                        )
                    except Exception as e:
                        frappe.log_error(f"Error updating transaction status: {str(e)}", "Status Update Error")
                    
                    return {
                        "success": True,
                        "data": data,
                        "message": "Transaction status retrieved successfully"
                    }
                elif response.status_code == 404:
                    return {
                        "success": False,
                        "error": "Transaction not found"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Status check failed with code {response.status_code}"
                    }
                    
            except requests.RequestException as e:
                frappe.log_error(f"Status check request error: {str(e)}", "Transaction Status Error")
                return {
                    "success": False,
                    "error": "Network error occurred while checking status"
                }
                
        except Exception as e:
            frappe.log_error(f"Transaction status check error: {str(e)}", "Status Check Error")
            return {
                "success": False,
                "error": f"Status check error: {str(e)}"
            }
