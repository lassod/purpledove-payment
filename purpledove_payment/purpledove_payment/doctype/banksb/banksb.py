# Copyright (c) 2025, Ejiroghene Douglas Dominic and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BanksB(Document):
    def validate(self):
        """Validate bank document"""
        if not self.bank_name:
            frappe.throw("Bank name is required")
        
        if not self.bank_code:
            frappe.throw("Bank code is required")
        
        # Check for duplicate bank codes
        existing = frappe.db.get_value(
            "BanksB", 
            {"bank_code": self.bank_code, "name": ("!=", self.name)}, 
            "name"
        )
        if existing:
            frappe.throw(f"Bank with code {self.bank_code} already exists")
    
    def before_save(self):
        """Clean and format bank data before saving"""
        if self.bank_name:
            self.bank_name = self.bank_name.strip()
        
        if self.bank_code:
            self.bank_code = self.bank_code.strip().upper()
    
    @frappe.whitelist()
    def get_bank_details(self):
        """Get comprehensive bank details"""
        return {
            "bank_name": self.bank_name,
            "bank_code": self.bank_code,
            "is_new": self.get("new", False),
            "status": "Active" if self.get("enabled", True) else "Inactive"
        }
