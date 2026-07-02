frappe.ui.form.on("TPA Revenue Batch", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.docstatus === 0 && frm.doc.source_file) {
			frm.add_custom_button(
				__("Validate Revenue File"),
				() => {
					frappe.call({
						method: "lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_batch.tpa_revenue_batch.validate_revenue_file",
						args: { batch_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Validating endorsement report..."),
					}).then((response) => {
						const result = response.message;
						frm.reload_doc();
						if (result.valid) {
							frappe.msgprint(
								__(
									"Validation passed: {0} revenue row(s), net TPA fee {1}.",
									[
										result.total_events,
										format_currency(result.net_tpa_fee),
									],
								),
							);
						} else {
							frappe.msgprint(
								__(
									"Validation failed with {0} error(s). Review the Validation Log.",
									[result.errors.length],
								),
							);
						}
					});
				},
				__("Actions"),
			);
		}

		if (frm.doc.docstatus === 0 && frm.doc.status === "Validated") {
			frm.add_custom_button(
				__("Import Revenue Events"),
				() => {
					frappe.call({
						method: "lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_batch.tpa_revenue_batch.import_revenue_events",
						args: { batch_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Importing revenue events..."),
					}).then((response) => {
						frm.reload_doc();
						frappe.msgprint(
							__("Imported {0} revenue event(s).", [
								response.message.imported_events,
							]),
						);
					});
				},
				__("Actions"),
			);
		}

		if (["Imported", "Processed"].includes(frm.doc.status)) {
			frm.add_custom_button(
				__("Preview Revenue Documents"),
				() => {
					frappe.call({
						method: "lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_batch.tpa_revenue_batch.preview_revenue_documents",
						args: { batch_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Building revenue document preview..."),
					}).then((response) => {
						const result = response.message;
						frappe.msgprint(
							__(
								"{0} document(s), {1} event(s), net total {2}.",
								[
									result.document_count,
									result.event_count,
									format_currency(result.net_total),
								],
							),
						);
					});
				},
				__("Actions"),
			);
		}

		if (
			frm.doc.docstatus === 1 &&
			["Imported", "Failed"].includes(frm.doc.status)
		) {
			frm.add_custom_button(
				frm.doc.status === "Failed"
					? __("Retry Revenue Processing")
					: __("Process Revenue Batch"),
				() => {
					frappe.confirm(
						__(
							"This will submit Sales Invoices, Sales Credit Notes, deferral Journal Entries, and revenue schedules. Continue?",
						),
						() => {
							frappe.call({
								method: "lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_batch.tpa_revenue_batch.enqueue_revenue_processing",
								args: { batch_name: frm.doc.name },
								freeze: true,
								freeze_message: __("Queueing revenue processing..."),
							}).then((response) => {
								frm.reload_doc();
								frappe.msgprint(
									__(
										"Revenue processing started. Job ID: {0}",
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
