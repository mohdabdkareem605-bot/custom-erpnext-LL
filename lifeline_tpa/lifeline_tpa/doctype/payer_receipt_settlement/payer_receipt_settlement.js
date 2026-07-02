frappe.ui.form.on("Payer Receipt Settlement", {
    refresh(frm) {
        frm.add_custom_button(
            __("Download Upload Template"),
            () => {
                window.open(
                    "/assets/lifeline_tpa/files/payer_receipt_upload_template.xlsx",
                    "_blank"
                );
            },
            __("Actions")
        );

        if (!frm.is_new() && frm.doc.docstatus === 0 && frm.doc.source_file) {
            frm.add_custom_button(__("Validate Receipt File"), () => {
                frm.call({
                    method:
                        "lifeline_tpa.lifeline_tpa.doctype.payer_receipt_settlement.payer_receipt_settlement.validate_receipt_file",
                    args: {
                        settlement_name: frm.doc.name,
                    },
                    freeze: true,
                    freeze_message: __("Validating receipt file..."),
                    callback(response) {
                        frm.reload_doc();
                        const result = response.message || {};
                        if (result.valid) {
                            frappe.msgprint(
                                __(
                                    "Validated {0} claim(s), total amount {1}.",
                                    [result.total_claims, result.total_amount]
                                )
                            );
                        } else {
                            frappe.msgprint(
                                __(
                                    "Validation failed. Check the Validation Log and claim rows."
                                )
                            );
                        }
                    },
                });
            });
        }

        if (frm.doc.docstatus === 1 && ["Validated", "Failed"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Process Receipt Settlement"), () => {
                frappe.confirm(
                    __("Create Payment Entry and update payer claim settlement?"),
                    () => {
                        frm.call({
                            method:
                                "lifeline_tpa.lifeline_tpa.doctype.payer_receipt_settlement.payer_receipt_settlement.process_receipt_settlement",
                            args: {
                                settlement_name: frm.doc.name,
                            },
                            freeze: true,
                            freeze_message: __("Processing receipt settlement..."),
                            callback() {
                                frm.reload_doc();
                            },
                        });
                    }
                );
            });
        }
    },
});
