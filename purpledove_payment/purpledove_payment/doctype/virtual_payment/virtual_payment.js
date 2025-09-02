// Copyright (c) 2025, Lassod Consulting Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on('Virtual Payment', {
    refresh: function(frm) {
        // Only show Make Payment button if no transaction reference exists (payment hasn't been made)
        if (frm.doc.destination_account_number && !frm.doc.transaction_reference) {
            frm.add_custom_button(__("Make Virtual Payment"), () => {
                frm.events.make_payment(frm);
            }).css({ fontWeight: "800" });
        }
        
        // Add status check button if transaction reference exists
        if (frm.doc.transaction_reference) {
            frm.add_custom_button(__("Check Transaction Status"), () => {
                frm.events.check_transaction_status(frm, frm.doc.transaction_reference);
            }).css({ fontWeight: "600", backgroundColor: "#17a2b8", color: "white" });
        }
    },

    onload: function(frm) {
        // Track original values for change detection
        frm._original_values = {
            account_number: frm.doc.destination_account_number,
            bank_code: frm.doc.bank_code,
            destination_bank: frm.doc.destination_bank
        };
    },

    // Field change handlers
    destination_account_number: function(frm) {
        frm.events.handle_field_change(frm, 'account_number');
    },

    bank_code: function(frm) {
        frm.events.handle_field_change(frm, 'bank_code');
    },

    destination_bank: function(frm) {
        frm.events.handle_field_change(frm, 'destination_bank');
        
        // Auto-populate destination bank code when bank is selected
        if (frm.doc.destination_bank) {
            frappe.db.get_value('BanksB', frm.doc.destination_bank, 'bank_code')
                .then(r => {
                    if (r.message && r.message.bank_code) {
                        frm.set_value('destination_bank_code', r.message.bank_code);
                        console.log('Bank code set:', r.message.bank_code);
                        
                        frappe.show_alert({
                            message: `Bank code ${r.message.bank_code} set for ${frm.doc.destination_bank}`,
                            indicator: 'green'
                        }, 3);
                    } else {
                        console.warn(`Bank code not found for ${frm.doc.destination_bank}`);
                        frappe.msgprint(`Bank code not found for ${frm.doc.destination_bank}`);
                    }
                })
                .catch(err => {
                    console.error('Error fetching bank code:', err);
                    frappe.msgprint(`Error fetching bank code: ${err.message}`);
                });
        } else {
            frm.set_value('destination_bank_code', '');
        }
    },

    // Unified field change handler
    handle_field_change: function(frm, field_type) {
        const field_map = {
            'account_number': 'destination_account_number',
            'bank_code': 'bank_code',
            'destination_bank': 'destination_bank'
        };
        
        const field_name = field_map[field_type];
        
        if (frm.doc[field_name] && frm.doc[field_name] !== frm._original_values[field_type]) {
            frm.set_value('destination_account_name', '');
            frm._verification_needed = true;
        }
    },

    after_save: function(frm) {
        if (frm._verification_needed) {
            frm._verification_needed = false;
            
            // Update tracked values
            frm._original_values = {
                account_number: frm.doc.destination_account_number,
                bank_code: frm.doc.bank_code,
                destination_bank: frm.doc.destination_bank
            };
            
            // Perform verification
            frm.events.verify_account(frm);
        }
    },

    verify_account: function(frm) {
        frm.disable_save();
        
        return frm.call('process_bank_verification')
            .then(r => {
                frm.enable_save();
                
                if (r.message?.success) {
                    if (r.message.account_name) {
                        frm.set_value('destination_account_name', r.message.account_name);
                    }
                    
                    frappe.show_alert({
                        message: __('Bank account verified successfully'),
                        indicator: 'green'
                    }, 3);
                    
                    frm.reload_doc();
                    return r.message;
                } else {
                    frappe.show_alert({
                        message: r.message?.error || __('Bank verification failed'),
                        indicator: 'red'
                    }, 5);
                    throw new Error(r.message?.error || 'Bank verification failed');
                }
            })
            .catch(err => {
                frm.enable_save();
                
                frappe.show_alert({
                    message: err.message || __('An error occurred during verification'),
                    indicator: 'red'
                }, 5);
                
                frm.reload_doc();
                throw err;
            });
    },

    make_payment: function(frm) {
        // First show wallet selection dialog
        frm.events.show_wallet_selection(frm);
    },

    show_wallet_selection: function(frm) {
        const wallet_dialog = new frappe.ui.Dialog({
            title: __('Select Wallet for Payment'),
            fields: [
                {
                    fieldtype: 'Link',
                    fieldname: 'selected_wallet', // Changed from 'wallet' to 'selected_wallet'
                    label: __('Select Wallet'),
                    options: 'Virtual Wallet',
                    reqd: 1,
                    description: __('Choose the wallet to use for this payment'),
                    default: frm.doc.virtual_wallet || frappe.defaults.get_default("company")
                },
                {
                    fieldtype: 'HTML',
                    fieldname: 'wallet_info',
                    options: `
                        <div style="padding: 10px; background: #f8f9fa; border-radius: 4px; margin-top: 10px;">
                            <i class="fa fa-info-circle"></i> Each wallet has its own PIN for security
                        </div>
                    `
                }
            ],
            primary_action_label: __('Continue'),
            primary_action: () => {
                const selected_wallet = wallet_dialog.get_value('selected_wallet'); // Updated field name
                
                if (!selected_wallet) {
                    frappe.msgprint({
                        title: __('Wallet Required'),
                        indicator: 'red',
                        message: __('Please select a wallet to continue')
                    });
                    return;
                }
                
                wallet_dialog.hide();
                frm.events.show_pin_entry(frm, selected_wallet);
            }
        });
        
        wallet_dialog.show();
        
        // Auto-focus wallet field
        setTimeout(() => {
            wallet_dialog.get_field('selected_wallet').$input.focus(); // Updated field name
        }, 500);
    },

    show_pin_entry: function(frm, selected_wallet) {
        const pin_dialog = new frappe.ui.Dialog({
            title: __('Enter PIN for Wallet: ') + selected_wallet,
            fields: [
                {
                    fieldtype: 'Password',
                    fieldname: 'transaction_pin',
                    label: __('Transaction PIN'),
                    reqd: 1,
                    description: __('Enter your 4-digit PIN for this wallet'),
                    max_length: 4
                },
                {
                    fieldtype: 'HTML',
                    fieldname: 'wallet_display',
                    options: `
                        <div style="padding: 10px; background: #e3f2fd; border-radius: 4px; margin-bottom: 10px;">
                            <strong>Wallet:</strong> ${selected_wallet}
                        </div>
                    `
                }
            ],
            primary_action_label: __('Verify & Process Payment'),
            primary_action: () => {
                const pin = pin_dialog.get_value('transaction_pin');
                
                if (!frm.events.validate_pin_format(pin)) {
                    frappe.msgprint({
                        title: __('Invalid PIN'),
                        indicator: 'red',
                        message: __('Please enter a valid 4-digit PIN')
                    });
                    return;
                }
                
                frm.events.verify_pin_and_process(frm, pin, pin_dialog, selected_wallet);
            },
            secondary_action_label: __('Change Wallet'),
            secondary_action: () => {
                pin_dialog.hide();
                frm.events.show_wallet_selection(frm);
            }
        });
        
        pin_dialog.show();
        
        // Auto-focus PIN input
        setTimeout(() => {
            const $input = pin_dialog.get_field('transaction_pin').$input;
            $input.focus();
            
            // Enter key handler
            $input.on('keypress', e => {
                if (e.which === 13) pin_dialog.primary_action();
            });
        }, 500);
    },

    validate_pin_format: function(pin) {
        return pin && pin.length === 4 && /^\d{4}$/.test(pin);
    },

    verify_pin_and_process: function(frm, pin, pin_dialog, selected_wallet) {
        pin_dialog.set_primary_action(__('Verifying PIN...'));
        pin_dialog.$wrapper.find('.btn-primary').prop('disabled', true);
        
        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Payment Pin",
                filters: { wallet: selected_wallet },
                fields: ["pin", "wallet", "name"]
            },
            callback: r => {
                if (r.message?.length > 0) {
                    const payment_pin_doc = r.message[0];
                    const stored_pin = payment_pin_doc.pin;
                    
                    console.log(`PIN verification for wallet: ${payment_pin_doc.wallet}`);
                    
                    if (stored_pin === pin) {
                        frappe.show_alert({
                            message: __('PIN verified successfully for wallet: ') + selected_wallet,
                            indicator: 'green'
                        }, 2);
                        
                        pin_dialog.hide();
                        frm.events.process_payment(frm, pin, selected_wallet);
                    } else {
                        frappe.msgprint({
                            title: __('Authentication Failed'),
                            indicator: 'red',
                            message: __('Incorrect PIN for the selected wallet. Please try again.')
                        });
                        
                        pin_dialog.set_primary_action(__('Verify & Process Payment'));
                        pin_dialog.$wrapper.find('.btn-primary').prop('disabled', false);
                        
                        const pin_field = pin_dialog.get_field('transaction_pin');
                        pin_field.set_value('');
                        pin_field.$input.focus();
                    }
                } else {
                    frappe.msgprint({
                        title: __('PIN Not Found'),
                        indicator: 'red',
                        message: __('No transaction PIN found for wallet: ') + selected_wallet + 
                                __('<br><br>Please set up a PIN for this wallet in Payment Pin doctype first.')
                    });
                    pin_dialog.hide();
                }
            },
            error: err => {
                console.error("PIN verification error:", err);
                frappe.msgprint({
                    title: __('System Error'),
                    indicator: 'red',
                    message: __('Unable to verify PIN. Please try again.')
                });
                pin_dialog.hide();
            }
        });
    },

    handle_invalid_pin: function(pin_dialog) {
        frappe.msgprint({
            title: __('Authentication Failed'),
            indicator: 'red',
            message: __('Incorrect PIN. Please try again.')
        });
        
        pin_dialog.set_primary_action(__('Verify & Process Payment'));
        pin_dialog.$wrapper.find('.btn-primary').prop('disabled', false);
        
        const pin_field = pin_dialog.get_field('transaction_pin');
        pin_field.set_value('');
        pin_field.$input.focus();
    },

    process_payment: function(frm, pin, selected_wallet) {
        frappe.call({
            doc: frm.doc,
            method: "make_virtual_payment",
            args: { 
                transaction_pin: pin,
                virtual_wallet: selected_wallet  // Fixed: Changed from 'wallet' to 'virtual_wallet'
            },
            freeze: true,
            freeze_message: __("Processing Virtual Payment...")
        }).then(r => {
            const response = r.message;
            
            if (response?.success === true) {
                frm.events.handle_payment_success(frm, response);
            } else if (response?.error?.includes("Insufficient Funds")) {
                frm.events.handle_insufficient_funds(frm, response);
            } else {
                frm.events.handle_payment_error(frm, response);
            }
        }).catch(error => {
            console.error("Payment processing error:", error);
            frappe.msgprint({
                title: __("System Error"),
                indicator: "red",
                message: __("An error occurred while processing payment.")
            });
        });
    },

    handle_payment_success: function(frm, response) {
        let message = __("Transfer completed successfully!");
        
        if (response.new_balance !== undefined) {
            message += `<br><br>${__("New wallet balance:")} ₦${response.new_balance.toLocaleString()}`;
        }
        
        if (response.transaction_data?.transactionReference) {
            message += `<br>${__("Transaction Reference:")} ${response.transaction_data.transactionReference}`;
        }
        
        const success_dialog = new frappe.ui.Dialog({
            title: __("Payment Successful"),
            fields: [{
                fieldtype: 'HTML',
                fieldname: 'success_message',
                options: `
                    <div style="text-align: center; margin-bottom: 20px;">
                        <div style="font-size: 48px; color: #28a745; margin-bottom: 10px;">
                            <i class="fa fa-check-circle"></i>
                        </div>
                        <div style="font-size: 16px; color: #666;">
                            ${message}
                        </div>
                    </div>
                `
            }],
            primary_action_label: __('Check Status'),
            primary_action: () => {
                success_dialog.hide();
                if (response.transaction_data?.transactionReference) {
                    frm.events.check_transaction_status(frm, response.transaction_data.transactionReference);
                } else {
                    frappe.msgprint(__('Transaction reference not available'));
                }
            },
            secondary_action_label: __('Go to Payment List'),
            secondary_action: () => {
                success_dialog.hide();
                frappe.set_route('List', 'Virtual Payment');
            }
        });
        
        success_dialog.show();
        
        // Store transaction reference for later status checks
        if (response.transaction_data?.transactionReference) {
            frm.set_value('transaction_reference', response.transaction_data.transactionReference);
        }
        
        // Add status check button to form after successful payment
        frm.add_custom_button(__("Check Transaction Status"), () => {
            const transaction_ref = frm.doc.transaction_reference || response.transaction_data?.transactionReference;
            if (transaction_ref) {
                frm.events.check_transaction_status(frm, transaction_ref);
            } else {
                frappe.msgprint(__('No transaction reference available'));
            }
        }).css({ fontWeight: "600", backgroundColor: "#17a2b8", color: "white" });
        
        // Auto-navigate after 10 seconds (increased time)
        setTimeout(() => {
            if (success_dialog.display) {
                success_dialog.hide();
                frappe.set_route('List', 'Virtual Payment');
            }
        }, 10000);
    },

    handle_insufficient_funds: function(frm, response) {
        const error_message = response.error || response.message || "";
        
        const dialog = new frappe.ui.Dialog({
            title: __('Insufficient Wallet Balance'),
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'error_info',
                    options: `
                        <div style="text-align: center; margin-bottom: 20px;">
                            <div style="font-size: 48px; color: #ff6b6b; margin-bottom: 10px;">
                                <i class="fa fa-wallet"></i>
                            </div>
                            <h4 style="color: #ff6b6b;">Insufficient Wallet Balance</h4>
                            <p style="font-size: 16px;">${error_message}</p>
                        </div>
                        <div style="border-radius: 8px; padding: 15px; background: #f8f9fa;">
                            <h5>What you can do:</h5>
                            <ul style="margin: 0; padding-left: 20px;">
                                <li>Fund your wallet with sufficient balance</li>
                                <li>Reduce the transfer amount</li>
                                <li>Check your wallet balance before transfers</li>
                                <li>Contact support if you believe this is an error</li>
                            </ul>
                        </div>
                    `
                }
            ],
            primary_action_label: __('Check Wallet Balance'),
            primary_action: () => {
                dialog.hide();
                frm.events.show_wallet_balance(frm);
            }
        });
        
        dialog.show();
    },

    handle_payment_error: function(frm, response) {
        const error_map = {
            502: {
                title: __("Gateway Temporarily Unavailable"),
                message: __("The payment gateway is temporarily unavailable. Please try again in a few minutes."),
                show_retry: true
            },
            500: {
                title: __("Server Error"),
                message: __("The payment server encountered an error. Please try again."),
                show_retry: true
            },
            400: {
                title: __("Invalid Request"),
                message: __("Please check your payment details and try again."),
                show_retry: true
            },
            401: {
                title: __("Authentication Error"),
                message: __("Payment authentication failed. Please contact support."),
                show_retry: false
            }
        };
        
        const status_code = response?.status_code;
        const error_config = error_map[status_code] || {
            title: __("Payment Failed"),
            message: response?.error || response?.message || __("An error occurred during payment."),
            show_retry: true
        };
        
        const error_dialog = new frappe.ui.Dialog({
            title: error_config.title,
            fields: [{
                fieldtype: 'HTML',
                fieldname: 'error_details',
                options: `<div style="margin-bottom: 15px;">${error_config.message}</div>`
            }],
            primary_action_label: error_config.show_retry ? __('Try Again') : __('Close'),
            primary_action: () => {
                error_dialog.hide();
                if (error_config.show_retry) {
                    setTimeout(() => frm.events.make_payment(frm), 500);
                }
            }
        });
        
        error_dialog.show();
    },

    show_wallet_balance: function(frm) {
        // First show dialog to select which wallet to check
        const balance_dialog = new frappe.ui.Dialog({
            title: __('Check Wallet Balance'),
            fields: [
                {
                    fieldtype: 'Link',
                    fieldname: 'selected_wallet', // Changed from 'wallet' to 'selected_wallet'
                    label: __('Select Wallet'),
                    options: 'Virtual Wallet',
                    reqd: 1,
                    description: __('Choose which wallet balance to check')
                }
            ],
            primary_action_label: __('Check Balance'),
            primary_action: () => {
                const selected_wallet = balance_dialog.get_value('selected_wallet'); // Updated field name
                
                if (!selected_wallet) {
                    frappe.msgprint({
                        title: __('Wallet Required'),
                        indicator: 'red',
                        message: __('Please select a wallet')
                    });
                    return;
                }
                
                balance_dialog.hide();
                
                // Fetch balance for the selected wallet
                frappe.call({
                    method: "frappe.client.get_value",
                    args: {
                        doctype: "Virtual Wallet",
                        filters: { name: selected_wallet },
                        fieldname: ["balance", "account_number", "name"]
                    },
                    callback: r => {
                        if (r.message) {
                            const balance = parseFloat(r.message.balance) || 0;
                            const account_number = r.message.account_number || "N/A";
                            
                            frappe.msgprint({
                                title: __("Wallet Balance"),
                                indicator: "blue",
                                message: `
                                    <strong>Wallet:</strong> ${selected_wallet}<br>
                                    <strong>Account Number:</strong> ${account_number}<br>
                                    <strong>Current Balance:</strong> ₦${balance.toLocaleString()}
                                `
                            });
                        } else {
                            frappe.msgprint({
                                title: __("Wallet Balance"),
                                indicator: "orange",
                                message: __("Unable to fetch balance for the selected wallet.")
                            });
                        }
                    },
                    error: err => {
                        console.error("Error fetching wallet balance:", err);
                        frappe.msgprint({
                            title: __("Error"),
                            indicator: "red",
                            message: __("Unable to fetch wallet balance. Please try again.")
                        });
                    }
                });
            }
        });
        
        balance_dialog.show();
    },

    check_transaction_status: function(frm, transaction_reference) {
        if (!transaction_reference) {
            frappe.msgprint({
                title: __('Transaction Reference Required'),
                indicator: 'red',
                message: __('Transaction reference is required to check status')
            });
            return;
        }
        
        // First check Transaction History doctype
        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Transaction History",
                filters: { transaction_reference: transaction_reference },
                fields: ["name", "status", "amount", "destination_bank", "destination_account_name", "transaction_reference", "transaction_date"]
            },
            callback: r => {
                if (r.message && r.message.length > 0) {
                    const transaction = r.message[0];
                    frm.events.show_transaction_status(frm, transaction);
                } else {
                    // If not found locally, check with API
                    frm.events.check_api_transaction_status(frm, transaction_reference);
                }
            },
            error: err => {
                console.error("Error checking transaction status:", err);
                // Fallback to API check
                frm.events.check_api_transaction_status(frm, transaction_reference);
            }
        });
    },

    check_api_transaction_status: function(frm, transaction_reference) {
        frappe.call({
            doc: frm.doc,
            method: "check_transaction_status_api",
            args: { transaction_reference: transaction_reference },
            freeze: true,
            freeze_message: __("Checking transaction status...")
        }).then(r => {
            const response = r.message;
            if (response?.success) {
                frm.events.show_api_transaction_status(frm, response.data, transaction_reference);
            } else {
                frappe.msgprint({
                    title: __('Status Check Failed'),
                    indicator: 'red',
                    message: response?.error || __('Unable to check transaction status from API')
                });
            }
        }).catch(error => {
            console.error("API status check error:", error);
            frappe.msgprint({
                title: __("System Error"),
                indicator: "red",
                message: __("An error occurred while checking transaction status.")
            });
        });
    },

    show_transaction_status: function(frm, transaction) {
        const status_colors = {
            'Pending': '#ffc107',
            'Completed': '#28a745',
            'Failed': '#dc3545',
            'Processing': '#17a2b8'
        };
        
        const status_color = status_colors[transaction.status] || '#6c757d';
        
        const status_dialog = new frappe.ui.Dialog({
            title: __('Transaction Status'),
            fields: [{
                fieldtype: 'HTML',
                fieldname: 'status_info',
                options: `
                    <div style="text-align: center; margin-bottom: 20px;">
                        <div style="font-size: 48px; color: ${status_color}; margin-bottom: 15px;">
                            <i class="fa fa-${transaction.status === 'Completed' ? 'check-circle' : 
                                              transaction.status === 'Failed' ? 'times-circle' : 
                                              transaction.status === 'Processing' ? 'spinner fa-spin' : 'clock-o'}"></i>
                        </div>
                        <h4 style="color: ${status_color}; margin-bottom: 20px;">${transaction.status}</h4>
                        <div style="background: #f8f9fa; border-radius: 8px; padding: 15px; text-align: left;">
                            <strong>Transaction Details:</strong><br><br>
                            <strong>Reference:</strong> ${transaction.transaction_reference}<br>
                            <strong>Amount:</strong> ₦${parseFloat(transaction.amount).toLocaleString()}<br>
                            <strong>Bank:</strong> ${transaction.destination_bank}<br>
                            <strong>Account Name:</strong> ${transaction.destination_account_name}<br>
                            <strong>Date:</strong> ${new Date(transaction.transaction_date || transaction.creation).toLocaleString()}
                        </div>
                    </div>
                `
            }],
            primary_action_label: __('Refresh Status'),
            primary_action: () => {
                status_dialog.hide();
                frm.events.check_transaction_status(frm, transaction.transaction_reference);
            }
        });
        
        status_dialog.show();
    },

    show_api_transaction_status: function(frm, api_data, transaction_reference) {
        const status = api_data.status || api_data.transactionStatus || 'Unknown';
        const status_colors = {
            'SUCCESSFUL': '#28a745',
            'SUCCESS': '#28a745', 
            'PENDING': '#ffc107',
            'FAILED': '#dc3545',
            'PROCESSING': '#17a2b8'
        };
        
        const status_color = status_colors[status.toUpperCase()] || '#6c757d';
        
        const status_dialog = new frappe.ui.Dialog({
            title: __('Transaction Status (API)'),
            fields: [{
                fieldtype: 'HTML',
                fieldname: 'api_status_info',
                options: `
                    <div style="text-align: center; margin-bottom: 20px;">
                        <div style="font-size: 48px; color: ${status_color}; margin-bottom: 15px;">
                            <i class="fa fa-${status.toUpperCase() === 'SUCCESSFUL' || status.toUpperCase() === 'SUCCESS' ? 'check-circle' : 
                                              status.toUpperCase() === 'FAILED' ? 'times-circle' : 
                                              status.toUpperCase() === 'PROCESSING' ? 'spinner fa-spin' : 'clock-o'}"></i>
                        </div>
                        <h4 style="color: ${status_color}; margin-bottom: 20px;">${status}</h4>
                        <div style="background: #f8f9fa; border-radius: 8px; padding: 15px; text-align: left;">
                            <strong>API Response:</strong><br><br>
                            <strong>Reference:</strong> ${transaction_reference}<br>
                            <strong>Status:</strong> ${status}<br>
                            ${api_data.amount ? `<strong>Amount:</strong> ₦${parseFloat(api_data.amount).toLocaleString()}<br>` : ''}
                            ${api_data.destinationAccountName ? `<strong>Account Name:</strong> ${api_data.destinationAccountName}<br>` : ''}
                            ${api_data.message ? `<strong>Message:</strong> ${api_data.message}<br>` : ''}
                        </div>
                    </div>
                `
            }],
            primary_action_label: __('Close'),
            primary_action: () => {
                status_dialog.hide();
            }
        });
        
        status_dialog.show();
    }
});