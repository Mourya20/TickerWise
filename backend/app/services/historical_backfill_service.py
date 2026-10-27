from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import DailyMarketSnapshot, DataSource, IngestionRun, Instrument
from app.providers.base import NormalizedOHLCV, ProviderError
from app.providers.tejhq import TejHQProvider

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT_FILE = PROJECT_ROOT / "data" / "backfill_checkpoint.json"

TEJHQ_SOURCE_NAME = "TejHQ EOD Market Data"
TEJHQ_SOURCE_TYPE = "api"
TEJHQ_SOURCE_URL = "https://api.tejhq.dev"
TEJHQ_TERMS_URL = "https://tejhq.dev/docs"


@dataclass
class BackfillAudit:
    symbols_requested: int = 0
    symbols_completed: int = 0
    symbols_failed: int = 0
    bars_read: int = 0
    bars_inserted: int = 0
    bars_updated: int = 0
    bars_skipped: int = 0
    bars_failed: int = 0
    failures: list[str] = field(default_factory=list)


class HistoricalBackfillService:
    """Orchestrates controlled, rate-limited, resumable historical OHLCV backfill."""

    def __init__(
        self,
        provider: TejHQProvider | None = None,
        session_factory=SessionLocal,
    ) -> None:
        self.provider = provider or TejHQProvider()
        self.session_factory = session_factory

    @staticmethod
    def validate_bar(bar: NormalizedOHLCV) -> list[str]:
        """Validate price relationships and non-negative constraints."""
        errors = []
        if bar.open is not None and bar.open < 0:
            errors.append("Negative open price")
        if bar.high is not None and bar.high < 0:
            errors.append("Negative high price")
        if bar.low is not None and bar.low < 0:
            errors.append("Negative low price")
        if bar.close is not None and bar.close < 0:
            errors.append("Negative close price")
        if bar.last_price is not None and bar.last_price < 0:
            errors.append("Negative LTP")
        if bar.volume is not None and bar.volume < 0:
            errors.append("Negative volume")
        if bar.turnover is not None and bar.turnover < 0:
            errors.append("Negative turnover")

        # OHLC logic
        if bar.high is not None and bar.low is not None and bar.high < bar.low:
            errors.append(f"High ({bar.high}) < Low ({bar.low})")
        if bar.high is not None and bar.open is not None and bar.high < bar.open:
            errors.append(f"High ({bar.high}) < Open ({bar.open})")
        if bar.high is not None and bar.close is not None and bar.high < bar.close:
            errors.append(f"High ({bar.high}) < Close ({bar.close})")
        if bar.low is not None and bar.open is not None and bar.low > bar.open:
            errors.append(f"Low ({bar.low}) > Open ({bar.open})")
        if bar.low is not None and bar.close is not None and bar.low > bar.close:
            errors.append(f"Low ({bar.low}) > Close ({bar.close})")

        return errors

    def get_or_create_source(self, session: Session) -> DataSource:
        source = session.scalar(select(DataSource).where(DataSource.name == TEJHQ_SOURCE_NAME))
        if source is None:
            source = DataSource(
                name=TEJHQ_SOURCE_NAME,
                source_type=TEJHQ_SOURCE_TYPE,
                source_url=TEJHQ_SOURCE_URL,
                terms_url=TEJHQ_TERMS_URL,
                is_active=True,
            )
            session.add(source)
            session.flush()
        return source

    def load_checkpoint(self) -> dict[str, Any]:
        if CHECKPOINT_FILE.exists():
            try:
                return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def save_checkpoint(self, data: dict[str, Any]) -> None:
        CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def backfill_single_instrument(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        session: Session,
        source_id: int,
        dry_run: bool = False,
    ) -> tuple[int, int, int, int, int, list[str]]:
        """Backfill a single instrument.

        Returns (read, inserted, updated, skipped, failed, errors).
        """
        clean_symbol = symbol.strip().upper()
        inst = session.scalar(
            select(Instrument).where(
                Instrument.symbol == clean_symbol,
                Instrument.exchange == "NSE",
            )
        )
        if inst is None:
            return 0, 0, 0, 0, 1, [f"Symbol {clean_symbol} not found in instrument master."]

        inst_id = int(inst.id)
        try:
            bars = self.provider.get_historical_ohlcv(clean_symbol, from_date, to_date)
        except Exception as exc:
            return 0, 0, 0, 0, 1, [f"Fetch failed for {clean_symbol}: {exc}"]

        # Load existing snapshots in this date range for idempotency
        existing_snapshots = session.scalars(
            select(DailyMarketSnapshot).where(
                DailyMarketSnapshot.instrument_id == inst_id,
                DailyMarketSnapshot.snapshot_date >= from_date,
                DailyMarketSnapshot.snapshot_date <= to_date,
            )
        ).all()
        by_date = {s.snapshot_date: s for s in existing_snapshots}

        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        err_msgs = []

        # Sort bars chronologically
        bars.sort(key=lambda b: b.date)

        for bar in bars:
            validation_errs = self.validate_bar(bar)
            if validation_errs:
                failed += 1
                err_msgs.append(f"{bar.date}: {', '.join(validation_errs)}")
                continue

            # Units conversions
            vol_lakhs = (
                Decimal(bar.volume) / Decimal("100000") if bar.volume is not None else None
            )
            val_crores = (
                Decimal(bar.turnover) / Decimal("10000000") if bar.turnover is not None else None
            )

            pct_change: Decimal | None = None
            is_calc = False
            if bar.close is not None and bar.prev_close is not None and bar.prev_close > 0:
                pct_change = ((bar.close - bar.prev_close) / bar.prev_close) * Decimal("100")
                is_calc = True
            elif bar.last_price is not None and bar.prev_close is not None and bar.prev_close > 0:
                pct_change = ((bar.last_price - bar.prev_close) / bar.prev_close) * Decimal("100")
                is_calc = True

            fields_to_set = {
                "source_id": source_id,
                "open_price": bar.open,
                "high_price": bar.high,
                "low_price": bar.low,
                "close_price": bar.close,
                "last_traded_price": bar.last_price,
                "prev_close_price": bar.prev_close,
                "percentage_change_pct": pct_change,
                "is_calculated_change": is_calc,
                "volume": bar.volume,
                "turnover": bar.turnover,
                "trade_count": bar.trades,
                "volume_lakhs": vol_lakhs,
                "traded_value_crores": val_crores,
            }

            snap = by_date.get(bar.date)
            if snap is None:
                if not dry_run:
                    snap = DailyMarketSnapshot(
                        instrument_id=inst_id,
                        snapshot_date=bar.date,
                        **fields_to_set,
                    )
                    session.add(snap)
                    by_date[bar.date] = snap
                inserted += 1
            else:
                changed = False
                for k, v in fields_to_set.items():
                    cur = getattr(snap, k)
                    if isinstance(v, Decimal) and isinstance(cur, Decimal):
                        if k in ("open_price", "high_price", "low_price", "close_price", "last_traded_price", "prev_close_price", "percentage_change_pct", "volume_lakhs", "traded_value_crores"):
                            v_cmp = v.quantize(Decimal("0.000001"))
                            c_cmp = cur.quantize(Decimal("0.000001"))
                        elif k == "turnover":
                            v_cmp = v.quantize(Decimal("0.0001"))
                            c_cmp = cur.quantize(Decimal("0.0001"))
                        else:
                            v_cmp, c_cmp = v, cur
                        if v_cmp != c_cmp:
                            if not dry_run:
                                setattr(snap, k, v)
                            changed = True
                    elif cur != v:
                        if not dry_run:
                            setattr(snap, k, v)
                        changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1

        if not dry_run:
            session.commit()

        return len(bars), inserted, updated, skipped, failed, err_msgs

    def backfill_instruments(
        self,
        symbols: list[str],
        from_date: date,
        to_date: date,
        resume: bool = True,
        delay_seconds: float = 0.2,
        dry_run: bool = False,
    ) -> BackfillAudit:
        """Controlled batch backfill with rate limiting and checkpointing."""
        if from_date > to_date:
            raise ValueError(f"from_date ({from_date}) must not be after to_date ({to_date})")

        audit = BackfillAudit(symbols_requested=len(symbols))
        checkpoint = self.load_checkpoint() if resume else {}
        cp_from = checkpoint.get("from_date")
        cp_to = checkpoint.get("to_date")

        # Checkpoint is valid only if it matches the requested date range
        if (
            resume
            and cp_from == from_date.isoformat()
            and cp_to == to_date.isoformat()
        ):
            completed_set = set(checkpoint.get("completed_symbols", []))
            empty_set = set(checkpoint.get("empty_history_symbols", []))
        else:
            completed_set = set()
            empty_set = set()

        with self.session_factory() as session:
            source = self.get_or_create_source(session)
            source_id = int(source.id)

            for sym in symbols:
                clean_sym = sym.strip().upper()
                if resume and clean_sym in completed_set:
                    logger.info("Skipping already backfilled symbol: %s (checkpoint)", clean_sym)
                    continue

                logger.info("Backfilling %s from %s to %s...", clean_sym, from_date, to_date)
                read_count, ins, upd, skp, fld, errs = self.backfill_single_instrument(
                    clean_sym, from_date, to_date, session, source_id, dry_run=dry_run
                )

                audit.bars_read += read_count
                audit.bars_inserted += ins
                audit.bars_updated += upd
                audit.bars_skipped += skp
                audit.bars_failed += fld

                if errs:
                    audit.failures.extend(errs)

                if fld > 0 and read_count == 0:
                    audit.symbols_failed += 1
                elif read_count == 0:
                    # Distinguish empty history response from verified populated bars
                    empty_set.add(clean_sym)
                    logger.warning("Symbol %s returned 0 bars between %s and %s", clean_sym, from_date, to_date)
                    audit.failures.append(f"{clean_sym}: 0 historical bars returned")
                else:
                    audit.symbols_completed += 1
                    completed_set.add(clean_sym)
                    if not dry_run:
                        self.save_checkpoint({
                            "from_date": from_date.isoformat(),
                            "to_date": to_date.isoformat(),
                            "completed_symbols": list(completed_set),
                            "empty_history_symbols": list(empty_set),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        })

                # Rate limiting delay
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

        return audit
