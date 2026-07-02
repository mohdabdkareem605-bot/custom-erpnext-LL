from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BulkClaim:
    claim_reference: str
    facility_id: str
    provider: str
    amount: Decimal


@dataclass(frozen=True)
class ProviderInvoiceGroup:
    facility_id: str
    provider: str
    claim_count: int
    total_amount: Decimal
    claim_references: tuple[str, ...]
    claim_lines: tuple[BulkClaim, ...]

    def as_dict(self):
        return {
            "facility_id": self.facility_id,
            "provider": self.provider,
            "claim_count": self.claim_count,
            "total_amount": float(self.total_amount),
            "claim_references": list(self.claim_references),
        }


def group_claims_for_bulk_processing(claims):
    grouped = {}
    for claim in claims:
        amount = Decimal(str(claim.amount))
        if amount <= 0:
            raise ValueError(
                f"Claim {claim.claim_reference} must have an amount greater than zero."
            )
        if not claim.facility_id or not claim.provider:
            raise ValueError(
                f"Claim {claim.claim_reference} is missing its provider mapping."
            )

        key = (claim.facility_id, claim.provider)
        grouped.setdefault(key, []).append(
            BulkClaim(
                claim_reference=claim.claim_reference,
                facility_id=claim.facility_id,
                provider=claim.provider,
                amount=amount,
            )
        )

    result = []
    for (facility_id, provider), provider_claims in grouped.items():
        result.append(
            ProviderInvoiceGroup(
                facility_id=facility_id,
                provider=provider,
                claim_count=len(provider_claims),
                total_amount=sum(
                    (claim.amount for claim in provider_claims),
                    Decimal("0"),
                ),
                claim_references=tuple(
                    claim.claim_reference for claim in provider_claims
                ),
                claim_lines=tuple(provider_claims),
            )
        )

    return sorted(result, key=lambda group: (-group.claim_count, group.facility_id))


def summarize_bulk_groups(groups):
    purchase_total = sum(
        (group.total_amount for group in groups),
        Decimal("0"),
    )
    sales_total = purchase_total
    return {
        "provider_count": len(groups),
        "claim_count": sum(group.claim_count for group in groups),
        "purchase_total": float(purchase_total),
        "sales_total": float(sales_total),
        "clearing_difference": float(purchase_total - sales_total),
    }
