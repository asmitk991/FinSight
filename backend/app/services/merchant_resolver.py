from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.config import get_settings
from app.services.category import (
    CATEGORY_MAP,
    MERCHANT_ALIASES,
    merchant_key,
    normalize_category_with_context,
    normalize_merchant_name,
)


@dataclass
class MerchantProfile:
    canonical_name: str
    category: str | None = None
    merchant_type: str = "unknown"
    confidence: float = 0.0
    source: str = "heuristic"
    search_summary: str | None = None


class MerchantResolver:
    def __init__(self) -> None:
        settings = get_settings()
        self.path = settings.merchant_registry_file
        self.base_profiles_path = settings.merchant_profiles_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"profiles": {}}, indent=2), encoding="utf-8")

    def resolve_profile(
        self,
        merchant: str,
        detail_text: str | None = None,
        counterparty_type: str | None = None,
        transfer_kind: str | None = None,
    ) -> MerchantProfile:
        normalized = normalize_merchant_name(merchant)
        key = merchant_key(normalized)
        profiles = self._load_profiles()

        if key in profiles:
            return MerchantProfile(**profiles[key])

        base_profile = self._base_profiles().get(key)
        if base_profile:
            profile = MerchantProfile(**base_profile)
            self._remember(key, profile)
            return profile

        builtin_profile = self._builtin_profile(normalized, detail_text, counterparty_type, transfer_kind)
        if builtin_profile:
            self._remember(key, builtin_profile)
            return builtin_profile

        fuzzy = self._fuzzy_match(key, profiles)
        if fuzzy:
            self._remember(key, fuzzy)
            return fuzzy

        heuristic = self._heuristic_profile(normalized, detail_text, counterparty_type, transfer_kind)
        self._remember(key, heuristic)
        return heuristic

    def resolve(
        self,
        merchant: str,
        detail_text: str | None = None,
        counterparty_type: str | None = None,
        transfer_kind: str | None = None,
    ) -> str:
        return self.resolve_profile(merchant, detail_text, counterparty_type, transfer_kind).canonical_name

    def _builtin_profile(
        self,
        normalized: str,
        detail_text: str | None,
        counterparty_type: str | None,
        transfer_kind: str | None,
    ) -> MerchantProfile | None:
        key = merchant_key(normalized)
        alias_map = {merchant_key(alias_key): alias_value for alias_key, alias_value in MERCHANT_ALIASES.items()}
        if key in alias_map:
            canonical = alias_map[key]
            category = normalize_category_with_context(
                canonical,
                None,
                [],
                transfer_kind,
                counterparty_type,
                detail_text,
            )
            merchant_type = self._infer_merchant_type(canonical, counterparty_type, transfer_kind)
            return MerchantProfile(
                canonical_name=canonical,
                category=category,
                merchant_type=merchant_type,
                confidence=0.95,
                source="builtin",
            )
        return None

    def _heuristic_profile(
        self,
        normalized: str,
        detail_text: str | None,
        counterparty_type: str | None,
        transfer_kind: str | None,
    ) -> MerchantProfile:
        canonical = self._smart_case(normalized, counterparty_type, detail_text)
        category = normalize_category_with_context(canonical, None, [], transfer_kind, counterparty_type, detail_text)
        return MerchantProfile(
            canonical_name=canonical,
            category=category,
            merchant_type=self._infer_merchant_type(canonical, counterparty_type, transfer_kind),
            confidence=0.35,
            source="heuristic",
        )

    def _load_profiles(self) -> dict[str, dict]:
        content = self.path.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return {}
        aliases = payload.pop("aliases", {})
        profiles = payload.setdefault("profiles", {})
        for key, canonical in aliases.items():
            profiles.setdefault(
                key,
                {
                    "canonical_name": canonical,
                    "category": None,
                    "merchant_type": "unknown",
                    "confidence": 0.8,
                    "source": "legacy_alias",
                    "search_summary": None,
                },
            )
        if aliases:
            self.path.write_text(json.dumps({"profiles": profiles}, indent=2), encoding="utf-8")
        return profiles

    def _base_profiles(self) -> dict[str, dict]:
        if not self.base_profiles_path.exists():
            return {}
        payload = json.loads(self.base_profiles_path.read_text(encoding="utf-8"))
        return payload.get("profiles", {})

    def _remember(self, key: str, profile: MerchantProfile) -> None:
        payload = {"profiles": self._load_profiles()}
        current = payload["profiles"].get(key)
        next_profile = {
            "canonical_name": profile.canonical_name,
            "category": profile.category,
            "merchant_type": profile.merchant_type,
            "confidence": profile.confidence,
            "source": profile.source,
            "search_summary": profile.search_summary,
        }
        if current == next_profile:
            return
        payload["profiles"][key] = next_profile
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _fuzzy_match(self, key: str, profiles: dict[str, dict]) -> MerchantProfile | None:
        best_key = None
        best_score = 0.0
        for profile_key, profile in profiles.items():
            score = SequenceMatcher(None, key, profile_key).ratio()
            if key in profile_key or profile_key in key:
                score += 0.15
            if score > best_score:
                best_key = profile_key
                best_score = score
        if best_key and best_score >= 0.92:
            return MerchantProfile(**profiles[best_key])
        return None

    @staticmethod
    def _infer_merchant_type(canonical: str, counterparty_type: str | None, transfer_kind: str | None) -> str:
        if counterparty_type:
            return counterparty_type
        if transfer_kind == "self_transfer":
            return "bank_account"
        key = merchant_key(canonical)
        for needle in CATEGORY_MAP:
            if needle.replace(" ", "") in key:
                return "business"
        if any(token in canonical.lower() for token in ["bank", "upi", "account"]):
            return "bank_account"
        return "unknown"

    @staticmethod
    def _smart_case(normalized: str, counterparty_type: str | None, detail_text: str | None) -> str:
        if not normalized:
            return "Unknown merchant"
        if detail_text and detail_text.lower().startswith("self transfer to "):
            return normalized.title() if normalized.lower() == normalized else normalized
        if counterparty_type == "person":
            return " ".join(token.title() if not token.isupper() else token for token in normalized.split())
        if normalized.isupper() and len(normalized) <= 12:
            return normalized
        if normalized.isupper():
            return normalized.title()
        tokens = normalized.split()
        if tokens and all(token[:1].isupper() for token in tokens):
            return " ".join(tokens)
        return normalized
