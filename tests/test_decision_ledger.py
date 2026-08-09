"""Tests for decision_ledger — hash-chained, tamper-evident run provenance."""

import json
from pathlib import Path

import pytest

from decision_ledger import (
    GENESIS_HASH,
    DecisionLedger,
    activate_ledger,
    active_ledger,
    record,
    sha256_text,
    verify_file,
)


@pytest.fixture()
def ledger(tmp_path: Path) -> DecisionLedger:
    return DecisionLedger(tmp_path)


def _fill(ledger: DecisionLedger, n: int = 5) -> None:
    for i in range(n):
        ledger.append("gate_decision", gate=f"stage{i}", decision="approve",
                      approved_artifact_sha256=sha256_text(f"artifact-{i}"))


class TestHappyPath:
    def test_empty_ledger_head_is_genesis(self, ledger):
        assert ledger.head_hash == GENESIS_HASH
        assert ledger.entry_count == 0

    def test_append_returns_sealed_entry(self, ledger):
        e = ledger.append("run_started", activity="build a ledger app")
        assert e["seq"] == 1
        assert e["prev_hash"] == GENESIS_HASH
        assert len(e["entry_hash"]) == 64
        assert ledger.head_hash == e["entry_hash"]

    def test_chain_verifies(self, ledger):
        _fill(ledger, 10)
        ok, n, err = ledger.verify()
        assert ok and n == 10 and err is None

    def test_resume_continues_chain(self, tmp_path):
        first = DecisionLedger(tmp_path)
        _fill(first, 3)
        head = first.head_hash
        resumed = DecisionLedger(tmp_path)          # e.g. --resume run
        assert resumed.entry_count == 3
        e = resumed.append("run_complete")
        assert e["seq"] == 4 and e["prev_hash"] == head
        ok, n, _ = verify_file(resumed.path)
        assert ok and n == 4

    def test_reserved_keys_cannot_be_spoofed(self, ledger):
        e = ledger.append("gate_decision", seq=999, prev_hash="fff",
                          entry_hash="fff", gate="planner:output")
        assert e["seq"] == 1 and e["prev_hash"] == GENESIS_HASH
        assert ledger.verify()[0]


class TestTamperDetection:
    def test_edited_field_detected(self, ledger):
        _fill(ledger)
        lines = ledger.path.read_text().splitlines()
        doc = json.loads(lines[2])
        doc["decision"] = "reject"                  # rewrite history
        lines[2] = json.dumps(doc, ensure_ascii=False)
        ledger.path.write_text("\n".join(lines) + "\n")
        ok, n, err = verify_file(ledger.path)
        assert not ok and n == 2 and "tampered" in err

    def test_deleted_line_detected(self, ledger):
        _fill(ledger)
        lines = ledger.path.read_text().splitlines()
        del lines[1]
        ledger.path.write_text("\n".join(lines) + "\n")
        ok, _, err = verify_file(ledger.path)
        assert not ok and ("seq" in err or "prev_hash" in err)

    def test_reordered_lines_detected(self, ledger):
        _fill(ledger)
        lines = ledger.path.read_text().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        ledger.path.write_text("\n".join(lines) + "\n")
        assert not verify_file(ledger.path)[0]

    def test_forged_insertion_detected(self, ledger):
        _fill(ledger)
        lines = ledger.path.read_text().splitlines()
        forged = json.loads(lines[0])
        forged["seq"] = 2
        lines.insert(1, json.dumps(forged, ensure_ascii=False))
        ledger.path.write_text("\n".join(lines) + "\n")
        assert not verify_file(ledger.path)[0]

    def test_garbage_line_detected(self, ledger):
        _fill(ledger)
        with ledger.path.open("a") as fh:
            fh.write("not json at all\n")
        ok, _, err = verify_file(ledger.path)
        assert not ok and "invalid JSON" in err

    def test_missing_file(self, tmp_path):
        ok, n, err = verify_file(tmp_path / "nope.jsonl")
        assert not ok and n == 0 and "not found" in err


class TestActiveLedgerHelpers:
    def test_record_is_best_effort_when_inactive(self, monkeypatch):
        import decision_ledger as dl
        monkeypatch.setattr(dl, "_active", None)
        record("gate_decision", gate="x")            # must not raise
        assert active_ledger() is None

    def test_activate_and_record(self, tmp_path, monkeypatch):
        led = activate_ledger(tmp_path)
        record("run_started", channel="test")
        assert led.entry_count == 1
        assert led.verify()[0]
