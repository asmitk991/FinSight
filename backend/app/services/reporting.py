from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

from app.models.schemas import CategoryBreakdown, MerchantBreakdown, ReportResponse, TransactionRecord
from app.services.category import format_amount
from app.services.currency import convert_to_inr


def summarize_transactions(transactions: list[TransactionRecord], start_date, end_date) -> ReportResponse:
    spend_transactions = [tx for tx in transactions if tx.type.value == "debit"]
    total_spend = sum(convert_to_inr(tx.amount, tx.currency) for tx in spend_transactions)
    by_category = defaultdict(float)
    merchant_totals = defaultdict(float)
    merchant_counts = Counter()

    for tx in spend_transactions:
        amount_inr = convert_to_inr(tx.amount, tx.currency)
        by_category[tx.category] += amount_inr
        merchant_totals[tx.merchant] += amount_inr
        merchant_counts[tx.merchant] += 1

    category_breakdown = [
        CategoryBreakdown(category=category, total=round(total, 2), percentage=round((total / total_spend) * 100, 2) if total_spend else 0)
        for category, total in sorted(by_category.items(), key=lambda item: item[1], reverse=True)
    ]
    top_merchants = [
        MerchantBreakdown(merchant=merchant, total=round(total, 2), count=merchant_counts[merchant])
        for merchant, total in sorted(merchant_totals.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    largest_transactions = sorted(spend_transactions, key=lambda tx: convert_to_inr(tx.amount, tx.currency), reverse=True)[:5]
    avg_amount = mean([convert_to_inr(tx.amount, tx.currency) for tx in spend_transactions]) if spend_transactions else 0
    anomalies = [tx for tx in spend_transactions if avg_amount and convert_to_inr(tx.amount, tx.currency) >= avg_amount * 2][:5]
    narrative = _build_narrative(total_spend, category_breakdown, top_merchants, anomalies, spend_transactions)

    return ReportResponse(
        start_date=start_date,
        end_date=end_date,
        total_spend=round(total_spend, 2),
        category_breakdown=category_breakdown,
        top_merchants=top_merchants,
        largest_transactions=largest_transactions,
        anomalies=anomalies,
        narrative=narrative,
        supporting_transactions=transactions,
    )


def aggregate_metrics(transactions: list[TransactionRecord]) -> dict:
    spend_transactions = [tx for tx in transactions if tx.type.value == "debit"]
    by_category = defaultdict(float)
    by_day = defaultdict(float)
    by_merchant = defaultdict(float)
    by_transfer_kind = defaultdict(float)
    for tx in spend_transactions:
        amount_inr = convert_to_inr(tx.amount, tx.currency)
        by_category[tx.category] += amount_inr
        by_day[tx.date.date().isoformat()] += amount_inr
        by_merchant[tx.merchant] += amount_inr
        if tx.transfer_kind:
            by_transfer_kind[tx.transfer_kind.value] += amount_inr
    return {
        "total_spend": round(sum(convert_to_inr(tx.amount, tx.currency) for tx in spend_transactions), 2),
        "count": len(transactions),
        "category_totals": dict(sorted(by_category.items(), key=lambda item: item[1], reverse=True)),
        "day_totals": dict(sorted(by_day.items())),
        "merchant_totals": dict(sorted(by_merchant.items(), key=lambda item: item[1], reverse=True)),
        "transfer_kind_totals": dict(sorted(by_transfer_kind.items(), key=lambda item: item[1], reverse=True)),
        "largest_transaction": max((convert_to_inr(tx.amount, tx.currency) for tx in spend_transactions), default=0),
    }


def _build_narrative(total_spend, categories, merchants, anomalies, spend_transactions) -> str:
    leading_category = categories[0].category if categories else "other"
    leading_merchant = merchants[0].merchant if merchants else "N/A"
    anomaly_count = len(anomalies)
    total_label = format_amount(total_spend, "INR")
    return (
        f"Total spend was {total_label}. "
        f"The largest category was {leading_category}, and {leading_merchant} was the top merchant by value. "
        f"{anomaly_count} transactions were materially above the usual spend pattern."
    )
