from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from statistics import mean as _mean
from typing import Any, Literal

from app.models.schemas import AgentQueryResponse, TransactionRecord
from app.services.category import find_item_group, format_amount, infer_question_category, item_belongs_to_group
from app.services.currency import convert_to_inr
from app.services.llm import LlmService
from app.services.reporting import aggregate_metrics, summarize_transactions
from app.services.transaction_store import TransactionRepository


ActionType = Literal["sum", "list", "top_counterparty", "max_transaction", "category_breakdown", "overview", "compare", "trend"]
DirectionType = Literal["sent", "received", "any"]


@dataclass
class QueryPlan:
    action: ActionType
    direction: DirectionType = "any"
    category: str | None = None
    transfer_kind: str | None = None
    counterparty: str | None = None
    item_name: str | None = None
    item_group: str | None = None
    month: int | None = None
    year: int | None = None
    comparison_month: int | None = None
    comparison_year: int | None = None
    limit: int = 8


class FinanceAgentService:
    def __init__(self) -> None:
        self.transactions = TransactionRepository()
        self.llm = LlmService()

    def query(
        self,
        user_id: str,
        question: str,
        top_k: int = 8,
        start_date: date | None = None,
        end_date: date | None = None,
        category: str | None = None,
    ) -> AgentQueryResponse:
        # 1. Semantic Search (RAG) via pgvector
        question_vector = self.llm.generate_embedding(question)
        filtered = []
        
        if question_vector:
            filtered = self.transactions.match_transactions(user_id, question_vector, match_threshold=0.60, match_count=max(top_k, 15))
            
        # 2. Fallback to general logic if RAG yields no results (e.g. no vectors created yet)
        if not filtered:
            transactions = self.transactions.list_transactions(user_id, start_date=start_date, end_date=end_date, category=None)
            plan = self._build_plan(question, transactions, top_k=top_k, explicit_category=category)
            filtered = self._apply_plan(transactions, plan)
            metrics = self._build_metrics(filtered)
            needs_clarification = self._needs_clarification(plan, question, filtered)
            answer = self._format_answer(question, plan, filtered, metrics)
            supporting = [] if needs_clarification else self._select_supporting(plan, filtered)
            return AgentQueryResponse(answer=answer, supporting_transactions=supporting, metrics=metrics)
            
        # 3. Augmented Generation
        metrics = self._build_metrics(filtered)
        answer = self.llm.generate_agent_response(question, metrics)
        
        return AgentQueryResponse(answer=answer, supporting_transactions=filtered[:top_k], metrics=metrics)

    def report(self, user_id: str, start_date: date, end_date: date):
        transactions = self.transactions.list_transactions(user_id, start_date=start_date, end_date=end_date)
        return summarize_transactions(transactions, start_date, end_date)

    def executive_report(self, user_id: str, start_date: date | None = None, end_date: date | None = None) -> dict:
        from app.services.currency import convert_to_inr as _cvt

        transactions = self.transactions.list_transactions(user_id, start_date=start_date, end_date=end_date)
        spend_txs = [tx for tx in transactions if tx.type.value == "debit"]

        if not transactions:
            return {
                "headline": "No transactions found.",
                "overview": "Upload a PDF statement or receipt images to generate your executive report.",
                "behavioral_insights": [],
                "recommendations": ["Upload a UPI statement PDF to get started.", "Add receipt images via the Sync Receipts button."],
                "health_score": 0,
                "health_label": "No Data",
                "period_label": "All time",
                "total_spend": 0.0,
                "top_category": "N/A",
                "top_merchant": "N/A",
            }

        metrics = aggregate_metrics(transactions)
        top_category = next(iter(metrics.get("category_totals", {})), "N/A")
        top_merchant = next(iter(metrics.get("merchant_totals", {})), "N/A")
        total_spend = metrics.get("total_spend", 0.0)

        # Period label
        if spend_txs:
            dates_sorted = sorted(tx.date for tx in spend_txs)
            period_label = f"{dates_sorted[0].strftime('%d %b %Y')} – {dates_sorted[-1].strftime('%d %b %Y')}"
        else:
            period_label = "All time"

        amounts = [_cvt(tx.amount, tx.currency) for tx in spend_txs]

        # ── Time-of-day analysis ──────────────────────────────────────────
        # Bands: morning 6-12, afternoon 12-18, evening 18-24, night 0-6
        time_bands: dict[str, float] = {"morning (6AM–12PM)": 0.0, "afternoon (12PM–6PM)": 0.0, "evening (6PM–12AM)": 0.0, "night (12AM–6AM)": 0.0}
        for tx in spend_txs:
            h = tx.date.hour
            amt = _cvt(tx.amount, tx.currency)
            if 6 <= h < 12:
                time_bands["morning (6AM–12PM)"] += amt
            elif 12 <= h < 18:
                time_bands["afternoon (12PM–6PM)"] += amt
            elif 18 <= h < 24:
                time_bands["evening (6PM–12AM)"] += amt
            else:
                time_bands["night (12AM–6AM)"] += amt
        peak_time_band = max(time_bands, key=lambda k: time_bands[k])
        time_band_pcts = {k: round(v / total_spend * 100, 1) if total_spend else 0 for k, v in time_bands.items()}

        # ── Per-merchant time-of-day ──────────────────────────────────────
        merchant_hours: dict[str, list[int]] = defaultdict(list)
        for tx in spend_txs:
            merchant_hours[tx.merchant].append(tx.date.hour)
        merchant_peak_times = {}
        for merchant, hours in merchant_hours.items():
            avg_h = sum(hours) / len(hours)
            after_noon_count = sum(1 for h in hours if h >= 12)
            pct_after_noon = round(after_noon_count / len(hours) * 100)
            merchant_peak_times[merchant] = {
                "avg_hour": round(avg_h, 1),
                "pct_after_noon": pct_after_noon,
                "visit_count": len(hours),
            }
        # Only send top 5 merchants by visit count to keep prompt tight
        top_merchant_times = dict(
            sorted(merchant_peak_times.items(), key=lambda x: x[1]["visit_count"], reverse=True)[:5]
        )

        # ── Monthly Trend & First-Half Averaging ──────────────────────────
        # If period > 35 days, we calculate averages per month to avoid confusing the user
        days_diff = (dates_sorted[-1] - dates_sorted[0]).days if spend_txs else 0
        is_multi_month = days_diff > 35

        by_month = defaultdict(lambda: {"total": 0.0, "first_half": 0.0, "second_half": 0.0, "count": 0})
        for tx in spend_txs:
            m_key = tx.date.strftime("%Y-%m")
            amt = _cvt(tx.amount, tx.currency)
            by_month[m_key]["total"] += amt
            by_month[m_key]["count"] += 1
            if tx.date.day <= 15:
                by_month[m_key]["first_half"] += amt
            else:
                by_month[m_key]["second_half"] += amt
        
        # Sort months for trend
        sorted_months = sorted(by_month.items())
        month_labels = [m for m, _ in sorted_months]
        month_totals = [round(d["total"], 2) for _, d in sorted_months]
        
        # Calculate MoM change for the last two months if available
        mom_pct = 0.0
        if len(sorted_months) >= 2:
            prev = sorted_months[-2][1]["total"]
            curr = sorted_months[-1][1]["total"]
            if prev > 0:
                mom_pct = round(((curr - prev) / prev) * 100, 1)

        # Average first vs second half across available months
        avg_first_half = _mean([d["first_half"] for _, d in sorted_months]) if sorted_months else 0.0
        avg_second_half = _mean([d["second_half"] for _, d in sorted_months]) if sorted_months else 0.0
        
        # ── Day-of-week analysis ──────────────────────────────────────────
        dow_map = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
        dow_spend: dict[str, float] = defaultdict(float)
        dow_count: dict[str, int] = defaultdict(int)
        for tx in spend_txs:
            day_name = dow_map[tx.date.weekday()]
            dow_spend[day_name] += _cvt(tx.amount, tx.currency)
            dow_count[day_name] += 1
        peak_dow = max(dow_spend, key=lambda k: dow_spend[k]) if dow_spend else "N/A"
        weekend_spend = dow_spend.get("Saturday", 0) + dow_spend.get("Sunday", 0)
        weekday_spend = total_spend - weekend_spend
        weekend_txs_count = dow_count.get("Saturday", 0) + dow_count.get("Sunday", 0)

        # ── Impulse spend analysis ─────────────────────────────────────────
        # Definition: Small, non-routine purchases. Routine small spends (coffee, tea, commute) aren't impulsive.
        NON_IMPULSIVE_CATEGORIES = {"food", "transport", "utilities", "groceries", "transfer", "self_transfer"}
        impulse_threshold = 400
        
        impulse_spend_txs = [
            tx for tx in spend_txs 
            if _cvt(tx.amount, tx.currency) < impulse_threshold 
            and tx.category not in NON_IMPULSIVE_CATEGORIES
        ]
        
        impulse_count = len(impulse_spend_txs)
        impulse_pct = round(impulse_count / len(spend_txs) * 100) if spend_txs else 0
        impulse_total = sum(_cvt(tx.amount, tx.currency) for tx in impulse_spend_txs)

        # ── Merchant concentration ────────────────────────────────────────
        merchant_totals_sorted = sorted(metrics.get("merchant_totals", {}).items(), key=lambda x: x[1], reverse=True)
        top3_spend = sum(v for _, v in merchant_totals_sorted[:3])
        top3_concentration_pct = round(top3_spend / total_spend * 100) if total_spend else 0
        top3_names = [k for k, _ in merchant_totals_sorted[:3]]

        # ── Merchant visit frequency ──────────────────────────────────────
        merchant_visit_counts = Counter(tx.merchant for tx in spend_txs)
        most_frequent_merchant, most_frequent_count = merchant_visit_counts.most_common(1)[0] if merchant_visit_counts else ("N/A", 0)

        # ── Total Behavior Metrics ────────────────────────────────────────
        prompt_payload = {
            "period": period_label,
            "total_spend_inr": round(total_spend, 2),
            "transaction_count": len(transactions),
            "spend_transaction_count": len(spend_txs),
            "top_category": top_category,
            "top_merchant": top_merchant,
            # Temporal patterns
            "time_of_day_spend_inr": {k: round(v, 2) for k, v in time_bands.items()},
            "time_of_day_pct": time_band_pcts,
            "peak_time_band": peak_time_band,
            # Per-merchant time behaviour (top 5 by visits)
            "merchant_time_patterns": top_merchant_times,
            # Half-of-month (averaged if multi-month)
            "is_multi_month": is_multi_month,
            "monthly_trend": sorted_months,
            "mom_change_pct": mom_pct,
            "avg_first_half_spend_inr": round(avg_first_half, 2),
            "avg_second_half_spend_inr": round(avg_second_half, 2),
            "first_vs_second_half_ratio": round(avg_first_half / avg_second_half, 2) if avg_second_half else None,
            # Day of week
            "day_of_week_spend_inr": {k: round(v, 2) for k, v in dow_spend.items()},
            "peak_day_of_week": peak_dow,
            "weekend_spend_inr": round(weekend_spend, 2),
            "weekday_spend_inr": round(weekday_spend, 2),
            "weekend_tx_count": weekend_txs_count,
            # Impulse (Refined)
            "impulse_tx_count": impulse_count,
            "impulse_tx_pct": impulse_pct,
            "impulse_total_inr": round(impulse_total, 2),
            "impulse_threshold_inr": impulse_threshold,
            "impulse_merchants": [tx.merchant for tx in impulse_spend_txs[:5]],
            # Concentration
            "top3_merchants": top3_names,
            "top3_merchant_concentration_pct": top3_concentration_pct,
            # Most frequent merchant
            "most_visited_merchant": most_frequent_merchant,
            "most_visited_count": most_frequent_count,
        }

        result = self.llm.generate_executive_report(prompt_payload)

        if result:
            result["period_label"] = period_label
            result["total_spend"] = round(total_spend, 2)
            result["top_category"] = top_category
            result["top_merchant"] = top_merchant
            # Normalize key: LLM might return key_insights; remap to behavioral_insights
            if "key_insights" in result and "behavioral_insights" not in result:
                result["behavioral_insights"] = result.pop("key_insights")
            result.pop("anomalies", None)
            return result

        # Rules-based fallback
        ratio_str = f"{round(avg_first_half / avg_second_half, 1)}x" if avg_second_half else "N/A"
        return {
            "headline": f"You spent {impulse_pct}% of transactions as impulse buys — and peak spending was in the {peak_time_band}.",
            "overview": (
                f"Across {len(spend_txs)} transactions totalling ₹{total_spend:,.0f}, "
                f"your most visited merchant was {most_frequent_merchant} ({most_frequent_count} visits). "
                f"You spent {ratio_str} more in the first half of the month than the second."
            ),
            "behavioral_insights": [
                f"{impulse_pct}% of your transactions were under ₹{impulse_threshold}, suggesting frequent small impulse purchases.",
                f"On average, you spend {ratio_str} more in the first half of the month (₹{avg_first_half:,.0f}) than the second (₹{avg_second_half:,.0f}).",
                f"{peak_dow} was your highest-spend day of the week.",
                f"Top 3 merchants ({', '.join(top3_names)}) account for {top3_concentration_pct}% of your total spend.",
            ],
            "recommendations": [
                f"Set a daily cap for impulse purchases under ₹{impulse_threshold} — they add up to ₹{impulse_total:,.0f}.",
                f"Your spend is concentrated at {', '.join(top3_names[:2])}. Diversifying or setting merchant-level limits would improve financial resilience.",
            ],
            "health_score": 55,
            "health_label": "Fair",
            "period_label": period_label,
            "total_spend": round(total_spend, 2),
            "top_category": top_category,
            "top_merchant": top_merchant,
        }

    def _build_plan(
        self,
        question: str,
        transactions: list[TransactionRecord],
        top_k: int,
        explicit_category: str | None,
    ) -> QueryPlan:
        llm_plan = self._build_plan_with_llm(question, transactions, top_k=top_k, explicit_category=explicit_category)
        if llm_plan:
            return llm_plan

        lower = question.lower().strip()
        plan = QueryPlan(action="overview", category=explicit_category or infer_question_category(question), limit=max(top_k, 8))
        
        m1, y1, m2, y2 = self._extract_comparison_months(question, transactions)
        plan.month = m1
        plan.year = y1
        if m2:
            plan.action = "compare"
            plan.comparison_month = m2
            plan.comparison_year = y2

        if any(phrase in lower for phrase in ["show me", "list", "which transactions", "all the transactions"]):
            plan.action = "list"
            plan.limit = max(top_k, 20)
        elif any(phrase in lower for phrase in ["compare", "vs", "versus"]):
            plan.action = "compare"
        elif any(phrase in lower for phrase in ["how much", "total", "sum"]):
            plan.action = "sum"
        elif any(phrase in lower for phrase in ["biggest", "largest", "max transaction", "highest single"]):
            plan.action = "max_transaction"
        elif any(phrase in lower for phrase in ["where did i spend the most", "who did i spend the most with", "highest-spend counterparty"]):
            plan.action = "top_counterparty"
        elif any(phrase in lower for phrase in ["by category", "category breakdown", "categories"]):
            plan.action = "category_breakdown"

        if "self transfer" in lower or "other account" in lower:
            plan.transfer_kind = "self_transfer"
            plan.category = "self_transfer"
            plan.direction = "sent"
            if plan.action == "overview":
                plan.action = "sum"
        elif any(token in lower for token in ["receive", "received", "credit", "credited"]):
            plan.direction = "received"
            if plan.action == "overview":
                plan.action = "sum"
        elif any(token in lower for token in ["debit", "debited", "send", "sent", "spend", "spent", "pay", "paid"]):
            plan.direction = "sent"
            if plan.action == "overview" and "most" not in lower:
                plan.action = "sum"

        matched_counterparty = self._match_counterparty(question, transactions)
        if matched_counterparty:
            plan.counterparty = matched_counterparty
            if plan.action == "overview":
                plan.action = "list"
                plan.limit = max(top_k, 20)

        matched_item = self._match_line_item(question, transactions)
        if matched_item:
            plan.item_name = matched_item
            plan.direction = "sent"
            if plan.action == "overview":
                plan.action = "sum"
        elif item_group := find_item_group(question):
            plan.item_group = item_group
            plan.direction = "sent"
            if plan.action == "overview":
                plan.action = "sum"

        if plan.action == "overview":
            plan.action = "sum" if plan.category or plan.direction != "any" else "overview"

        return plan

    def _build_plan_with_llm(
        self,
        question: str,
        transactions: list[TransactionRecord],
        top_k: int,
        explicit_category: str | None,
    ) -> QueryPlan | None:
        merchants = sorted({tx.merchant for tx in transactions if tx.merchant})
        payload = self.llm.plan_agent_query(question, merchants)
        if not payload:
            return None

        valid_actions = {"sum", "list", "top_counterparty", "max_transaction", "category_breakdown", "overview", "compare", "trend"}
        valid_directions = {"sent", "received", "any"}
        valid_transfer_kinds = {"self_transfer", "person", "merchant", "reward", "bank", "unknown"}
        valid_categories = {
            "food",
            "transport",
            "groceries",
            "utilities",
            "entertainment",
            "health",
            "shopping",
            "transfer",
            "self_transfer",
            "professional",
            "other",
        }

        action = payload.get("action") or "overview"
        direction = payload.get("direction") or "any"
        category = payload.get("category")
        transfer_kind = payload.get("transfer_kind")
        counterparty = payload.get("counterparty")
        limit = payload.get("limit")

        if action not in valid_actions or direction not in valid_directions:
            return None
        if category not in valid_categories and category is not None:
            category = explicit_category or infer_question_category(question)
        if transfer_kind not in valid_transfer_kinds and transfer_kind is not None:
            transfer_kind = None
        if counterparty and counterparty not in merchants:
            counterparty = self._match_counterparty(counterparty, transactions)
        if explicit_category:
            category = explicit_category

        try:
            parsed_limit = int(limit)
        except (TypeError, ValueError):
            parsed_limit = max(top_k, 8)

        m1 = payload.get("month")
        y1 = payload.get("year")
        m2 = payload.get("comparison_month")
        y2 = payload.get("comparison_year")

        # Fallback to pos-aware extraction
        if m1 is None:
            fm1, fy1, fm2, fy2 = self._extract_comparison_months(question, transactions)
            m1, y1 = fm1, fy1
            if action == "compare" and m2 is None:
                m2, y2 = fm2, fy2

        return QueryPlan(
            action=action,
            direction=direction,
            category=category,
            transfer_kind=transfer_kind,
            counterparty=counterparty,
            item_name=self._match_line_item(question, transactions),
            item_group=find_item_group(question),
            month=m1,
            year=y1,
            comparison_month=m2,
            comparison_year=y2,
            limit=min(parsed_limit, 50),
        )

    def _apply_plan(self, transactions: list[TransactionRecord], plan: QueryPlan) -> list[TransactionRecord]:
        filtered = list(transactions)

        if plan.category:
            filtered = [tx for tx in filtered if tx.category == plan.category]

        if plan.direction == "sent":
            filtered = [tx for tx in filtered if tx.type.value == "debit"]
        elif plan.direction == "received":
            filtered = [tx for tx in filtered if tx.type.value == "credit"]

        if plan.transfer_kind:
            filtered = [tx for tx in filtered if tx.transfer_kind and tx.transfer_kind.value == plan.transfer_kind]

        if plan.counterparty:
            needle = plan.counterparty.lower()
            filtered = [
                tx
                for tx in filtered
                if needle in tx.merchant.lower() or (tx.detail_text and needle in tx.detail_text.lower())
            ]

        if plan.month is not None:
            if plan.action == "compare" and plan.comparison_month is not None:
                # Keep both months
                filtered = [
                    tx for tx in filtered 
                    if (tx.date.month == plan.month and (plan.year is None or tx.date.year == plan.year))
                    or (tx.date.month == plan.comparison_month and (plan.comparison_year is None or tx.date.year == plan.comparison_year))
                ]
            else:
                filtered = [tx for tx in filtered if tx.date.month == plan.month]
                if plan.year is not None:
                    filtered = [tx for tx in filtered if tx.date.year == plan.year]

        if plan.item_name:
            needle = plan.item_name.lower()
            filtered = [
                tx
                for tx in filtered
                if any(needle in item.name.lower() for item in tx.line_items)
            ]
        elif plan.item_group:
            filtered = [
                tx
                for tx in filtered
                if any(item_belongs_to_group(item.name, plan.item_group) for item in tx.line_items)
            ]

        return filtered

    def _select_supporting(self, plan: QueryPlan, filtered: list[TransactionRecord]) -> list[TransactionRecord]:
        if plan.action == "list":
            return filtered[: plan.limit]
        if plan.action == "max_transaction":
            return sorted(filtered, key=lambda tx: tx.amount, reverse=True)[: plan.limit]
        if plan.action == "top_counterparty":
            return sorted([tx for tx in filtered if tx.type.value == "debit"], key=lambda tx: tx.amount, reverse=True)[: plan.limit]
        return filtered[: plan.limit]

    def _build_metrics(self, filtered: list[TransactionRecord]) -> dict[str, Any]:
        metrics = aggregate_metrics(filtered)
        metrics["credit_total"] = round(sum(convert_to_inr(tx.amount, tx.currency) for tx in filtered if tx.type.value == "credit"), 2)
        metrics["debit_total"] = round(sum(convert_to_inr(tx.amount, tx.currency) for tx in filtered if tx.type.value == "debit"), 2)
        metrics["transaction_count"] = len(filtered)
        metrics["line_item_total"] = round(sum(convert_to_inr(item.price or 0, tx.currency) for tx in filtered for item in tx.line_items), 2)
        
        # Monthly breakdown for comparisons
        monthly = defaultdict(float)
        for tx in filtered:
            month_key = tx.date.strftime("%B %Y")
            monthly[month_key] += convert_to_inr(tx.amount, tx.currency)
        metrics["monthly_breakdown"] = dict(sorted(monthly.items(), key=lambda x: datetime.strptime(x[0], "%B %Y") if x[0] else datetime.min))
        
        return metrics

    def _format_answer(self, question: str, plan: QueryPlan, filtered: list[TransactionRecord], metrics: dict[str, Any]) -> str:
        if not filtered:
            return "I couldn't find any matching transactions in the current dataset."

        # Analytical/Complex queries go to LLM
        if plan.action in {"trend", "overview"}:
            return self.llm.generate_agent_response(question, metrics)

        if plan.action == "compare":
            if plan.month is not None and plan.comparison_month is not None:
                monthly = metrics.get("monthly_breakdown", {})
                m1_name = self._month_name(plan.month)
                m2_name = self._month_name(plan.comparison_month)
                
                # We need to find the keys that contain these labels
                m1_key = next((k for k in monthly if m1_name in k), None)
                m2_key = next((k for k in monthly if m2_name in k), None)
                
                v1 = monthly.get(m1_key, 0)
                v2 = monthly.get(m2_key, 0)
                
                diff = v2 - v1
                direction_str = "increased" if diff > 0 else "decreased"
                pct = round(abs(diff / v1) * 100, 1) if v1 else 100
                
                base_msg = f"Comparing {plan.category or plan.counterparty or 'spending'} between {m1_name} and {m2_name}: "
                return base_msg + f"it {direction_str} from {format_amount(v1, 'INR')} to {format_amount(v2, 'INR')} ({pct}% {direction_str})."
            
            return self.llm.generate_agent_response(question, metrics)

        if plan.action == "list":
            descriptor = self._plan_descriptor(plan)
            return f"I found {len(filtered)} {descriptor} transaction(s)."

        if plan.action == "sum":
            if plan.transfer_kind == "self_transfer":
                return f"You self-transferred {format_amount(metrics['debit_total'], 'INR')}{self._scope_suffix(plan)} across {len(filtered)} transaction(s)."
            if plan.item_name:
                item_total, matches, breakdown = self._line_item_summary(filtered, lambda item: plan.item_name.lower() in item.name.lower())
                breakdown_text = ", ".join(f"{name}: {format_amount(amount, 'INR')}" for name, amount in breakdown[:5])
                suffix = f" Matched items: {breakdown_text}." if breakdown_text else ""
                return f"You spent {format_amount(item_total, 'INR')} on {plan.item_name}{self._scope_suffix(plan)} across {matches} line item(s) in {len(filtered)} receipt(s).{suffix}"
            if plan.item_group:
                item_total, matches, breakdown = self._line_item_summary(filtered, lambda item: item_belongs_to_group(item.name, plan.item_group))
                breakdown_text = ", ".join(f"{name}: {format_amount(amount, 'INR')}" for name, amount in breakdown[:8])
                suffix = f" Matched items: {breakdown_text}." if breakdown_text else ""
                return f"You spent {format_amount(item_total, 'INR')} on {plan.item_group}{self._scope_suffix(plan)} across {matches} line item(s) in {len(filtered)} receipt(s).{suffix}"
            if plan.counterparty:
                return (
                    f"I found {len(filtered)} transaction(s) involving {plan.counterparty}{self._scope_suffix(plan)}. "
                    f"Debit total is {format_amount(metrics['debit_total'], 'INR')} and credit total is {format_amount(metrics['credit_total'], 'INR')}."
                )
            if plan.direction == "received":
                return f"You received {format_amount(metrics['credit_total'], 'INR')}{self._scope_suffix(plan)} across {len(filtered)} transaction(s)."
            if plan.direction == "sent":
                label = plan.category.replace("_", " ") if plan.category else "debit"
                return f"You spent {format_amount(metrics['debit_total'], 'INR')} in {label} transactions{self._scope_suffix(plan)} across {len(filtered)} transaction(s)."
            if plan.category:
                amount = metrics["category_totals"].get(plan.category, 0)
                return f"Total {plan.category.replace('_', ' ')} amount is {format_amount(amount, 'INR')}{self._scope_suffix(plan)} across {len(filtered)} transaction(s)."
            return (
                "I’m not confident I understood what slice of transactions you want. "
                "Please be more specific, for example: 'How much did I spend this month?', "
                "'How much did I receive this month?', 'Show my transport transactions', "
                "or 'How much did I pay Isha Kumari?'."
            )

        if plan.action == "max_transaction":
            tx = max(filtered, key=lambda tx: tx.amount)
            return f"The largest matching transaction was {format_amount(tx.amount, tx.currency)} at {tx.merchant} on {tx.date.date().isoformat()}{self._scope_suffix(plan)}."

        if plan.action == "top_counterparty":
            merchant_totals = metrics["merchant_totals"]
            top = next(iter(merchant_totals.items()), None)
            if top:
                return f"Your highest-spend counterparty was {top[0]} at {format_amount(top[1], 'INR')}{self._scope_suffix(plan)}."
            return "I couldn't find a highest-spend counterparty in the matched transactions."

        if plan.action == "category_breakdown":
            pieces = [f"{key}: {format_amount(value, 'INR')}" for key, value in list(metrics["category_totals"].items())[:6]]
            return "Category totals are " + ", ".join(pieces) + "."

        return (
            f"I found {len(filtered)} matching transaction(s){self._scope_suffix(plan)}. "
            f"Debit total is {format_amount(metrics['debit_total'], 'INR')} and credit total is {format_amount(metrics['credit_total'], 'INR')}."
        )

    @staticmethod
    def _extract_comparison_months(question: str, transactions: list[TransactionRecord]) -> tuple[int | None, int | None, int | None, int | None]:
        lower = question.lower()
        month_map = {
            "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
            "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sep": 9, "october": 10, "oct": 10,
            "november": 11, "nov": 11, "december": 12, "dec": 12
        }
        found = []
        for name, m_val in month_map.items():
            for match in re.finditer(rf"\b{name}\b", lower):
                found.append((match.start(), m_val))
        
        found.sort() # By occurrence in string
        m1 = found[0][1] if len(found) > 0 else None
        m2 = found[1][1] if len(found) > 1 else None
        
        y_matches = re.findall(r"\b(20\d{2})\b", lower)
        y1 = int(y_matches[0]) if len(y_matches) > 0 else None
        y2 = int(y_matches[1]) if len(y_matches) > 1 else y1
        
        if not y1 and transactions:
            years = sorted({tx.date.year for tx in transactions}, reverse=True)
            y1 = y2 = years[0] if years else None
            
        return m1, y1, m2, y2

    @staticmethod
    def _extract_month_scope(question: str, transactions: list[TransactionRecord]) -> tuple[int | None, int | None]:
        lower = question.lower()
        month_map = {
            "january": 1, "jan": 1,
            "february": 2, "feb": 2,
            "march": 3, "mar": 3,
            "april": 4, "apr": 4,
            "may": 5,
            "june": 6, "jun": 6,
            "july": 7, "jul": 7,
            "august": 8, "aug": 8,
            "september": 9, "sep": 9, "sept": 9,
            "october": 10, "oct": 10,
            "november": 11, "nov": 11,
            "december": 12, "dec": 12,
        }
        month = next((value for name, value in month_map.items() if re.search(rf"\b{name}\b", lower)), None)
        year_match = re.search(r"\b(20\d{2})\b", lower)
        if year_match:
            return month, int(year_match.group(1))
        if month is None:
            return None, None
        if not transactions:
            return month, None
        years = sorted({tx.date.year for tx in transactions}, reverse=True)
        return month, years[0]

    @staticmethod
    def _month_name(month: int) -> str:
        names = {
            1: "January", 2: "February", 3: "March", 4: "April", 
            5: "May", 6: "June", 7: "July", 8: "August", 
            9: "September", 10: "October", 11: "November", 12: "December"
        }
        return names.get(month, f"Month {month}")

    @staticmethod
    def _scope_suffix(plan: QueryPlan) -> str:
        if plan.month is None:
            return ""
        month_names = {
            1: "January",
            2: "February",
            3: "March",
            4: "April",
            5: "May",
            6: "June",
            7: "July",
            8: "August",
            9: "September",
            10: "October",
            11: "November",
            12: "December",
        }
        label = month_names.get(plan.month, "")
        if plan.year is not None:
            return f" in {label} {plan.year}"
        return f" in {label}"

    @staticmethod
    def _line_item_summary(filtered: list[TransactionRecord], predicate) -> tuple[float, int, list[tuple[str, float]]]:
        total = 0.0
        matches = 0
        breakdown: dict[str, float] = {}
        for tx in filtered:
            for item in tx.line_items:
                if predicate(item):
                    amount = convert_to_inr(item.price or 0.0, tx.currency)
                    total += amount
                    matches += 1
                    breakdown[item.name] = round(breakdown.get(item.name, 0.0) + amount, 2)
        ordered = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
        return round(total, 2), matches, ordered

    @staticmethod
    def _needs_clarification(plan: QueryPlan, question: str, filtered: list[TransactionRecord]) -> bool:
        lower = question.lower()
        asks_for_total = any(phrase in lower for phrase in ["how much", "total", "sum"])
        explicit_scope = any(
            [
                plan.category,
                plan.counterparty,
                plan.transfer_kind,
                plan.direction != "any",
            ]
        )
        return plan.action == "sum" and asks_for_total and not explicit_scope and bool(filtered)

    @staticmethod
    def _plan_descriptor(plan: QueryPlan) -> str:
        if plan.transfer_kind == "self_transfer":
            return "self transfer"
        if plan.counterparty:
            return f"transaction for {plan.counterparty}"
        if plan.item_name:
            return f"receipt item {plan.item_name}"
        if plan.item_group:
            return f"receipt item group {plan.item_group}"
        if plan.category:
            return plan.category.replace("_", " ")
        if plan.direction == "received":
            return "received"
        if plan.direction == "sent":
            return "debit"
        return "matching"

    @staticmethod
    def _match_counterparty(question: str, transactions: list[TransactionRecord]) -> str | None:
        lower = question.lower()
        merchants = sorted({tx.merchant for tx in transactions if tx.merchant}, key=len, reverse=True)

        # Exact substring match against known merchants is the most reliable path.
        for merchant in merchants:
            if merchant.lower() in lower:
                return merchant

        # Then try extracting a likely target phrase after common prepositions.
        candidate = None
        for pattern in [r"with ([a-z][a-z\s]+)", r"to ([a-z][a-z\s]+)", r"from ([a-z][a-z\s]+)"]:
            match = re.search(pattern, lower)
            if match:
                candidate = match.group(1).strip()
                candidate = re.sub(
                    r"\b(this|whole|entire|month|week|year|all|transactions|transaction|money|amount|did|i|my|the)\b",
                    " ",
                    candidate,
                )
                candidate = " ".join(candidate.split())
                break

        if not candidate or "account" in candidate:
            return None

        best_match = None
        best_score = 0.0
        for merchant in merchants:
            score = SequenceMatcher(None, candidate, merchant.lower()).ratio()
            if candidate in merchant.lower():
                score += 0.25
            if score > best_score:
                best_score = score
                best_match = merchant

        return best_match if best_score >= 0.58 else None

    @staticmethod
    def _match_line_item(question: str, transactions: list[TransactionRecord]) -> str | None:
        lower = question.lower()
        item_names = sorted(
            {
                item.name
                for tx in transactions
                for item in tx.line_items
                if item.name and item.name.lower() not in {"cash", "change"}
            },
            key=len,
            reverse=True,
        )
        for item_name in item_names:
            if item_name.lower() in lower:
                return item_name

        cleaned = re.sub(r"[^a-z\s]", " ", lower)
        for token in cleaned.split():
            if len(token) < 3:
                continue
            best_match = None
            best_score = 0.0
            for item_name in item_names:
                score = SequenceMatcher(None, token, item_name.lower()).ratio()
                if token in item_name.lower():
                    score += 0.25
                if score > best_score:
                    best_match = item_name
                    best_score = score
            if best_match and best_score >= 0.72:
                return best_match
        return None
