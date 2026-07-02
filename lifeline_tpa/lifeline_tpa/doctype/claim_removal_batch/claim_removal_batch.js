frappe.ui.form.on("Claim Removal Batch", {
	refresh(frm) {
		frm.add_custom_button(
			__("Download Upload Template"),
			() => {
				window.open(
					"/assets/lifeline_tpa/files/claim_removal_upload_template.xlsx",
					"_blank",
				);
			},
			__("Actions"),
		);

		if (frm.is_new()) {
			return;
		}

		if (frm.doc.docstatus === 0 && frm.doc.source_file) {
			frm.add_custom_button(
				__("Validate Removal File"),
				() => {
					frappe.call({
						method: "lifeline_tpa.lifeline_tpa.doctype.claim_removal_batch.claim_removal_batch.validate_removal_file",
						args: { batch_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Validating claim removals..."),
					}).then((response) => {
						const result = response.message;
						frm.reload_doc();
						if (result.valid) {
							frappe.msgprint(
								__(
									"Validation passed: {0} claims totaling {1}. Submit the batch when ready.",
									[
										result.total_claims,
										format_currency(result.total_amount),
									],
								),
							);
						} else {
							frappe.msgprint(
								__(
									"Validation failed with {0} error(s). Review the Validation Log and claim rows.",
									[result.errors.length],
								),
							);
						}
					});
				},
				__("Actions"),
			);
		}

		if (
			frm.doc.docstatus === 1 &&
			["Validated", "Failed"].includes(frm.doc.status)
		) {
			frm.add_custom_button(
				frm.doc.status === "Failed"
					? __("Retry Claim Removals")
					: __("Process Claim Removals"),
				() => {
					frappe.confirm(
						__(
							"Active unprocessed claims will be marked Removed. Processed claims will create submitted Purchase Debit Notes and Sales Credit Notes. Continue?",
						),
						() => {
							frappe.call({
								method: "lifeline_tpa.lifeline_tpa.doctype.claim_removal_batch.claim_removal_batch.enqueue_claim_removals",
								args: { batch_name: frm.doc.name },
								freeze: true,
								freeze_message: __("Queueing claim removals..."),
							}).then((response) => {
								frm.reload_doc();
								frappe.msgprint(
									__(
										"Claim removal processing started. Job ID: {0}",
										[response.message.job_id],
									),
								);
							});
						},
					);
				},
				__("Actions"),
			);
		}
	},
});
