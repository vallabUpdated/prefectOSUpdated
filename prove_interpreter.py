"""Prove the interpreter works: three rehearsed vendor behaviours, each
arriving downstream in perfect house format or as a named incident.
Run from repo root:  python prove_interpreter.py"""
from pathlib import Path
from batch_ingest.external.mock_adapter import MockAnalyzer
from batch_ingest.external.dispatch import _canonical_to_result
from batch_ingest.external.base import AdapterError

a, tmp = MockAnalyzer(), Path("interp_test"); tmp.mkdir(exist_ok=True)
for name in ("unknown_doc", "vendor_exception_case", "vendor_down_case"):
    f = tmp / f"{name}.pdf"; f.write_bytes(b"x")
    try:
        c = a.analyze(str(f))
        r = _canonical_to_result(c, name)
        print(f"OK {name:24s} status={r.status:9s} "
              f"producer={r.provenance['producer']}")
    except AdapterError as e:
        print(f"OK {name:24s} structured failure: {e.reason}")
