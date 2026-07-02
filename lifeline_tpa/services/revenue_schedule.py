from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


SCHEDULE_PRECISION = Decimal("0.000001")
POSTING_PRECISION = Decimal("0.01")


@dataclass(frozen=True)
class RevenueScheduleLine:
    recognition_month: date
    month_start: date
    month_end: date
    service_days: int
    eligible_days: int
    scheduled_amount: Decimal

    def as_dict(self):
        return {
            "recognition_month": self.recognition_month,
            "month_start": self.month_start,
            "month_end": self.month_end,
            "service_days": self.service_days,
            "eligible_days": self.eligible_days,
            "scheduled_amount": self.scheduled_amount,
        }


def build_revenue_schedule(*, amount, service_start, service_end):
    amount = Decimal(str(amount))
    if not service_start or not service_end:
        raise ValueError("Revenue schedule requires both service_start and service_end.")
    if service_end <= service_start:
        raise ValueError("Revenue schedule service_end must be after service_start.")

    service_days = (service_end - service_start).days
    if service_days <= 0:
        raise ValueError("Revenue schedule must have at least one service day.")

    lines = []
    current = first_day_of_month(service_start)
    final_month = first_day_of_month(service_end)
    accumulated = Decimal("0")

    while current <= final_month:
        next_month = add_month(current)
        overlap_start = max(service_start, current)
        overlap_end = min(service_end, next_month)
        eligible_days = max((overlap_end - overlap_start).days, 0)

        if eligible_days:
            if next_month > service_end or first_day_of_month(next_month) > final_month:
                scheduled_amount = amount - accumulated
            else:
                scheduled_amount = (
                    amount * Decimal(eligible_days) / Decimal(service_days)
                ).quantize(SCHEDULE_PRECISION, rounding=ROUND_HALF_UP)
                accumulated += scheduled_amount

            lines.append(
                RevenueScheduleLine(
                    recognition_month=current,
                    month_start=current,
                    month_end=next_month,
                    service_days=service_days,
                    eligible_days=eligible_days,
                    scheduled_amount=scheduled_amount,
                )
            )
        current = next_month

    if lines:
        total = sum((line.scheduled_amount for line in lines), Decimal("0"))
        if total != amount:
            last = lines[-1]
            lines[-1] = RevenueScheduleLine(
                recognition_month=last.recognition_month,
                month_start=last.month_start,
                month_end=last.month_end,
                service_days=last.service_days,
                eligible_days=last.eligible_days,
                scheduled_amount=last.scheduled_amount + amount - total,
            )
    return lines


def rounded_posting_amount(amount):
    return Decimal(str(amount)).quantize(POSTING_PRECISION, rounding=ROUND_HALF_UP)


def first_day_of_month(value):
    return date(value.year, value.month, 1)


def add_month(value):
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)
