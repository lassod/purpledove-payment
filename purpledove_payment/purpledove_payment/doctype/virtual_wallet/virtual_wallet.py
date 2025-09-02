# Copyright (c) 2025, Ejiroghene Dominic Douglas and contributors
# For license information, please see license.txt

import json
import os
import random
import subprocess
import requests
import frappe
from frappe.utils import get_site_name, now_datetime
from frappe.model.document import Document

class VirtualWallet(Document):
    def safe_log_error(self, data, title_prefix="Log", max_title_length=130):
        """
        Safely log errors with proper title length limits
        """
        # Ensure title doesn't exceed the limit
        if len(title_prefix) > max_title_length:
            title_prefix = title_prefix[:max_title_length-3] + "..."
        
        # Convert data to string if it's a dict/object
        if isinstance(data, (dict, list)):
            message = json.dumps(data, indent=2)
        else:
            message = str(data)
        
        # Truncate message if too long to prevent issues
        if len(message) > 3000:
            message = message[:3000] + "... (truncated)"
        
        # Log with safe parameters
        frappe.log_error(message=message, title=title_prefix)

    def validate_wallet_data(self):
        """Validate wallet data before API call"""
        errors = []
        
        # Validate wallet name
        if not self.wallet_name:
            errors.append("Wallet name is required")
        else:
            wallet_name = str(self.wallet_name).strip()
            if len(wallet_name) < 2:
                errors.append("Wallet name must be at least 2 characters")
            elif len(wallet_name) > 50:
                errors.append("Wallet name must be less than 50 characters")
            # Check for special characters that might cause issues
            elif not wallet_name.replace(' ', '').replace('-', '').replace('_', '').isalnum():
                errors.append("Wallet name should contain only letters, numbers, spaces, hyphens, and underscores")
        
        # Validate BVN
        if not self.bvn:
            errors.append("BVN is required")
        else:
            bvn_str = str(self.bvn).strip()
            if not bvn_str.isdigit():
                errors.append("BVN must contain only digits")
            elif len(bvn_str) != 11:
                errors.append(f"BVN must be exactly 11 digits (provided: {len(bvn_str)})")
        
        return errors

    def get_bearer_token(self):
        """Get bearer token using os library"""
        try:
            # Method 1: Use os.getenv() to get LIVE_TOKEN from environment
            bearer_token = os.getenv('LIVE_TOKEN')
            if bearer_token:
                return bearer_token.strip()
            
            # Method 2: Try os.environ.get() as fallback
            bearer_token = os.environ.get('LIVE_TOKEN')
            if bearer_token:
                return bearer_token.strip()
            
            # Method 3: Load .env file and set environment variables using os
            try:
                # Find .env file location
                env_file_path = None
                possible_paths = [
                    os.path.join(os.getcwd(), 'sites', '.env'),
                    os.path.join(os.path.dirname(os.getcwd()), 'sites', '.env'),
                    os.path.join(os.getcwd(), '.env'),
                    os.path.join(os.path.dirname(os.getcwd()), '.env'),
                ]
                
                for path in possible_paths:
                    if os.path.exists(path):
                        env_file_path = path
                        break
                
                if env_file_path:
                    # Read .env file and set environment variables
                    with open(env_file_path, 'r') as env_file:
                        for line in env_file:
                            line = line.strip()
                            if line and not line.startswith('#') and '=' in line:
                                key, value = line.split('=', 1)
                                key = key.strip()
                                value = value.strip().strip('"\'')
                                # Set environment variable using os
                                os.environ[key] = value
                    
                    # Now try to get LIVE_TOKEN again
                    bearer_token = os.getenv('LIVE_TOKEN')
                    if bearer_token:
                        return bearer_token.strip()
                        
            except Exception as e:
                self.safe_log_error(f"Error loading .env file: {str(e)}", "Env Load Error")
            
            # Method 4: Try from site configuration as fallback
            bearer_token = frappe.conf.get('LIVE_TOKEN')
            if bearer_token:
                return bearer_token.strip()
            
            self.safe_log_error("LIVE_TOKEN not found in environment variables", "Token Error")
            return None
            
        except Exception as e:
            self.safe_log_error(f"Error getting bearer token: {str(e)}", "Token Get Error")
            return None
    
    def on_trash(self):
        """Called when the document is being deleted"""
        try:
            self.unregister_from_client_wallet()
            self.delete_associated_pin()
        except Exception as e:
            # Use shorter error message for logging to avoid truncation
            error_msg = str(e)[:50]
            self.safe_log_error(f"Wallet deletion error: {error_msg}", "Wallet Del Error")
            # Don't prevent deletion even if unregistration fails
    
    def delete_associated_pin(self):
        """Delete associated Payment Pin when wallet is deleted"""
        try:
            # Find and delete associated PIN
            pin_records = frappe.get_list(
                "Payment Pin",
                filters={"wallet": self.name},
                fields=["name"]
            )
            
            for pin_record in pin_records:
                frappe.delete_doc("Payment Pin", pin_record.name, ignore_permissions=True)
                
            if pin_records:
                self.safe_log_error(
                    f"Deleted {len(pin_records)} PIN record(s) for wallet: {self.wallet_name}",
                    "PIN Records Deleted"
                )
                
        except Exception as e:
            self.safe_log_error(
                f"Error deleting PIN records: {str(e)[:50]}",
                "PIN Delete Error"
            )
    
    def unregister_from_client_wallet(self):
        """Unregister wallet from the client wallet system"""
        try:
            # Prepare payload for the Admin system
            admin_payload = {
                "event": "wallet_deleted",
                "data": {
                    "wallet_name": getattr(self, 'wallet_name', ''),
                    "account_number": getattr(self, 'account_number', ''),
                    "wallet_id": getattr(self, 'wallet_id', ''),
                    "site_name": getattr(self, 'site_name', '')
                }
            }
            
            post_url_admin = "https://lassod.purpledove.net/api/method/buypower_admin.buypower_admin.utils.client_wallet"
            admin_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            # Log the deletion request
            self.safe_log_error(
                f"Sending wallet deletion request for: {self.wallet_name}",
                "Delete Request"
            )
            
            admin_response = requests.post(
                post_url_admin, 
                headers=admin_headers, 
                json=admin_payload, 
                timeout=30
            )
            
            if admin_response.status_code in [200, 201]:
                try:
                    admin_response_json = admin_response.json()
                    admin_response_data = admin_response_json.get("message", admin_response_json)
                    
                    if admin_response_data and admin_response_data.get("success"):
                        self.safe_log_error(
                            f"Wallet {self.wallet_name} unregistered successfully", 
                            "Del Success"
                        )
                    else:
                        self.safe_log_error(
                            "Admin API failed wallet deletion", 
                            "Del Warning"
                        )
                        
                except Exception as parse_err:
                    self.safe_log_error(
                        f"Parse error: {str(parse_err)[:30]}", 
                        "Del Parse Error"
                    )
            else:
                error_msg = f"Admin API error: {admin_response.status_code}"
                self.safe_log_error(error_msg, "Del API Error")
                
        except requests.RequestException as req_err:
            self.safe_log_error(f"Request error: {str(req_err)[:30]}", "Del Req Error")
        except Exception as e:
            self.safe_log_error(f"Unexpected error: {str(e)[:30]}", "Del Error")
    
    def register_with_admin_system(self, wallet_data):
        """Register wallet with admin system using the single endpoint"""
        try:
            # Get site name with fallback
            try:
                site_name = get_site_name(frappe.local.site)
            except:
                site_name = frappe.conf.get('site_name', 'unknown_site')
            
            # Prepare admin payload for registration
            admin_payload = {
                "event": "wallet_created",
                "data": {
                    "wallet_name": str(wallet_data.get("name", self.wallet_name)),
                    "currency": str(wallet_data.get("currency", "NGN")),
                    "wallet_id": str(wallet_data.get("id", "")),
                    "description": str(wallet_data.get("description", self.description or "")),
                    "bvn": str(wallet_data.get("bvn", self.bvn)),
                    "account_number": str(wallet_data.get("accountNumber", "")),
                    "exchange_ref": str(wallet_data.get("exchangeRef", "")),
                    "business_id": str(wallet_data.get("businessId", "")),
                    "account_type": str(wallet_data.get("accountType", "static")),
                    "bank_code": str(wallet_data.get("bankCode", "")),
                    "bank_name": str(wallet_data.get("bankName", "")),
                    "site_name": str(site_name)
                }
            }

            # Use the single admin endpoint for all operations
            post_url_admin = "https://lassod.purpledove.net/api/method/buypower_admin.buypower_admin.utils.client_wallet"
            admin_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Frappe-Client/1.0"
            }

            # Log admin request details with safe logging
            self.safe_log_error(
                f"Sending admin request for wallet: {wallet_data.get('name', 'Unknown')}", 
                "Admin Request"
            )


            # Make the admin API request with proper error handling
            admin_response = requests.post(
                post_url_admin, 
                headers=admin_headers, 
                json=admin_payload, 
                timeout=30,
                verify=True
            )
            
            # Log response details with safe logging
            self.safe_log_error(
                f"Admin API Status: {admin_response.status_code}, Response: {admin_response.text[:150]}", 
                "Admin Response"
            )
            
            
            if admin_response.status_code in [200, 201]:
                try:
                    admin_response_json = admin_response.json()
                    
                    # Handle different response structures
                    if "message" in admin_response_json:
                        admin_response_data = admin_response_json["message"]
                    else:
                        admin_response_data = admin_response_json
                    
                    # Check for success in various possible locations
                    is_success = (
                        admin_response_data.get("success") or
                        admin_response_json.get("success") or
                        admin_response.status_code == 200
                    )
                    
                    if is_success:
                        self.safe_log_error(
                            f"Wallet {self.wallet_name} registered successfully with admin", 
                            "Admin Success"
                        )
                        return {"success": True, "message": "Registered with admin successfully"}
                    else:
                        error_detail = admin_response_data.get("message", "Unknown admin error")
                        self.safe_log_error(
                            f"Admin registration failed: {str(error_detail)[:100]}", 
                            "Admin Failed"
                        )
                        return {"success": False, "message": f"Admin registration failed: {error_detail}"}
                        
                except json.JSONDecodeError as parse_err:
                    self.safe_log_error(
                        f"Failed to parse admin response: {str(parse_err)}", 
                        "Admin Parse Error"
                    )
                    return {"success": False, "message": "Failed to parse admin response"}
                    
            elif admin_response.status_code == 417:
                # Specific handling for 417 error (character length exceeded)
                self.safe_log_error(
                    "Admin system has logging character limit issues", 
                    "Admin 417 Error"
                )
                return {"success": False, "message": "Admin system configuration error (character limit)"}
                
            else:
                error_msg = f"Admin API returned status {admin_response.status_code}: {admin_response.text[:100]}"
                self.safe_log_error(error_msg, "Admin API Error")
                return {"success": False, "message": error_msg}
                
        except requests.exceptions.Timeout:
            error_msg = "Admin API request timed out"
            self.safe_log_error(error_msg, "Admin Timeout")
            return {"success": False, "message": error_msg}
            
        except requests.exceptions.ConnectionError as conn_err:
            error_msg = f"Admin API connection error: {str(conn_err)[:100]}"
            self.safe_log_error(error_msg, "Admin Conn Error")
            return {"success": False, "message": error_msg}
            
        except Exception as e:
            error_msg = f"Unexpected admin registration error: {str(e)[:100]}"
            self.safe_log_error(error_msg, "Admin Reg Error")
            return {"success": False, "message": error_msg}

    @frappe.whitelist()
    def create_wallet(self):
        """
        Create a virtual wallet and register it with the client wallet system
        """
        try:
            # Validate input data first
            validation_errors = self.validate_wallet_data()
            if validation_errors:
                return {"error": "; ".join(validation_errors)}

            # Check if wallet already exists
            if self.wallet_id:
                return {"error": "Wallet already exists for this record"}

            # Get bearer token from environment or site config
            bearer_token = self.get_bearer_token()
            if not bearer_token:
                return {"error": "Bearer token not found in configuration"}

            # API details for creating the wallet
            post_url = "https://api.core.payable.africa/api/banking/virtual/accounts/reserved"
            headers = {
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            # Prepare data for POST request with proper validation
            bank_name = str(self.wallet_name).strip()
            bvn_str = str(self.bvn).strip()

            # Validate BVN format before API call
            bvn_clean = ''.join(filter(str.isdigit, bvn_str))
            if len(bvn_clean) != 11:
                error_msg = f"BVN must be exactly 11 digits. Current BVN has {len(bvn_clean)} digits"
                self.safe_log_error(error_msg, "BVN Val Error")
                return {"error": "BVN must be exactly 11 digits"}

            # Generate a unique reference with timestamp to ensure uniqueness
            timestamp = now_datetime().strftime('%Y%m%d%H%M%S')
            unique_ref = f"REF-{random.randint(100000, 999999)}-{timestamp}"

            post_data = {
                "exRef": unique_ref,
                "name": bank_name,
                "bvn": bvn_clean,  # Use cleaned BVN
                "description": f"Virtual wallet for {bank_name}",
                "accountType": "static"
            }

            # Log the request data for debugging (without sensitive info)
            debug_data = post_data.copy()
            debug_data["bvn"] = "***masked***"
            self.safe_log_error(json.dumps(debug_data, indent=2), "API Request")

            # Send the POST request to create the wallet
            response = requests.post(post_url, headers=headers, json=post_data, timeout=30)
            
            # Log response status for debugging
            self.safe_log_error(f"API Response Status: {response.status_code}", "API Status")
            
            if response.status_code == 201:  # Successful creation
                try:
                    response_json = response.json()
                    response_data = response_json.get("data", {})
                except json.JSONDecodeError:
                    self.safe_log_error("Failed to parse API response", "Parse Error")
                    return {"error": "Invalid response from API"}

                if not response_data:
                    self.safe_log_error("Empty data from API", "Response Error")
                    return {"error": "No data received from the API"}

                # Get site name with fallback
                try:
                    site_name = get_site_name(frappe.local.site)
                except:
                    site_name = frappe.conf.get('site_name', 'unknown_site')

                # Update current Virtual Wallet record with API response
                self.update({
                    "wallet_name": response_data.get("name", self.wallet_name),
                    "currency": response_data.get("currency", "NGN"),
                    "wallet_id": response_data.get("id"),
                    "description": response_data.get("description", self.description),
                    "bvn": response_data.get("bvn", bvn_clean),  # Use cleaned BVN
                    "account_number": response_data.get("accountNumber"),
                    "exchange_ref": response_data.get("exchangeRef"),
                    "business_id": response_data.get("businessId"),
                    "account_type": response_data.get("accountType", "static"),
                    "bank_code": response_data.get("bankCode"),
                    "bank_name": response_data.get("bankName"),
                    "site_name": site_name
                })
                
                # Save the updated document
                self.save(ignore_permissions=True)
                frappe.db.commit()

                # Register with admin system using the single endpoint
                admin_result = self.register_with_admin_system(response_data)
                
                # Return appropriate message based on admin registration result
                if admin_result.get("success"):
                    return {"info": f"Virtual wallet '{self.wallet_name}' created and registered successfully!"}
                else:
                    admin_error = admin_result.get("message", "Unknown admin error")
                    # Still return success for wallet creation, but note admin issue
                    return {
                        "info": f"Virtual wallet '{self.wallet_name}' created successfully!",
                        "warning": f"Admin registration issue: {admin_error}"
                    }
            
            else:
                # External API call failed
                try:
                    error_response = response.json()
                    error_msg = error_response.get("message", f"API request failed with status {response.status_code}")
                except json.JSONDecodeError:
                    error_msg = f"API request failed with status {response.status_code}: {response.text[:100]}"
                
                self.safe_log_error(f"External API Error: {error_msg}", "External API Error")
                return {"error": error_msg}

        except requests.exceptions.Timeout:
            return {"error": "Request timeout - please try again"}
        
        except requests.exceptions.ConnectionError:
            return {"error": "Connection error - check your internet connection"}
        
        except Exception as e:
            self.safe_log_error(f"Wallet Creation Error: {str(e)}", "Virtual Wallet")
            return {"error": f"System error: {str(e)}"}
    
    def get_api_settings(self):
        """Get API configuration settings"""
        try:
            # Try to get from Site Config first
            api_key = frappe.conf.get('virtual_wallet_api_key')
            base_url = frappe.conf.get('virtual_wallet_api_url')
            
            if not api_key or not base_url:
                # Fall back to System Settings or custom doctype
                # You may need to adjust this based on where you store API settings
                try:
                    settings_doc = frappe.get_single('Virtual Payment Settings')
                    api_key = settings_doc.get('api_key')
                    base_url = settings_doc.get('api_base_url')
                except:
                    pass
            
            if not api_key or not base_url:
                self.safe_log_error("Virtual Wallet API settings not configured", "API Config")
                return None
            
            return {
                'api_key': api_key,
                'base_url': base_url.rstrip('/')  # Remove trailing slash
            }
            
        except Exception as e:
            self.safe_log_error(f"Error getting API settings: {str(e)}", "API Config")
            return None


@frappe.whitelist()
def verify_and_update_pin(wallet_name, current_pin, new_pin):
    """Verify current PIN and update to new PIN"""
    try:
        # Find the associated Payment Pin document
        pin_records = frappe.get_list(
            "Payment Pin",
            filters={"wallet": wallet_name},
            fields=["name"]
        )
        
        if not pin_records:
            return {"success": False, "error": "No PIN found for this wallet"}
        
        # Get the PIN document
        pin_doc = frappe.get_doc("Payment Pin", pin_records[0].name)
        
        # Verify current PIN - assuming the PIN is stored as plain text for now
        # In production, you should hash the PINs for security
        if str(pin_doc.pin) != str(current_pin):
            return {"success": False, "error": "Current PIN is incorrect"}
        
        # Update to new PIN
        pin_doc.pin = new_pin
        pin_doc.save()
        frappe.db.commit()
        
        return {"success": True, "message": "PIN updated successfully"}
        
    except Exception as e:
        frappe.log_error(f"PIN update error: {str(e)}", "PIN Update Error")
        return {"success": False, "error": f"Error updating PIN: {str(e)}"}


@frappe.whitelist()
def get_live_token():
    """Standalone function to get LIVE_TOKEN using os library"""
    try:
        # Method 1: Direct os.getenv()
        token = os.getenv('LIVE_TOKEN')
        if token:
            return {"success": True, "token": token[:20] + "...", "method": "os.getenv()"}
        
        # Method 2: Load from .env file
        env_file_path = os.path.join(os.getcwd(), 'sites', '.env')
        if not os.path.exists(env_file_path):
            env_file_path = os.path.join(os.path.dirname(os.getcwd()), 'sites', '.env')
        
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r') as env_file:
                for line in env_file:
                    line = line.strip()
                    if line.startswith('LIVE_TOKEN='):
                        token = line.split('=', 1)[1].strip()
                        # Set it in os environment for future use
                        os.environ['LIVE_TOKEN'] = token
                        return {"success": True, "token": token[:20] + "...", "method": "loaded from .env", "path": env_file_path}
        
        return {"success": False, "error": "LIVE_TOKEN not found", "searched_path": env_file_path}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_admin_api_connection():
    """Test connection to admin API"""
    try:
        test_payload = {
            "event": "test_connection",
            "data": {
                "site_name": frappe.conf.get('site_name', 'test_site'),
                "timestamp": now_datetime().isoformat()
            }
        }
        
        post_url = "https://lassod.purpledove.net/api/method/buypower_admin.buypower_admin.utils.client_wallet"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Frappe-Client/1.0"
        }
        
        response = requests.post(
            post_url, 
            headers=headers, 
            json=test_payload, 
            timeout=30
        )
        
        return {
            "status_code": response.status_code,
            "raw_response": response.text[:500],  # Limit response length
            "parsed_response": response.json() if response.headers.get('content-type', '').startswith('application/json') else None
        }
        
    except Exception as e:
        return {
            "status_code": 0,
            "raw_response": f"Error: {str(e)}",
            "parsed_response": None
        }
