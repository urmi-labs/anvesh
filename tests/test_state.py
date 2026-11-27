from datetime import UTC, datetime, timedelta

from anvesh.state import State, Table, to_iso

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def test_new_key_returns_true_and_sets_both_times(tmp_path):
    table = Table(tmp_path / "jobs.jsonl")
    assert table.upsert("acme:sre", {"title": "SRE"}, now=NOW) is True
    record = table.get("acme:sre")
    assert record["first_seen"] == record["last_seen"] == "2026-11-27T12:00:00Z"


def test_seen_key_keeps_first_seen_and_moves_last_seen(tmp_path):
    table = Table(tmp_path / "jobs.jsonl")
    table.upsert("acme:sre", {"title": "SRE"}, now=NOW)
    later = NOW + timedelta(hours=6)
    assert table.upsert("acme:sre", {"title": "SRE I"}, now=later) is False
    record = table.get("acme:sre")
    assert record["first_seen"] == "2026-11-27T12:00:00Z"
    assert record["last_seen"] == "2026-11-27T18:00:00Z"
    assert record["title"] == "SRE I"


def test_save_then_load_round_trip_sorted(tmp_path):
    path = tmp_path / "companies.jsonl"
    table = Table(path)
    table.upsert("zeta", {"name": "Zeta"}, now=NOW)
    table.upsert("alpha", {"name": "Alpha"}, now=NOW)
    table.save()
    lines = path.read_text().splitlines()
    assert [line.split('"key": "')[1].split('"')[0] for line in lines] == ["alpha", "zeta"]
    again = Table(path)
    assert again.existed and len(again) == 2 and "zeta" in again


def test_prune_drops_only_old_records(tmp_path):
    table = Table(tmp_path / "people.jsonl")
    table.upsert("old", {}, now=NOW - timedelta(days=121))
    table.upsert("fresh", {}, now=NOW - timedelta(days=5))
    assert table.prune(120, now=NOW) == 1
    assert "fresh" in table and "old" not in table


def test_bad_lines_are_skipped_not_fatal(tmp_path):
    path = tmp_path / "jobs.jsonl"
    path.write_text('{"key": "ok", "last_seen": "2026-11-27T12:00:00Z"}\nnot json\n{"no_key": 1}\n')
    table = Table(path)
    assert len(table) == 1 and table.bad_lines == 2


def test_missing_file_starts_empty(tmp_path):
    table = Table(tmp_path / "nope.jsonl")
    assert not table.existed and len(table) == 0


def test_read_only_state_writes_nothing(tmp_path):
    state = State(tmp_path, read_only=True)
    state.table("runs").upsert("x", {}, now=NOW)
    state.save()
    assert list(tmp_path.iterdir()) == []


def test_state_save_writes_each_table(tmp_path):
    state = State(tmp_path)
    state.table("runs").upsert(to_iso(NOW), {}, now=NOW)
    state.table("jobs").upsert("a", {}, now=NOW)
    state.save()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["jobs.jsonl", "runs.jsonl"]
