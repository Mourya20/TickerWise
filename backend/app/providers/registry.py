"""Market Data Provider Registry and Evaluation Framework.

Maintains formal capability declarations, license terms, observed publication latencies,
data-use permissions, and source-precedence rules across primary, fallback, and candidate providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class ProviderRole(str, Enum):
    PRIMARY_CANONICAL = "primary_canonical"
    SECONDARY_FALLBACK = "secondary_fallback"
    SUPPLEMENTARY_METRICS = "supplementary_metrics"
    OFFLINE_ARCHIVE = "offline_archive"
    QUARANTINED = "quarantined"
    PROHIBITED_SCRAPING = "prohibited_scraping"


class ProviderCapability(str, Enum):
    EOD_SNAPSHOT = "eod_snapshot"
    HISTORICAL_OHLCV = "historical_ohlcv"
    CORPORATE_ACTIONS = "corporate_actions"
    INSTRUMENT_MASTER = "instrument_master"
    FUNDAMENTALS = "fundamentals"


@dataclass(frozen=True)
class ProviderEvaluation:
    """Formal audit and evaluation profile for a market data provider candidate."""

    provider_id: str
    name: str
    role: ProviderRole
    capabilities: frozenset[ProviderCapability]
    observed_publication_latency: str
    typical_publication_time: str
    historical_coverage_years: int
    instrument_coverage_count: int
    supported_series: tuple[str, ...]
    reliability_score: float  # 0.0 to 1.0
    correction_behavior: str
    price_units: str
    volume_units: str
    turnover_units: str
    commercial_cost: str
    license_and_terms: str
    automated_scraping_permitted: bool
    local_storage_permitted: bool
    intended_display_permitted: bool
    notes: str


# Comprehensive evaluations of evaluated provider candidates for Indian Equities
EVALUATED_PROVIDERS: dict[str, ProviderEvaluation] = {
    "tejhq": ProviderEvaluation(
        provider_id="tejhq",
        name="TejHQ EOD Market Data",
        role=ProviderRole.PRIMARY_CANONICAL,
        capabilities=frozenset({
            ProviderCapability.EOD_SNAPSHOT,
            ProviderCapability.HISTORICAL_OHLCV,
            ProviderCapability.CORPORATE_ACTIONS,
        }),
        observed_publication_latency="T+0 4h30m–7h00m (observed ready 20:00–22:30 IST)",
        typical_publication_time="20:30 IST",
        historical_coverage_years=16,
        instrument_coverage_count=2605,
        supported_series=("EQ", "BE", "BZ", "SM", "ST"),
        reliability_score=0.96,
        correction_behavior="Staged derived pipeline: prices stage (~20:00 IST), derived stage (~20:30 IST). Post-close revisions overwrite draft figures.",
        price_units="INR decimal (e.g. 1174.60)",
        volume_units="Raw total traded shares",
        turnover_units="Raw total traded value in INR",
        commercial_cost="Free developer tier / API key auth",
        license_and_terms="TejHQ Developer API Terms (https://tejhq.dev/docs). API access permitted for registered keys.",
        automated_scraping_permitted=True,  # Documented public API with key
        local_storage_permitted=True,
        intended_display_permitted=True,
        notes="Active canonical primary provider. Excellent coverage and deterministic historical OHLCV. Primary operational concern is evening publication delay.",
    ),
    "nse_official_bhavcopy": ProviderEvaluation(
        provider_id="nse_official_bhavcopy",
        name="NSE Official Bhavcopy Archive",
        role=ProviderRole.OFFLINE_ARCHIVE,
        capabilities=frozenset({
            ProviderCapability.EOD_SNAPSHOT,
            ProviderCapability.INSTRUMENT_MASTER,
        }),
        observed_publication_latency="T+0 3h00m–4h00m (published ~18:30–19:30 IST)",
        typical_publication_time="19:00 IST",
        historical_coverage_years=25,
        instrument_coverage_count=2605,
        supported_series=("EQ", "BE", "BZ", "SM", "ST", "GB", "IL"),
        reliability_score=0.99,
        correction_behavior="Authoritative exchange record. Next-day correction files published separately if trades are restated.",
        price_units="INR decimal",
        volume_units="Raw shares traded",
        turnover_units="Raw turnover in INR (or Lakhs depending on file era)",
        commercial_cost="Free on official site (manual); Commercial feed requires NSE Market Data subscription",
        license_and_terms="NSE Website Terms of Use explicitly forbid automated scraping / bot access (enforced by Akamai WAF).",
        automated_scraping_permitted=False,  # PROHIBITED BY TERMS & PROTECTED BY AKAMAI
        local_storage_permitted=True,  # For authorized offline/manual downloads
        intended_display_permitted=True,
        notes="Authoritative primary source. Controlled fallback candidate via authorized offline/downloaded file import, NOT automated scrapers.",
    ),
    "bse_official_bhavcopy": ProviderEvaluation(
        provider_id="bse_official_bhavcopy",
        name="BSE Official Bhavcopy Archive",
        role=ProviderRole.OFFLINE_ARCHIVE,
        capabilities=frozenset({
            ProviderCapability.EOD_SNAPSHOT,
            ProviderCapability.INSTRUMENT_MASTER,
        }),
        observed_publication_latency="T+0 2h30m–3h30m (published ~18:00–19:00 IST)",
        typical_publication_time="18:30 IST",
        historical_coverage_years=30,
        instrument_coverage_count=4500,
        supported_series=("A", "B", "T", "X", "XT"),
        reliability_score=0.98,
        correction_behavior="Authoritative exchange record for BSE listings.",
        price_units="INR decimal",
        volume_units="Raw shares traded",
        turnover_units="Raw turnover in INR",
        commercial_cost="Free on official site (manual download)",
        license_and_terms="BSE Terms of Use. Automated mass harvesting restricted.",
        automated_scraping_permitted=False,
        local_storage_permitted=True,
        intended_display_permitted=True,
        notes="Authoritative secondary exchange. Useful for cross-validating dual-listed securities.",
    ),
    "zero_x_ramm": ProviderEvaluation(
        provider_id="zero_x_ramm",
        name="0xramm Indian Stock Market API",
        role=ProviderRole.SUPPLEMENTARY_METRICS,
        capabilities=frozenset({
            ProviderCapability.EOD_SNAPSHOT,
            ProviderCapability.FUNDAMENTALS,
        }),
        observed_publication_latency="T+0 1h00m–2h00m (quotes ready ~16:30–17:30 IST)",
        typical_publication_time="17:00 IST",
        historical_coverage_years=0,  # Snapshot only, no deep historical backfill
        instrument_coverage_count=2100,
        supported_series=("EQ",),
        reliability_score=0.75,
        correction_behavior="No published correction or audit trail.",
        price_units="INR decimal",
        volume_units="Raw share count",
        turnover_units="Unreported",
        commercial_cost="Free open-source proxy",
        license_and_terms="MIT repository license; upstream data origins unverified.",
        automated_scraping_permitted=False,
        local_storage_permitted=False,
        intended_display_permitted=False,
        notes="Gated by default (TICKERWISE_0XRAMM_ENABLED=false). Fails closed until upstream redistribution rights are certified.",
    ),
    "yahoo_finance": ProviderEvaluation(
        provider_id="yahoo_finance",
        name="Yahoo Finance (yfinance)",
        role=ProviderRole.QUARANTINED,
        capabilities=frozenset({
            ProviderCapability.HISTORICAL_OHLCV,
        }),
        observed_publication_latency="T+0 3h00m–5h00m (delayed ~18:30–20:30 IST)",
        typical_publication_time="19:30 IST",
        historical_coverage_years=20,
        instrument_coverage_count=1800,
        supported_series=("EQ",),
        reliability_score=0.70,
        correction_behavior="Unannounced splits/bonus retroactive restatements that can break raw price integrity without notice.",
        price_units="INR decimal",
        volume_units="Raw volume (frequently discrepancies with official NSE trade books)",
        turnover_units="Unreported",
        commercial_cost="Free personal use only; commercial use strictly requires paid Yahoo API contract",
        license_and_terms="Yahoo Developer API Terms of Service. Prohibits redistribution, storage, and commercial product integration.",
        automated_scraping_permitted=False,
        local_storage_permitted=False,
        intended_display_permitted=False,
        notes="Quarantined. Discarded as production candidate due to legal restrictions, missing ISIN/series metadata, and unannounced split smoothing.",
    ),
    "eodhd_commercial": ProviderEvaluation(
        provider_id="eodhd_commercial",
        name="EODHD / Twelve Data Commercial APIs",
        role=ProviderRole.SECONDARY_FALLBACK,
        capabilities=frozenset({
            ProviderCapability.EOD_SNAPSHOT,
            ProviderCapability.HISTORICAL_OHLCV,
            ProviderCapability.CORPORATE_ACTIONS,
        }),
        observed_publication_latency="T+0 4h00m–6h00m (~19:30–21:30 IST)",
        typical_publication_time="20:00 IST",
        historical_coverage_years=15,
        instrument_coverage_count=2200,
        supported_series=("EQ", "BE"),
        reliability_score=0.92,
        correction_behavior="Commercial SLA with restatement notices.",
        price_units="INR decimal",
        volume_units="Raw share count",
        turnover_units="Raw turnover in INR",
        commercial_cost="Paid commercial subscription ($30–$100/mo)",
        license_and_terms="Commercial market data vendor terms. Local caching and application display permitted under paid tiers.",
        automated_scraping_permitted=True,
        local_storage_permitted=True,
        intended_display_permitted=True,
        notes="Viable future paid fallback candidate. Requires budget approval before production integration.",
    ),
}


class ProviderRegistry:
    """Central lookup and governance for market data provider capabilities."""

    @classmethod
    def get_provider(cls, provider_id: str) -> ProviderEvaluation | None:
        return EVALUATED_PROVIDERS.get(provider_id.lower().strip())

    @classmethod
    def get_all_providers(cls) -> list[ProviderEvaluation]:
        return list(EVALUATED_PROVIDERS.values())

    @classmethod
    def get_providers_for_capability(
        cls, capability: ProviderCapability
    ) -> list[ProviderEvaluation]:
        return [
            p for p in EVALUATED_PROVIDERS.values()
            if capability in p.capabilities
        ]

    @classmethod
    def get_active_primary(cls) -> ProviderEvaluation:
        for p in EVALUATED_PROVIDERS.values():
            if p.role == ProviderRole.PRIMARY_CANONICAL:
                return p
        raise RuntimeError("No primary canonical provider registered.")

    @classmethod
    def verify_permissions(cls, provider_id: str) -> dict[str, bool]:
        """Check if provider is legally authorized for automated retrieval, caching and display."""
        p = cls.get_provider(provider_id)
        if not p:
            return {
                "exists": False,
                "automated_scraping_permitted": False,
                "local_storage_permitted": False,
                "intended_display_permitted": False,
            }
        return {
            "exists": True,
            "automated_scraping_permitted": p.automated_scraping_permitted,
            "local_storage_permitted": p.local_storage_permitted,
            "intended_display_permitted": p.intended_display_permitted,
        }
