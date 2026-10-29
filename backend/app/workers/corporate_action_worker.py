"""Automated Corporate Actions Ingestion Worker.

Runs scheduled or on-demand corporate actions synchronization from market data providers
without tying execution to HTTP request/response lifecycles.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from app.corporate_actions.service import (
    DEFAULT_SOURCE_NAME,
    CorporateActionIngestionResult,
    CorporateActionService,
)
from app.db.session import SessionLocal
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.instrument import Instrument
from app.providers.tejhq import TejHQProvider

logger = logging.getLogger("app.workers.corporate_actions")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT_FILE = PROJECT_ROOT / "data" / "corporate_actions_checkpoint.json"


def load_checkpoint(checkpoint_path: Path = CHECKPOINT_FILE) -> dict[str, Any]:
    if checkpoint_path.exists():
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to read checkpoint file, starting fresh: %s", exc)
    return {
        "completed_symbols": [],
        "empty_symbols": [],
        "failed_symbols": {},
        "updated_at": None,
    }


def save_checkpoint(checkpoint_data: dict[str, Any], checkpoint_path: Path = CHECKPOINT_FILE) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        temp_file = checkpoint_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)
        temp_file.replace(checkpoint_path)
    except Exception as exc:
        logger.warning("Failed to save checkpoint: %s", exc)


def run_corporate_action_worker(
    symbols: list[str] | None = None,
    top: int | None = None,
    all_instruments: bool = False,
    delay: float = 0.1,
    resume: bool = True,
    dry_run: bool = False,
    checkpoint_path: Path = CHECKPOINT_FILE,
) -> dict[str, Any]:
    """Execute batch corporate actions synchronization across instruments."""
    session = SessionLocal()
    try:
        # Determine target instruments
        query = select(Instrument).where(Instrument.is_active == True)  # noqa: E712
        if symbols:
            clean_symbols = [s.strip().upper() for s in symbols if s.strip()]
            query = query.where(Instrument.symbol.in_(clean_symbols))
        elif top:
            query = query.order_by(Instrument.id.asc()).limit(top)
        elif not all_instruments:
            # Default to top 50 if nothing specified
            query = query.order_by(Instrument.id.asc()).limit(50)

        instruments = session.scalars(query).all()
        target_symbols = [inst.symbol for inst in instruments]
    finally:
        session.close()

    checkpoint = load_checkpoint(checkpoint_path) if resume else {
        "completed_symbols": [],
        "empty_symbols": [],
        "failed_symbols": {},
        "updated_at": None,
    }

    completed_set = set(checkpoint.get("completed_symbols", []))
    empty_set = set(checkpoint.get("empty_symbols", []))

    provider = TejHQProvider()
    service = CorporateActionService(provider=provider, session_factory=SessionLocal)

    total_synced = 0
    total_actions_inserted = 0
    total_actions_updated = 0
    total_failed = 0

    for symbol in target_symbols:
        if resume and (symbol in completed_set or symbol in empty_set):
            continue

        try:
            raw_actions = provider.get_actions(symbol)
            if not raw_actions:
                empty_set.add(symbol)
                checkpoint["empty_symbols"] = sorted(list(empty_set))
                save_checkpoint(checkpoint, checkpoint_path)
                continue

            if not dry_run:
                audit = service.ingest_actions(symbol, raw_actions)
                total_actions_inserted += audit.actions_inserted
                total_actions_updated += audit.actions_updated

            completed_set.add(symbol)
            checkpoint["completed_symbols"] = sorted(list(completed_set))
            save_checkpoint(checkpoint, checkpoint_path)
            total_synced += 1

            if delay > 0:
                time.sleep(delay)
        except Exception as exc:
            total_failed += 1
            logger.error("Failed corporate actions sync for %s: %s", symbol, exc)
            checkpoint.setdefault("failed_symbols", {})[symbol] = str(exc)
            save_checkpoint(checkpoint, checkpoint_path)

    return {
        "target_count": len(target_symbols),
        "total_synced": total_synced,
        "total_actions_inserted": total_actions_inserted,
        "total_actions_updated": total_actions_updated,
        "total_failed": total_failed,
        "empty_count": len(empty_set),
    }


__all__ = [
    "run_corporate_action_worker",
    "load_checkpoint",
    "save_checkpoint",
    "CHECKPOINT_FILE",
]
