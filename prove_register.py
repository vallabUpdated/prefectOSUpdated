"""Prove the register works: every passage through the doorway writes a
governance event — success, failure, refusal — with fingerprints.
Run from repo root:  python prove_register.py
Then the sealed-chain demo:
  EXTRACTOR_PROVIDER=mock  -> one batch via /ui as demo_coexist ->
  python batch_ledger.py verify-all projects
  grep external_call projects/batches/*/decision_ledger.jsonl
"""
import asyncio
import json
import os
from pathlib import Path

from batch_ingest.external.dispatch import run_extraction


class RegisterSpy:
    """Stands in for the batch chain; prints every event as it is written."""
    def __call__(self, event_type, **fields):
        print(f"  REGISTER <- {event_type}")
        for k, v in fields.items():
            print(f"      {k}: {str(v)[:64]}")


async def main():
    spy = RegisterSpy()
    tmp = Path("register_test"); tmp.mkdir(exist_ok=True)

    print("\n1) SUCCESS — vendor consulted, entry with fingerprints:")
    os.environ["EXTRACTOR_PROVIDER"] = "mock"
    os.environ["EXTERNAL_EGRESS_POLICY"] = "client_consented_v1"
    f = tmp / "clean_doc.pdf"; f.write_bytes(b"%PDF specimen")
    r = await run_extraction(str(f), "clean_doc", "pilot",
                             "bank_statement", spy)
    print(f"   -> came back status={r.status}, "
          f"producer={r.provenance['producer']}")

    print("\n2) FAILURE — vendor down, structured incident recorded:")
    f2 = tmp / "vendor_down_case.pdf"; f2.write_bytes(b"%PDF specimen")
    try:
        await run_extraction(str(f2), "down_doc", "pilot",
                             "bank_statement", spy)
    except Exception as e:
        print(f"   -> raised {type(e).__name__} (and the register knows)")

    print("\n3) REFUSAL — sovereign client, bolted door recorded:")
    cfg = Path("register_test/routing.json")
    cfg.write_text(json.dumps(
        {"clients": {"sovereign_bank": {"provider": "internal_only"}}}))
    os.environ["EXTRACTOR_ROUTING_CONFIG"] = str(cfg)
    sample = "22343240649159_statement.pdf"
    src = Path(sample) if Path(sample).exists() else f
    r3 = await run_extraction(str(src), "sov_doc", "sovereign_bank",
                              "bank_statement", spy)
    print(f"   -> processed INTERNALLY (status={r3.status}); "
          "no external_call event above = nothing egressed")


if __name__ == "__main__":
    asyncio.run(main())
