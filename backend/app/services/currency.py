from __future__ import annotations

from app.config import get_settings


def conversion_rate_to_inr(currency: str | None) -> float:
    settings = get_settings()
    code = (currency or "INR").upper()
    rates = {
        "INR": 1.0,
        "USD": settings.usd_to_inr,
        "AED": settings.aed_to_inr,
        "EUR": settings.eur_to_inr,
        "GBP": settings.gbp_to_inr,
    }
    return rates.get(code, 1.0)


def convert_to_inr(amount: float, currency: str | None) -> float:
    return round(amount * conversion_rate_to_inr(currency), 2)
