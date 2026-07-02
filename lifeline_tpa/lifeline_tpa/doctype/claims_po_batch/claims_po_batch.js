frappe.ui.form.on("Claims PO Batch", {
	refresh(frm) {
		frm.add_custom_button(
			__("Download Upload Template"),
			() => {
				window.open(
					"/assets/lifeline_tpa/files/claims_po_upload_template.xlsx",
					"_blank",
				);
			},
			__("Actions"),
		);

		if (frm.is_new()) {
			return;
		}

		if (frm.doc.docstatus === 1 && frm.doc.status === "Imported") {
			frm.add_custom_button(
				__("Preview Bulk Processing"),
				() => {
					frappe.call({
						method: "lifeline_tpa.lifeline_tpa.doctype.claims_po_batch.claims_po_batch.preview_bulk_processing",
						args: { batch_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Building accounting preview..."),
					}).then((response) => {
						show_bulk_processing_preview(response.message);
					});
				},
				__("Actions"),
			);
			add_bulk_processing_button(frm, false);
		}

		if (frm.doc.docstatus === 1 && frm.doc.status === "Failed") {
			add_bulk_processing_button(frm, true);
		}

		if (
			frm.doc.docstatus === 1 &&
			["Processed", "Partially Settled", "Fully Settled"].includes(
				frm.doc.status,
			)
		) {
			frm.add_custom_button(
				__("Download Processed PO"),
				() => {
					const method =
						"lifeline_tpa.lifeline_tpa.doctype.claims_po_batch.claims_po_batch.download_processed_po";
					window.location.href = `/api/method/${method}?batch_name=${encodeURIComponent(
						frm.doc.name,
					)}`;
				},
				__("Actions"),
			);
		}

		if (frm.doc.docstatus !== 0) {
			return;
		}

		if (frm.doc.source_file && frm.doc.status !== "Imported") {
			frm.add_custom_button(__("Validate PO File"), () => {
				frappe.call({
					method: "lifeline_tpa.lifeline_tpa.doctype.claims_po_batch.claims_po_batch.validate_po_file",
					args: { batch_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Validating PO workbook..."),
				}).then((response) => {
					const result = response.message;
					frm.reload_doc();
					if (result.valid) {
						frappe.msgprint(
							__(
								"Validation passed: {0} claims, {1} providers, total {2}.",
								[
									result.total_claims,
									result.total_providers,
									format_currency(result.total_amount, result.currency),
								],
							),
						);
					} else {
						frappe.msgprint(
							__("Validation failed with {0} error(s). Review the Validation Log.", [
								result.errors.length,
							]),
						);
					}
				});
			});
		}

		if (frm.doc.status === "Validated") {
			frm.add_custom_button(
				__("Import Claims"),
				() => {
					frappe.confirm(
						__("Create {0} Claim Record documents from this workbook?", [
							frm.doc.total_claims,
						]),
						() => {
							frappe.call({
								method: "lifeline_tpa.lifeline_tpa.doctype.claims_po_batch.claims_po_batch.import_claims",
								args: { batch_name: frm.doc.name },
								freeze: true,
								freeze_message: __("Importing claims..."),
							}).then((response) => {
								frm.reload_doc();
								frappe.show_alert({
									message: __("{0} claims imported.", [
										response.message.imported_claims,
									]),
									indicator: "green",
								});
							});
						},
					);
				},
				__("Actions"),
			);
		}
	},
});

function add_bulk_processing_button(frm, is_retry) {
	frm.add_custom_button(
		is_retry ? __("Retry Bulk Processing") : __("Run Bulk Processing"),
		() => {
			frappe.confirm(
				__(
					"This will submit Purchase and Sales Invoices and post General Ledger entries. Continue?",
				),
				() => {
					frappe.call({
						method: "lifeline_tpa.lifeline_tpa.doctype.claims_po_batch.claims_po_batch.enqueue_bulk_processing",
						args: { batch_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Queueing bulk processing..."),
					}).then((response) => {
						frm.reload_doc();
						frappe.msgprint(
							__(
								"Bulk processing started in the background. Job ID: {0}",
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

function show_bulk_processing_preview(preview) {
	const rows = preview.rows
		.map(
			(row) => `
				<tr>
					<td>${frappe.utils.escape_html(row.provider)}</td>
					<td>${frappe.utils.escape_html(row.facility_id)}</td>
					<td class="text-right">${row.claim_count}</td>
					<td class="text-right">${format_currency(row.total_amount, preview.currency)}</td>
					<td class="text-right">${format_currency(row.purchase_invoice.grand_total, preview.currency)}</td>
					<td class="text-right">${format_currency(row.sales_invoice.grand_total, preview.currency)}</td>
					<td class="text-right">${format_currency(row.difference, preview.currency)}</td>
				</tr>
			`,
		)
		.join("");

	const dialog = new frappe.ui.Dialog({
		title: __("Bulk Processing Preview"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "preview",
				options: `
					<div class="mb-3">
						<p><strong>${__("No accounting documents will be posted from this preview.")}</strong></p>
						<p>
							${__("Providers")}: ${preview.provider_count}
							&nbsp; | &nbsp; ${__("Claims")}: ${preview.claim_count}
							&nbsp; | &nbsp; ${__("Total")}: ${format_currency(preview.purchase_total, preview.currency)}
							&nbsp; | &nbsp; ${__("Clearing Difference")}: ${format_currency(preview.clearing_difference, preview.currency)}
						</p>
					</div>
					<div class="table-responsive">
						<table class="table table-bordered">
							<thead>
								<tr>
									<th>${__("Provider")}</th>
									<th>${__("Facility ID")}</th>
									<th class="text-right">${__("Claims")}</th>
									<th class="text-right">${__("Group Total")}</th>
									<th class="text-right">${__("Purchase Invoice Total")}</th>
									<th class="text-right">${__("Sales Invoice Total")}</th>
									<th class="text-right">${__("Difference")}</th>
								</tr>
							</thead>
							<tbody>${rows}</tbody>
						</table>
					</div>
				`,
			},
		],
		primary_action_label: __("Close"),
		primary_action() {
			dialog.hide();
		},
	});
	dialog.show();
}
