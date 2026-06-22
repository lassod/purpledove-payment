# Copyright (c) 2025, Lassod Consulting Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class TransactionHistory(Document):
    def before_insert(self):
        """Set transaction date if not provided"""
        if not self.transaction_date:
            self.transaction_date = frappe.utils.now()
    
    def validate(self):
        """Validate transaction data"""
        if not self.transaction_reference:
            frappe.throw("Transaction Reference is required")
        
        if not self.amount or self.amount <= 0:
            frappe.throw("Amount must be greater than zero")
    
    @staticmethod
    def create_transaction_record(transaction_data, virtual_payment_name=None):
        """
        Create a new transaction history record
        
        Args:
            transaction_data (dict): Transaction data from API response
            virtual_payment_name (str): Name of the Virtual Payment document
        
        Returns:
            TransactionHistory: Created transaction record
        """
        try:
            # Normalize BuyPower MFB response (nested) with legacy fallbacks.
            destination = transaction_data.get("destination", {}) or {}
            amount_obj = transaction_data.get("amount", {})
            amount_val = amount_obj.get("value", 0) if isinstance(amount_obj, dict) else (amount_obj or 0)
            source = transaction_data.get("source", {}) or {}

            tx_ref = (
                transaction_data.get("reference")
                or transaction_data.get("transactionReference")
            )

            # Check if record already exists
            existing = frappe.db.exists("Transaction History", {
                "transaction_reference": tx_ref
            })

            if existing:
                return frappe.get_doc("Transaction History", existing)

            # Map BuyPower transfer status -> Transaction History status
            status_map = {
                "paid": "Successful",
                "pending": "Pending",
                "processing": "Processing",
                "failed": "Failed",
                "cancelled": "Cancelled",
            }
            mapped_status = status_map.get(str(transaction_data.get("status", "")).lower(), "Pending")

            # Create new record
            transaction = frappe.get_doc({
                "doctype": "Transaction History",
                "transaction_reference": tx_ref,
                "virtual_payment": virtual_payment_name,
                "status": mapped_status,
                "transaction_date": frappe.utils.now(),
                "amount": amount_val,
                "destination_bank": destination.get("bankName") or transaction_data.get("destinationBankName", ""),
                "destination_account_number": destination.get("accountNumber") or transaction_data.get("destinationAccountNumber", ""),
                "destination_account_name": destination.get("accountName") or transaction_data.get("destinationAccountName", ""),
                "source_account_number": source.get("accountNumber") or transaction_data.get("sourceAccountNumber", ""),
                "narration": transaction_data.get("narration", ""),
                "api_response": frappe.as_json(transaction_data)
            })
            
            transaction.insert(ignore_permissions=True)
            frappe.db.commit()
            
            return transaction
            
        except Exception as e:
            frappe.log_error(f"Error creating transaction history: {str(e)}", "Transaction History Creation Error")
            return None
    
    @staticmethod
    def update_status(transaction_reference, status, api_response=None):
        """
        Update transaction status
        
        Args:
            transaction_reference (str): Transaction reference
            status (str): New status
            api_response (dict): Latest API response
        """
        try:
            transaction = frappe.db.exists("Transaction History", {
                "transaction_reference": transaction_reference
            })
            
            if transaction:
                doc = frappe.get_doc("Transaction History", transaction)
                doc.status = status
                
                if api_response:
                    doc.api_response = frappe.as_json(api_response)
                
                doc.save(ignore_permissions=True)
                frappe.db.commit()
                
                return doc
            
        except Exception as e:
            frappe.log_error(f"Error updating transaction status: {str(e)}", "Transaction Status Update Error")
            return None