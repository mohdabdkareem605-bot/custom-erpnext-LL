frappe.ui.form.on("TPA Revenue Recognition Run", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(
				__("Preview Accrued Revenue"),
				() => {
					frappe.call({
						method: "lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_recognition_run.tpa_revenue_recognition_run.preview_recognition_run",
						args: { run_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Calculating accrued revenue..."),
					}).then((response) => {
						const result = response.message;
						frm.reload_doc();
						frappe.msgprint(
							__(
								"{0} pending schedule row(s), accrued amount {1}.",
								[
									result.total_schedule_rows,
									format_currency(result.posted_amount),
								],
							),
						);
					});
				},
				__("Actions"),
			);
		}

		if (frm.doc.docstatus === 1 && frm.doc.status === "Previewed") {
			frm.add_custom_button(
				__("Post Recognition Journal Entry"),
				() => {
					frappe.confirm(
						__(
							"This will post the month-end revenue recognition Journal Entry and mark schedules as posted. Continue?",
						),
						() => {
							frappe.call({
								method: "lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_recognition_run.tpa_revenue_recognition_run.post_recognition_run",
								args: { run_name: frm.doc.name },
								freeze: true,
								freeze_message: __("Posting revenue recognition..."),
							}).then((response) => {
								frm.reload_doc();
								frappe.msgprint(
									__(
										"Posted Journal Entry {0} for {1}.",
										[
											response.message.journal_entry,
											format_currency(response.message.posted_amount),
										],
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
