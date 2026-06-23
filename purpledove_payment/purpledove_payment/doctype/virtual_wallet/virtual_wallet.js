// Copyright (c) 2025, Ejiroghene Dominic Douglas and contributors
// For license information, please see license.txt

frappe.ui.form.on('Virtual Wallet', {
    refresh: function (frm) {
        // Only show the button if wallet hasn't been created yet (no wallet_id)
        if (frm.doc.wallet_name && frm.doc.bvn && !frm.doc.wallet_id){  
            frm.add_custom_button(
                __("Create Wallet"),
                function () {
                    frm.events.create_wallet(frm);
                }
            ).css({
                color: "white",
                backgroundColor: "#105C10",
                fontWeight: "800",
            });
        }
        
        // Show "Setup PIN" button if wallet exists but no PIN is set up
        if (frm.doc.wallet_id && !frm.doc.__pin_exists) {
            // Check if PIN already exists for this wallet
            frappe.call({
                method: "frappe.client.get_list",
                args: {
                    doctype: "Payment Pin",
                    filters: {
                        wallet: frm.doc.name
                    },
                    limit: 1
                },
                callback: function(r) {
                    if (r.message && r.message.length === 0) {
                        // No PIN exists, show setup button
                        frm.add_custom_button(
                            __("Setup PIN"),
                            function () {
                                frm.events.setup_payment_pin(frm);
                            }
                        ).css({
                            color: "white",
                            backgroundColor: "#2196F3",
                            fontWeight: "800",
                        });
                    } else {
                        // PIN exists, show change PIN button
                        frm.add_custom_button(
                            __("Change PIN"),
                            function () {
                                frm.events.change_payment_pin(frm);
                            },
                            __("PIN Actions")
                        );
                        
                        // Add view PIN button for admin
                        if (frappe.user.has_role("System Manager")) {
                            frm.add_custom_button(
                                __("View PIN Details"),
                                function () {
                                    frappe.set_route("Form", "Payment Pin", r.message[0].name);
                                },
                                __("PIN Actions")
                            );
                        }
                    }
                }
            });
        }
        
        // Add validation button for testing
        if (frm.doc.wallet_name || frm.doc.bvn) {
            frm.add_custom_button(
                __("Test Validation"),
                function () {
                    frm.events.test_validation(frm);
                },
                __("Debug")
            );
        }
        
        // Add admin API test button
        frm.add_custom_button(
            __("Test Admin API"),
            function () {
                frm.events.test_admin_api(frm);
            },
            __("Debug")
        );
    },
    
    onload: function(frm) {
        // Allow users to manually enter wallet name
        frm.refresh_field("wallet_name");
        
        // Set up validation on BVN field
        frm.set_df_property('bvn', 'description', 'Enter exactly 11 digits');
    },
    
    // Removed popup validations from bvn and wallet_name events
    // Validation will only happen on save/create
    
    validate: function(frm) {
        // Validation that runs before saving
        let errors = [];
        
        if (frm.doc.wallet_name) {
            let name = frm.doc.wallet_name.trim();
            if (name.length < 2) {
                errors.push("Wallet name must be at least 2 characters");
            } else if (name.length > 50) {
                errors.push("Wallet name must be less than 50 characters");
            }
        }
        
        if (frm.doc.bvn) {
            let bvn = frm.doc.bvn.toString().trim();
            if (bvn.length !== 11 || !/^\d{11}$/.test(bvn)) {
                errors.push("BVN must be exactly 11 digits");
            }
        }
        
        if (errors.length > 0) {
            frappe.msgprint({
                title: __('Validation Error'),
                message: errors.join('<br>'),
                indicator: 'red'
            });
            frappe.validated = false; // Prevent saving
        }
    },
    
    setup_payment_pin: function(frm) {
        // Create a dialog for PIN setup
        let pin_dialog = new frappe.ui.Dialog({
            title: __('Setup Payment PIN'),
            fields: [
                {
                    fieldname: 'pin',
                    fieldtype: 'Password',
                    label: __('Enter 4-Digit PIN'),
                    reqd: 1,
                    description: 'Enter a 4-digit numeric PIN for transactions'
                },
                {
                    fieldname: 'confirm_pin',
                    fieldtype: 'Password',
                    label: __('Confirm PIN'),
                    reqd: 1,
                    description: 'Re-enter the same PIN to confirm'
                }
            ],
            primary_action_label: __('Create PIN'),
            primary_action: function(values) {
                // Validate PIN format
                if (!values.pin || !values.confirm_pin) {
                    frappe.msgprint({
                        title: __('Missing Information'),
                        message: __('Please enter both PIN and confirmation'),
                        indicator: 'red'
                    });
                    return;
                }
                
                // Check if PIN is 4 digits
                if (!/^\d{4}$/.test(values.pin)) {
                    frappe.msgprint({
                        title: __('Invalid PIN'),
                        message: __('PIN must be exactly 4 digits'),
                        indicator: 'red'
                    });
                    return;
                }
                
                // Check if PINs match
                if (values.pin !== values.confirm_pin) {
                    frappe.msgprint({
                        title: __('PIN Mismatch'),
                        message: __('PIN and confirmation do not match'),
                        indicator: 'red'
                    });
                    return;
                }
                
                // Create the PIN
                frm.events.create_payment_pin(frm, values.pin, pin_dialog);
            }
        });
        
        pin_dialog.show();
    },
    
    change_payment_pin: function(frm) {
        // Create a dialog for PIN change
        let change_dialog = new frappe.ui.Dialog({
            title: __('Change Payment PIN'),
            fields: [
                {
                    fieldname: 'current_pin',
                    fieldtype: 'Password',
                    label: __('Current PIN'),
                    reqd: 1,
                    description: 'Enter your current 4-digit PIN'
                },
                {
                    fieldname: 'new_pin',
                    fieldtype: 'Password',
                    label: __('New PIN'),
                    reqd: 1,
                    description: 'Enter a new 4-digit numeric PIN'
                },
                {
                    fieldname: 'confirm_new_pin',
                    fieldtype: 'Password',
                    label: __('Confirm New PIN'),
                    reqd: 1,
                    description: 'Re-enter the new PIN to confirm'
                }
            ],
            primary_action_label: __('Change PIN'),
            primary_action: function(values) {
                // Validate all fields
                if (!values.current_pin || !values.new_pin || !values.confirm_new_pin) {
                    frappe.msgprint({
                        title: __('Missing Information'),
                        message: __('Please fill in all fields'),
                        indicator: 'red'
                    });
                    return;
                }
                
                // Validate new PIN format
                if (!/^\d{4}$/.test(values.new_pin)) {
                    frappe.msgprint({
                        title: __('Invalid PIN'),
                        message: __('New PIN must be exactly 4 digits'),
                        indicator: 'red'
                    });
                    return;
                }
                
                // Check if new PINs match
                if (values.new_pin !== values.confirm_new_pin) {
                    frappe.msgprint({
                        title: __('PIN Mismatch'),
                        message: __('New PIN and confirmation do not match'),
                        indicator: 'red'
                    });
                    return;
                }
                
                // Check if new PIN is different from current
                if (values.current_pin === values.new_pin) {
                    frappe.msgprint({
                        title: __('Same PIN'),
                        message: __('New PIN must be different from current PIN'),
                        indicator: 'orange'
                    });
                    return;
                }
                
                frm.events.update_payment_pin(frm, values.current_pin, values.new_pin, change_dialog);
            }
        });
        
        change_dialog.show();
    },

    
    create_payment_pin: function(frm, pin, dialog) {
        frappe.call({
            method: "frappe.client.insert",
            args: {
                doc: {
                    doctype: "Payment Pin",
                    pin: pin,
                    wallet: frm.doc.name
                }
            },
            freeze: true,
            freeze_message: __("Creating Payment PIN..."),
            callback: function(r) {
                if (r.message) {
                    dialog.hide();
                    frappe.msgprint({
                        title: __('Success'),
                        message: __('Payment PIN has been created successfully'),
                        indicator: 'green'
                    });
                    frm.refresh(); // Refresh to update buttons
                } else {
                    frappe.msgprint({
                        title: __('Error'),
                        message: __('Failed to create Payment PIN'),
                        indicator: 'red'
                    });
                }
            },
            error: function(r) {
                frappe.msgprint({
                    title: __('Error'),
                    message: __('An error occurred while creating the PIN'),
                    indicator: 'red'
                });
                console.error("PIN Creation Error:", r);
            }
        });
    },
    
    update_payment_pin: function(frm, current_pin, new_pin, dialog) {
        // First verify the current PIN
        frappe.call({
            method: "purpledove_payment.purpledove_payment.doctype.virtual_wallet.virtual_wallet.verify_and_update_pin",
            args: {
                wallet_name: frm.doc.name,
                current_pin: current_pin,
                new_pin: new_pin
            },
            freeze: true,
            freeze_message: __("Updating Payment PIN..."),
            callback: function(r) {
                if (r.message && r.message.success) {
                    dialog.hide();
                    frappe.msgprint({
                        title: __('Success'),
                        message: __('Payment PIN has been updated successfully'),
                        indicator: 'green'
                    });
                } else {
                    frappe.msgprint({
                        title: __('Error'),
                        message: r.message ? r.message.error : __('Failed to update PIN'),
                        indicator: 'red'
                    });
                }
            },
            error: function(r) {
                frappe.msgprint({
                    title: __('Error'),
                    message: __('An error occurred while updating the PIN'),
                    indicator: 'red'
                });
                console.error("PIN Update Error:", r);
            }
        });
    },
    
    test_validation: function(frm) {
        // Simple client-side validation instead of server call
        let errors = [];
        
        if (!frm.doc.wallet_name || frm.doc.wallet_name.trim().length < 2) {
            errors.push("Wallet name must be at least 2 characters");
        } else if (frm.doc.wallet_name.trim().length > 50) {
            errors.push("Wallet name must be less than 50 characters");
        }
        
        if (!frm.doc.bvn) {
            errors.push("BVN is required");
        } else {
            let bvn = frm.doc.bvn.toString().trim();
            if (bvn.length !== 11 || !/^\d{11}$/.test(bvn)) {
                errors.push("BVN must be exactly 11 digits");
            }
        }
        
        if (errors.length > 0) {
            frappe.msgprint({
                title: __('Validation Failed'),
                message: errors.join('<br>'),
                indicator: 'red'
            });
        } else {
            frappe.msgprint({
                title: __('Validation Passed'),
                message: __('Data is valid and ready for wallet creation'),
                indicator: 'green'
            });
        }
    },
    
    test_admin_api: function(frm) {
        frappe.call({
            method: "purpledove_payment.purpledove_payment.doctype.virtual_wallet.virtual_wallet.test_admin_api_connection",
            callback: function(r) {
                if (r.message) {
                    console.log("Admin API Test Result:", r.message);
                    
                    let message = `
                        <strong>Status Code:</strong> ${r.message.status_code}<br>
                        <strong>Raw Response:</strong> ${r.message.raw_response}<br>
                        <strong>Parsed Response:</strong> ${JSON.stringify(r.message.parsed_response, null, 2)}
                    `;
                    
                    frappe.msgprint({
                        title: __('Admin API Test Result'),
                        message: message,
                        indicator: r.message.status_code === 200 ? 'green' : 'orange',
                        wide: true
                    });
                } else {
                    frappe.msgprint({
                        title: __('Test Failed'),
                        message: __('No response received from test'),
                        indicator: 'red'
                    });
                }
            }
        });
    },
    
    create_wallet: function (frm) {
        // Pre-validation before API call
        let errors = [];
        
        if (!frm.doc.wallet_name || frm.doc.wallet_name.trim().length < 2) {
            errors.push("Wallet name must be at least 2 characters");
        }
        
        if (!frm.doc.bvn) {
            errors.push("BVN is required");
        } else {
            let bvn = frm.doc.bvn.toString().trim();
            if (bvn.length !== 11 || !/^\d{11}$/.test(bvn)) {
                errors.push("BVN must be exactly 11 digits");
            }
        }
        
        if (errors.length > 0) {
            frappe.msgprint({
                title: __('Validation Error'),
                message: errors.join('<br>'),
                indicator: 'red'
            });
            return;
        }
        
        // Confirm before creating wallet
        frappe.confirm(
            __('Are you sure you want to create this virtual wallet?<br><br><strong>Wallet Name:</strong> {0}<br><strong>BVN:</strong> ***********{1}', 
               [frm.doc.wallet_name, frm.doc.bvn.toString().slice(-2)]),
            function() {
                // User confirmed, proceed with wallet creation
                frappe.call({
                    doc: frm.doc,
                    method: "create_wallet",
                    freeze: true,
                    freeze_message: __("Creating Virtual Wallet... Please wait."),
                    callback: function(r) {
                        console.log("Wallet Creation Response:", r.message);
                        
                        if (r.message && r.message.info) {
                            frappe.msgprint({
                                title: __('Success'),
                                message: __(r.message.info),
                                indicator: 'green'
                            });
                            
                            // Refresh to show the PIN setup button
                            frm.refresh();
                            
                            // Auto-prompt for PIN setup after successful wallet creation
                            setTimeout(function() {
                                frappe.confirm(
                                    __('Your wallet has been created successfully!<br><br>Would you like to set up a Payment PIN now for secure transactions?'),
                                    function() {
                                        frm.events.setup_payment_pin(frm);
                                    },
                                    function() {
                                        frappe.msgprint({
                                            title: __('Reminder'),
                                            message: __('You can set up your Payment PIN later using the "Setup PIN" button.'),
                                            indicator: 'blue'
                                        });
                                    }
                                );
                            }, 1000);
                            
                        } else if (r.message && r.message.error) {
                            frappe.msgprint({
                                title: __('Error'),
                                message: __("Error: " + r.message.error),
                                indicator: 'red'
                            });
                        } else {
                            frappe.msgprint({
                                title: __('Error'),
                                message: __("Failed to set up virtual wallet."),
                                indicator: 'red'
                            });
                        }
                    },
                    error: function(r) {
                        frappe.msgprint({
                            title: __('Error'),
                            message: __("An error occurred while setting up the virtual wallet."),
                            indicator: 'red'
                        });
                        console.error("Wallet Creation Error:", r);
                    }
                });
            }
        );
    },
});