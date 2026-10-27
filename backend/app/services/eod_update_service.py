from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    Company,
    CompanyMetric,
    DailyMarketSnapshot,
    DataSource,
    IngestionRun,
    Instrument,
    InstrumentShareCount,
)
from app.providers.base import (
    NormalizedCompanyMetric,
    NormalizedMarketSnapshot,
    NormalizedQuote,
    ProviderError,
    ProviderStatus,
)
from app.providers.tejhq import TejHQProvider
from app.providers.zero_x_ramm import ZeroXRammProvider

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REVIEW_DIR = PROJECT_ROOT / "data" / "rejected"

TEJHQ_SOURCE_NAME = "TejHQ EOD Market Data"
TEJHQ_SOURCE_TYPE = "api"
TEJHQ_SOURCE_URL = "https://api.tejhq.dev"
TEJHQ_TERMS_URL = "https://tejhq.dev/docs"

ZEROM_SOURCE_NAME = "0xramm Indian Stock Market API"
ZEROM_SOURCE_TYPE = "api"
ZEROM_SOURCE_URL = "https://github.com/0xramm/Indian-Stock-Market-API"
ZEROM_TERMS_URL = "https://github.com/0xramm/Indian-Stock-Market-API/blob/main/LICENSE"


def utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class EODUpdateResult:
    status: str  # "completed", "partial", "skipped", "failed"
    trading_date: date | None
    run_id: int | None
    records_read: int
    records_inserted: int
    records_updated: int
    records_skipped: int
    records_failed: int
    records_unmatched: int
    review_path: Path | None
    message: str


@dataclass(frozen=True)
class ReconciledQuote:
    """Canonical reconciled market data record combining canonical EOD and supplementary fields."""

    symbol: str
    snapshot_date: date
    # Canonical prices (TejHQ)
    last_price: Decimal | None
    close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    prev_close: Decimal | None
    volume: int | None
    turnover: Decimal | None
    trades: int | None
    # Supplementary fundamental metrics (0xramm)
    market_cap: Decimal | None = None
    pe_ratio: Decimal | None = None
    dividend_yield: Decimal | None = None
    sector: str | None = None
    # Audit & provenance
    provenance: dict[str, str] = field(default_factory=dict)
    discrepancies: list[str] = field(default_factory=list)


class EODUpdateService:
    """Orchestrates end-of-day market data ingestion from TejHQ and supplementary metrics."""

    DEFAULT_MIN_COVERAGE_THRESHOLD = 1500

    def __init__(
        self,
        tejhq_provider: TejHQProvider | None = None,
        zero_x_ramm_provider: ZeroXRammProvider | None = None,
        session_factory=SessionLocal,
    ) -> None:
        self.tejhq = tejhq_provider or TejHQProvider()
        self.zero_x_ramm = zero_x_ramm_provider or ZeroXRammProvider()
        self.session_factory = session_factory

    def get_or_create_source(
        self,
        session: Session,
        name: str,
        source_type: str,
        source_url: str | None,
        terms_url: str | None,
        is_active: bool = True,
    ) -> DataSource:
        source = session.scalar(select(DataSource).where(DataSource.name == name))
        if source is None:
            source = DataSource(
                name=name,
                source_type=source_type,
                source_url=source_url,
                terms_url=terms_url,
                is_active=is_active,
            )
            session.add(source)
            session.flush()
        else:
            if source.source_type != source_type:
                source.source_type = source_type
            if source_url and source.source_url != source_url:
                source.source_url = source_url
            if terms_url and source.terms_url != terms_url:
                source.terms_url = terms_url
            session.flush()
        return source

    @staticmethod
    def resolve_instrument(
        symbol: str,
        series: str | None,
        isin: str | None,
        exact_instruments: dict[tuple[str, str, str], Instrument],
        isin_instruments: dict[str, list[Instrument]],
        symbol_instruments: dict[tuple[str, str], list[Instrument]],
    ) -> tuple[Instrument | None, str | None]:
        """Match provider record to existing instrument using symbol, series and ISIN."""
        exchange = "NSE"
        clean_symbol = symbol.strip().upper()
        clean_series = series.strip().upper() if series else None
        clean_isin = isin.strip().upper() if isin else None

        # 1. Exact match on (exchange, symbol, series)
        if clean_series:
            instrument = exact_instruments.get((exchange, clean_symbol, clean_series))
            if instrument is not None:
                return instrument, None

        # 2. Match by ISIN if available
        if clean_isin:
            candidates = isin_instruments.get(clean_isin, [])
            if len(candidates) == 1:
                return candidates[0], None
            elif len(candidates) > 1:
                # Disambiguate with symbol
                matching_sym = [c for c in candidates if c.symbol.upper() == clean_symbol]
                if len(matching_sym) == 1:
                    return matching_sym[0], None

        # 3. Match by symbol alone if only 1 instrument exists under that symbol
        candidates = symbol_instruments.get((exchange, clean_symbol), [])
        if len(candidates) == 1:
            return candidates[0], None
        elif len(candidates) > 1:
            series_list = [c.series for c in candidates]
            return (
                None,
                f"Ambiguous instrument: symbol {clean_symbol} has {len(candidates)} candidates with series {series_list}, provider series was '{clean_series}'",
            )

        if clean_isin and clean_isin.startswith("INF"):
            return None, f"Non-equity fund/ETF instrument: ISIN '{clean_isin}' (not in equity master)"

        return None, f"No instrument found matching symbol '{clean_symbol}' (series='{clean_series}', isin='{clean_isin}')"

    @staticmethod
    def classify_review_category(
        isin: str | None,
        error_message: str | None,
    ) -> str:
        """Classify an unmatched record into a distinct review category."""
        if error_message and "Ambiguous" in error_message:
            return "ambiguous"
        clean_isin = isin.strip().upper() if isin else None
        if (clean_isin and clean_isin.startswith("INF")) or (error_message and "Non-equity" in error_message):
            return "unmatched_non_equity_fund"
        return "unmatched_equity"

    @staticmethod
    def reconcile_quote(
        primary_snapshot: NormalizedMarketSnapshot,
        supplementary_quote: NormalizedQuote | None = None,
        divergence_threshold: Decimal = Decimal("0.05"),
    ) -> ReconciledQuote:
        """Reconcile primary canonical EOD market prices with optional supplementary metrics.

        Enforces Phase E source priority rules:
        1. TejHQ is canonical for daily market prices (LTP, OHLCV, close, prev_close).
        2. Supplementary provider NEVER overwrites canonical price fields.
        3. Conflicting prices are NEVER averaged.
        4. If as-of dates differ, reject supplementary metrics to avoid date mixing.
        5. If supplementary provides a price on the same date, flag material divergence (>5%).
        6. Supplementary fundamental metrics (market_cap, pe_ratio, dividend_yield, sector)
           are attached only when as_of_date is synchronized.
        7. Explicit provenance is recorded for every field.
        """
        provenance: dict[str, str] = {
            "last_price": primary_snapshot.provider_name,
            "close": primary_snapshot.provider_name,
            "open": primary_snapshot.provider_name,
            "high": primary_snapshot.provider_name,
            "low": primary_snapshot.provider_name,
            "prev_close": primary_snapshot.provider_name,
            "volume": primary_snapshot.provider_name,
            "turnover": primary_snapshot.provider_name,
            "trades": primary_snapshot.provider_name,
        }
        discrepancies: list[str] = []

        market_cap = None
        pe_ratio = None
        dividend_yield = None
        sector = None

        if supplementary_quote is not None:
            # 1. As-of date check: Do not mix metrics from differing dates
            if supplementary_quote.as_of_date != primary_snapshot.snapshot_date:
                discrepancies.append(
                    f"Date mismatch: canonical snapshot date is {primary_snapshot.snapshot_date} but "
                    f"supplementary quote date is {supplementary_quote.as_of_date}. "
                    "Supplementary metrics rejected to prevent date mixing."
                )
                logger.warning(
                    "Symbol %s: rejected supplementary quote due to date mismatch (%s vs %s)",
                    primary_snapshot.symbol,
                    primary_snapshot.snapshot_date,
                    supplementary_quote.as_of_date,
                )
            else:
                # 2. Material price divergence check (if supplementary supplies a price)
                sup_price = supplementary_quote.price
                pri_price = primary_snapshot.close or primary_snapshot.last_price
                if sup_price is not None and pri_price is not None and pri_price > 0:
                    diff_pct = abs(sup_price - pri_price) / pri_price
                    if diff_pct > divergence_threshold:
                        msg = (
                            f"Material price divergence ({diff_pct * 100:.2f}%): "
                            f"canonical {primary_snapshot.provider_name} price={pri_price} vs "
                            f"supplementary {supplementary_quote.provider_name} price={sup_price}. "
                            f"Canonical price retained (divergence > {divergence_threshold * 100:.0f}%)."
                        )
                        discrepancies.append(msg)
                        logger.warning("Symbol %s: %s", primary_snapshot.symbol, msg)

                # 3. Attach supplementary fundamental metrics
                if supplementary_quote.market_cap is not None:
                    market_cap = supplementary_quote.market_cap
                    provenance["market_cap"] = supplementary_quote.provider_name
                if supplementary_quote.pe_ratio is not None:
                    pe_ratio = supplementary_quote.pe_ratio
                    provenance["pe_ratio"] = supplementary_quote.provider_name
                if supplementary_quote.dividend_yield is not None:
                    dividend_yield = supplementary_quote.dividend_yield
                    provenance["dividend_yield"] = supplementary_quote.provider_name
                if supplementary_quote.sector is not None:
                    sector = supplementary_quote.sector
                    provenance["sector"] = supplementary_quote.provider_name

        return ReconciledQuote(
            symbol=primary_snapshot.symbol,
            snapshot_date=primary_snapshot.snapshot_date,
            last_price=primary_snapshot.last_price,
            close=primary_snapshot.close,
            open=primary_snapshot.open,
            high=primary_snapshot.high,
            low=primary_snapshot.low,
            prev_close=primary_snapshot.prev_close,
            volume=primary_snapshot.volume,
            turnover=primary_snapshot.turnover,
            trades=primary_snapshot.trades,
            market_cap=market_cap,
            pe_ratio=pe_ratio,
            dividend_yield=dividend_yield,
            sector=sector,
            provenance=provenance,
            discrepancies=discrepancies,
        )

    def write_review_rows(
        self,
        review_rows: list[tuple[dict[str, Any], str, str]],
    ) -> Path | None:
        if not review_rows:
            return None

        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        review_path = REVIEW_DIR / f"eod_snapshot_review_{stamp}.csv"

        fieldnames = [
            "SYMBOL",
            "SERIES",
            "ISIN",
            "NAME",
            "OPEN",
            "HIGH",
            "LOW",
            "CLOSE",
            "LAST",
            "PREV_CLOSE",
            "VOLUME",
            "TURNOVER",
            "TRADES",
            "REVIEW_CATEGORY",
            "REVIEW_REASON",
        ]

        with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for raw_row, category, reason in review_rows:
                output = {
                    "SYMBOL": raw_row.get("symbol", ""),
                    "SERIES": raw_row.get("series", ""),
                    "ISIN": raw_row.get("isin", ""),
                    "NAME": raw_row.get("name", ""),
                    "OPEN": raw_row.get("open", ""),
                    "HIGH": raw_row.get("high", ""),
                    "LOW": raw_row.get("low", ""),
                    "CLOSE": raw_row.get("close", ""),
                    "LAST": raw_row.get("last", ""),
                    "PREV_CLOSE": raw_row.get("prev_close", ""),
                    "VOLUME": raw_row.get("volume", ""),
                    "TURNOVER": raw_row.get("turnover", ""),
                    "TRADES": raw_row.get("trades", ""),
                    "REVIEW_CATEGORY": category,
                    "REVIEW_REASON": reason,
                }
                writer.writerow(output)

        return review_path

    def run_update(
        self,
        target_date: date | None = None,
        force: bool = False,
        dry_run: bool = False,
        min_coverage_threshold: int = 0,
    ) -> EODUpdateResult:
        """Execute the end-of-day market data ingestion workflow."""
        # 1. Determine trading date from provider if not provided
        provider_status: ProviderStatus | None = None
        if target_date is None:
            try:
                provider_status = self.tejhq.get_status()
                if provider_status.trading_date is None:
                    return EODUpdateResult(
                        status="skipped",
                        trading_date=None,
                        run_id=None,
                        records_read=0,
                        records_inserted=0,
                        records_updated=0,
                        records_skipped=0,
                        records_failed=0,
                        records_unmatched=0,
                        review_path=None,
                        message="TejHQ status reports no trading date published yet.",
                    )
                target_date = provider_status.trading_date
                logger.info("Determined latest published trading date from TejHQ: %s", target_date)
            except ProviderError as exc:
                logger.error("Failed to query TejHQ status: %s", exc)
                return EODUpdateResult(
                    status="failed",
                    trading_date=None,
                    run_id=None,
                    records_read=0,
                    records_inserted=0,
                    records_updated=0,
                    records_skipped=0,
                    records_failed=0,
                    records_unmatched=0,
                    review_path=None,
                    message=f"Failed to check provider status: {exc}",
                )

        # 2. Check if already ingested (unless forced)
        with self.session_factory() as session:
            source = self.get_or_create_source(
                session,
                name=TEJHQ_SOURCE_NAME,
                source_type=TEJHQ_SOURCE_TYPE,
                source_url=TEJHQ_SOURCE_URL,
                terms_url=TEJHQ_TERMS_URL,
                is_active=True,
            )
            # Also register 0xramm source as inactive (unauthorized by default)
            self.get_or_create_source(
                session,
                name=ZEROM_SOURCE_NAME,
                source_type=ZEROM_SOURCE_TYPE,
                source_url=ZEROM_SOURCE_URL,
                terms_url=ZEROM_TERMS_URL,
                is_active=False,
            )
            source_id = int(source.id)
            session.commit()

            if not force:
                existing_run = session.scalar(
                    select(IngestionRun).where(
                        IngestionRun.source_id == source_id,
                        IngestionRun.trading_date == target_date,
                        IngestionRun.status == "completed",
                    )
                )
                if existing_run is not None:
                    logger.info(
                        "Trading date %s was already ingested in run %d with status %s. Skipping (up to date).",
                        target_date,
                        existing_run.id,
                        existing_run.status,
                    )
                    return EODUpdateResult(
                        status="skipped",
                        trading_date=target_date,
                        run_id=int(existing_run.id),
                        records_read=existing_run.records_read,
                        records_inserted=existing_run.records_inserted,
                        records_updated=existing_run.records_updated,
                        records_skipped=existing_run.records_skipped,
                        records_failed=existing_run.records_failed,
                        records_unmatched=existing_run.records_unmatched,
                        review_path=None,
                        message=f"Trading date {target_date} has already been ingested (Run ID {existing_run.id}). Use --force to re-process.",
                    )

        # 3. Create IngestionRun
        dataset_name = f"tejhq_eod_snapshot_{target_date.isoformat()}"
        run_id: int | None = None
        if not dry_run:
            with self.session_factory() as session:
                run = IngestionRun(
                    source_id=source_id,
                    dataset_name=dataset_name,
                    trading_date=target_date,
                    source_status=provider_status.stage if provider_status else "active",
                    status="running",
                    records_read=0,
                    records_inserted=0,
                    records_updated=0,
                    records_skipped=0,
                    records_failed=0,
                    records_unmatched=0,
                )
                session.add(run)
                session.commit()
                run_id = int(run.id)

        # 4. Fetch snapshot from TejHQ
        try:
            logger.info("Fetching full NSE snapshot for %s from TejHQ...", target_date)
            normalized_rows = self.tejhq.get_daily_snapshot(target_date, exchange="NSE")
            logger.info("Received %d normalized rows from TejHQ for %s", len(normalized_rows), target_date)
        except Exception as exc:
            logger.error("TejHQ snapshot fetch failed for %s: %s", target_date, exc)
            if run_id is not None:
                with self.session_factory() as session:
                    failed_run = session.get(IngestionRun, run_id)
                    if failed_run:
                        failed_run.status = "failed"
                        failed_run.completed_at = utc_naive_now()
                        failed_run.error_summary = f"Provider fetch error: {exc}"
                        session.commit()
            return EODUpdateResult(
                status="failed",
                trading_date=target_date,
                run_id=run_id,
                records_read=0,
                records_inserted=0,
                records_updated=0,
                records_skipped=0,
                records_failed=1,
                records_unmatched=0,
                review_path=None,
                message=f"TejHQ snapshot fetch failed: {exc}",
            )

        # 5. Process rows against database
        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        unmatched = 0
        review_rows: list[tuple[dict[str, Any], str, str]] = []

        try:
            with self.session_factory() as session:
                # Load instrument lookups
                instruments = session.scalars(select(Instrument)).all()
                exact_instruments: dict[tuple[str, str, str], Instrument] = {}
                isin_instruments: dict[str, list[Instrument]] = {}
                symbol_instruments: dict[tuple[str, str], list[Instrument]] = {}

                for inst in instruments:
                    exch = inst.exchange.strip().upper()
                    sym = inst.symbol.strip().upper()
                    ser = inst.series.strip().upper()
                    exact_instruments[(exch, sym, ser)] = inst
                    symbol_instruments.setdefault((exch, sym), []).append(inst)
                    if inst.isin:
                        isin_instruments.setdefault(inst.isin.strip().upper(), []).append(inst)

                # Load existing snapshots for this date to support idempotent updates
                existing_snapshots = session.scalars(
                    select(DailyMarketSnapshot).where(
                        DailyMarketSnapshot.snapshot_date == target_date
                    )
                ).all()
                snapshots_by_instrument_id = {
                    int(s.instrument_id): s for s in existing_snapshots
                }

                # Load active share counts for calculating market capitalization
                # Point-in-time: strictly require reporting_date <= target_date
                share_counts = session.scalars(
                    select(InstrumentShareCount).where(
                        InstrumentShareCount.share_class == "EQUITY",
                        InstrumentShareCount.is_active == True,
                        InstrumentShareCount.reporting_date <= target_date,
                    ).order_by(InstrumentShareCount.reporting_date.desc(), InstrumentShareCount.id.desc())
                ).all()
                share_counts_by_inst_id: dict[int, int] = {}
                for sc in share_counts:
                    inst_key = int(sc.instrument_id)
                    if inst_key not in share_counts_by_inst_id and sc.reported_share_count:
                        share_counts_by_inst_id[inst_key] = sc.reported_share_count

                for row in normalized_rows:
                    raw_dict = {
                        "symbol": row.symbol,
                        "series": row.series,
                        "isin": row.isin,
                        "name": row.name,
                        "open": row.open,
                        "high": row.high,
                        "low": row.low,
                        "close": row.close,
                        "last": row.last_price,
                        "prev_close": row.prev_close,
                        "volume": row.volume,
                        "turnover": row.turnover,
                        "trades": row.trades,
                    }

                    # Match instrument
                    instrument, match_error = self.resolve_instrument(
                        row.symbol,
                        row.series,
                        row.isin,
                        exact_instruments,
                        isin_instruments,
                        symbol_instruments,
                    )
                    if instrument is None:
                        unmatched += 1
                        category = self.classify_review_category(row.isin, match_error)
                        review_rows.append((raw_dict, category, match_error or "No matching instrument."))
                        continue

                    # Validate critical fields
                    if row.last_price is None and row.close is None:
                        failed += 1
                        review_rows.append(
                            (raw_dict, "failed", "Both last_traded_price (LTP) and close are missing/null.")
                        )
                        continue

                    # Units conversions for existing columns:
                    # volume_lakhs = volume / 100,000
                    # traded_value_crores = turnover / 10,000,000
                    volume_lakhs: Decimal | None = None
                    if row.volume is not None:
                        volume_lakhs = Decimal(row.volume) / Decimal("100000")

                    traded_value_crores: Decimal | None = None
                    if row.turnover is not None:
                        traded_value_crores = Decimal(row.turnover) / Decimal("10000000")

                    inst_id = int(instrument.id)

                    # Calculate dated, defensible market capitalization:
                    # Market Capitalization in ₹ Crores = (LTP × Applicable Outstanding Shares) / 10,000,000
                    market_cap_crores: Decimal | None = None
                    price_for_mcap = row.last_price if row.last_price is not None else row.close
                    if price_for_mcap is not None and inst_id in share_counts_by_inst_id:
                        shares = share_counts_by_inst_id[inst_id]
                        market_cap_crores = (
                            (price_for_mcap * Decimal(shares)) / Decimal("10000000")
                        ).quantize(Decimal("0.000001"))

                    fields_to_set = {
                        "source_id": source_id,
                        "open_price": row.open,
                        "high_price": row.high,
                        "low_price": row.low,
                        "close_price": row.close,
                        "last_traded_price": row.last_price,
                        "prev_close_price": row.prev_close,
                        "percentage_change_pct": row.percentage_change_pct,
                        "is_calculated_change": row.is_calculated_change,
                        "volume": row.volume,
                        "turnover": row.turnover,
                        "trade_count": row.trades,
                        "volume_lakhs": volume_lakhs,
                        "traded_value_crores": traded_value_crores,
                        "market_capitalization_crores": market_cap_crores,
                    }

                    snapshot = snapshots_by_instrument_id.get(inst_id)

                    if snapshot is None:
                        if not dry_run:
                            snapshot = DailyMarketSnapshot(
                                instrument_id=inst_id,
                                snapshot_date=target_date,
                                **fields_to_set,
                            )
                            session.add(snapshot)
                            snapshots_by_instrument_id[inst_id] = snapshot
                        inserted += 1
                    else:
                        # Check if any field changed
                        changed = False
                        for attr, val in fields_to_set.items():
                            cur = getattr(snapshot, attr)
                            # Normalize Decimals to column scale to avoid precision mismatch
                            if isinstance(val, Decimal) and isinstance(cur, Decimal):
                                if attr in ("open_price", "high_price", "low_price", "close_price", "last_traded_price", "prev_close_price", "percentage_change_pct", "volume_lakhs", "traded_value_crores", "market_capitalization_crores"):
                                    val_cmp = val.quantize(Decimal("0.000001"))
                                    cur_cmp = cur.quantize(Decimal("0.000001"))
                                elif attr == "turnover":
                                    val_cmp = val.quantize(Decimal("0.0001"))
                                    cur_cmp = cur.quantize(Decimal("0.0001"))
                                else:
                                    val_cmp, cur_cmp = val, cur
                                if cur_cmp != val_cmp:
                                    if not dry_run:
                                        setattr(snapshot, attr, val)
                                    changed = True
                            elif cur != val:
                                if not dry_run:
                                    setattr(snapshot, attr, val)
                                changed = True
                        if changed:
                            updated += 1
                        else:
                            skipped += 1


                review_path = self.write_review_rows(review_rows)

                matched_count = inserted + updated + skipped
                coverage_failed = bool(min_coverage_threshold > 0 and matched_count < min_coverage_threshold)

                if not dry_run and run_id is not None:
                    run_record = session.get(IngestionRun, run_id)
                    if run_record:
                        run_record.records_read = len(normalized_rows)
                        run_record.records_inserted = inserted
                        run_record.records_updated = updated
                        run_record.records_skipped = skipped
                        run_record.records_failed = failed
                        run_record.records_unmatched = unmatched
                        run_record.completed_at = utc_naive_now()
                        if coverage_failed:
                            run_record.status = "failed"
                            run_record.error_summary = (
                                f"Mandatory coverage check failed: only {matched_count} instruments covered "
                                f"(minimum required: {min_coverage_threshold})."
                            )
                        else:
                            run_record.status = "partial" if (failed > 0 or unmatched > 0) else "completed"
                            if review_path is not None:
                                run_record.error_summary = (
                                    f"{failed} failed and {unmatched} unmatched rows. Review: {review_path.name}"
                                )
                        session.commit()
                elif dry_run:
                    session.rollback()

            if coverage_failed:
                final_status = "failed"
                msg = (
                    f"Mandatory coverage check failed: only {matched_count} instruments covered "
                    f"(minimum required: {min_coverage_threshold}). Run marked as failed."
                )
            else:
                final_status = "partial" if (failed > 0 or unmatched > 0) else "completed"
                msg = (
                    f"EOD update for {target_date} finished: {inserted} inserted, "
                    f"{updated} updated, {skipped} unchanged, {failed} failed, {unmatched} unmatched."
                )
            if dry_run:
                msg = "[DRY RUN] " + msg

            return EODUpdateResult(
                status=final_status,
                trading_date=target_date,
                run_id=run_id,
                records_read=len(normalized_rows),
                records_inserted=inserted,
                records_updated=updated,
                records_skipped=skipped,
                records_failed=failed,
                records_unmatched=unmatched,
                review_path=review_path,
                message=msg,
            )

        except Exception as exc:
            logger.exception("Database error while committing EOD update for %s: %s", target_date, exc)
            if not dry_run and run_id is not None:
                with self.session_factory() as error_session:
                    run_record = error_session.get(IngestionRun, run_id)
                    if run_record:
                        run_record.status = "failed"
                        run_record.completed_at = utc_naive_now()
                        run_record.error_summary = f"Fatal DB error: {exc}"
                        error_session.commit()
            return EODUpdateResult(
                status="failed",
                trading_date=target_date,
                run_id=run_id,
                records_read=len(normalized_rows),
                records_inserted=inserted,
                records_updated=updated,
                records_skipped=skipped,
                records_failed=failed + 1,
                records_unmatched=unmatched,
                review_path=None,
                message=f"Fatal error during database ingestion: {exc}",
            )

    def run_catchup(
        self,
        max_catchup_days: int = 15,
        dry_run: bool = False,
        min_coverage_threshold: int = 0,
    ) -> list[EODUpdateResult]:
        """Catch up missing EOD trading dates sequentially between latest local and remote."""
        provider_status = self.tejhq.get_status()
        latest_remote = provider_status.trading_date
        if latest_remote is None:
            logger.info("Provider has not published any trading date yet.")
            return []

        # Find completed trading dates to allow recovering partial/incomplete runs
        with self.session_factory() as session:
            completed_runs = session.scalars(
                select(IngestionRun.trading_date).where(
                    IngestionRun.status == "completed",
                    IngestionRun.trading_date.is_not(None),
                )
            ).all()
            completed_dates = set(completed_runs)

            last_run = session.scalar(
                select(IngestionRun)
                .where(
                    IngestionRun.status == "completed",
                    IngestionRun.trading_date.is_not(None),
                )
                .order_by(IngestionRun.trading_date.desc())
                .limit(1)
            )
            latest_local = last_run.trading_date if last_run else None

        if latest_local is None:
            logger.info("No completed local runs found, running update for latest remote date: %s", latest_remote)
            return [self.run_update(target_date=latest_remote, dry_run=dry_run, min_coverage_threshold=min_coverage_threshold)]

        if latest_local >= latest_remote and all(d in completed_dates for d in [latest_local]):
            logger.info(
                "Local database is already up to date with provider (local: %s, remote: %s).",
                latest_local,
                latest_remote,
            )
            return []

        results = []
        cur_date = latest_local + timedelta(days=1)
        count = 0
        while cur_date <= latest_remote and count < max_catchup_days:
            # Skip weekends (Saturday=5, Sunday=6)
            if cur_date.weekday() < 5 and cur_date not in completed_dates:
                logger.info("Catching up missing or incomplete trading date: %s", cur_date)
                res = self.run_update(
                    target_date=cur_date,
                    force=True,
                    dry_run=dry_run,
                    min_coverage_threshold=min_coverage_threshold,
                )
                results.append(res)
                count += 1
            cur_date += timedelta(days=1)

        return results

