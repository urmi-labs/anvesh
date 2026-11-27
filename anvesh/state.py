"""Run-to-run memory: one JSONL file per table in the state folder."""

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from anvesh.config import StateSettings

PRUNE_DAYS = StateSettings().retention_days  # default only; settings.yaml state.retention_days overrides


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(moment: datetime) -> str:
    """Format a time as UTC, for example 2026-11-27T12:36:37Z."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


class Table:
    """One JSONL file. Each line is one record with a unique "key" field."""

    def __init__(self, path: Path):
        self.path = path
        self.records: dict[str, dict] = {}
        self.existed = path.exists()
        self.bad_lines = 0
        if self.existed:
            self._load()

    def _load(self) -> None:
        with self.path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    key = record["key"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    self.bad_lines += 1
                    print(f"warning: {self.path.name} line {line_no} is unreadable, skipped", file=sys.stderr)
                    continue
                self.records[key] = record

    def __contains__(self, key: str) -> bool:
        return key in self.records

    def __len__(self) -> int:
        return len(self.records)

    def get(self, key: str) -> dict | None:
        return self.records.get(key)

    def upsert(self, key: str, data: dict, now: datetime | None = None) -> bool:
        """Insert or update a record. Returns True if the key was not seen before."""
        stamp = to_iso(now or utc_now())
        old = self.records.get(key)
        record = {**(old or {}), **data, "key": key, "last_seen": stamp}
        record.setdefault("first_seen", stamp)
        self.records[key] = record
        return old is None

    def prune(self, max_age_days: int = PRUNE_DAYS, now: datetime | None = None) -> int:
        """Delete records whose last_seen is older than max_age_days. Returns how many were deleted."""
        cutoff = (now or utc_now()) - timedelta(days=max_age_days)
        stale = [
            key
            for key, record in self.records.items()
            if "last_seen" in record and from_iso(record["last_seen"]) < cutoff
        ]
        for key in stale:
            del self.records[key]
        return len(stale)

    def save(self) -> None:
        """Write all records sorted by key, so each commit is a small readable diff."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for key in sorted(self.records):
                f.write(json.dumps(self.records[key], sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)


class State:
    """The state folder. Hands out tables and saves them all at the end of a run."""

    def __init__(self, directory: str | Path, read_only: bool = False):
        self.directory = Path(directory)
        self.read_only = read_only
        self._tables: dict[str, Table] = {}

    def table(self, name: str) -> Table:
        if name not in self._tables:
            self._tables[name] = Table(self.directory / f"{name}.jsonl")
        return self._tables[name]

    def save(self, prune_days: int = PRUNE_DAYS) -> None:
        if self.read_only:
            return
        for table in self._tables.values():
            table.prune(prune_days)
            table.save()
