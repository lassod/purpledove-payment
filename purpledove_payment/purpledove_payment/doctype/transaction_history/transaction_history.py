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
            # Check if record already exists
            existing = frappe.db.exists("Transaction History", {
                "transaction_reference": transaction_data.get("transactionReference")
            })
            
            if existing:
                return frappe.get_doc("Transaction History", existing)
            
            # Create new record
            transaction = frappe.get_doc({
                "doctype": "Transaction History",
                "transaction_reference": transaction_data.get("transactionReference"),
                "virtual_payment": virtual_payment_name,
                "status": "Pending",  # Default status
                "transaction_date": frappe.utils.now(),
                "amount": transaction_data.get("amount", 0),
                "destination_bank": transaction_data.get("destinationBankName", ""),
                "destination_account_number": transaction_data.get("destinationAccountNumber", ""),
                "destination_account_name": transaction_data.get("destinationAccountName", ""),
                "source_account_number": transaction_data.get("sourceAccountNumber", ""),
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