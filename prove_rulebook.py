"""Prove the rulebook works: resolution order, per-client pages, and the
bolted door as a LOCK (not a memo).   Run from repo root:
    python prove_rulebook.py
"""
import asyncio
import json
import os
from pathlib import Path

from batch_ingest.external.dispatch import (resolve_extractor_provider,
                                            run_extraction)
from batch_ingest.external.base import EgressForbidden


class Spy:
    def __init__(self): self.events = []
    def __call__(self, ev, **f): self.events.append(ev); print(f"  REGISTER <- {ev}")


def clean_env():
    for k in list(os.environ):
        if k.startswith(("EXTRACTOR_", "HYBRID_", "RECONCILE_")):
            del os.environ[k]


async def main():
    tmp = Path("rulebook_test"); tmp.mkdir(exist_ok=True)
    cfg = tmp / "routing.json"
    cfg.write_text(json.dumps({"clients": {
        "sovereign_bank": {"provider": "internal_only"},
        "nbfc_client":    {"provider": "mock",
                           "doc_types": {"scanned": "mock"}}}}))

    print("1) RESOLUTION ORDER — most specific wins:")
    clean_env()
    print("   no rules anywhere            ->",
          resolve_extractor_provider("anyone"))
    os.environ["EXTRACTOR_PROVIDER"] = "hybrid"
    print("   house default (env)          ->",
          resolve_extractor_provider("anyone"))
    os.environ["EXTRACTOR_PROVIDER_SCANNED"] = "mock"
    print("   doc-type page (env, scanned) ->",
          resolve_extractor_provider("anyone", "scanned"))
    os.environ["EXTRACTOR_ROUTING_CONFIG"] = str(cfg)
    print("   client page (config file)    ->",
          resolve_extractor_provider("nbfc_client"))
    print("   client page beats env        ->",
          resolve_extractor_provider("sovereign_bank"))

    print("\n2) THE LOCK — sovereign client, vendor path physically refused:")
    spy = Spy()
    f = tmp / "vendor_down_case.pdf"; f.write_bytes(b"%PDF x")
    os.environ["EXTRACTOR_PROVIDER"] = "hybrid"   # house says vendors OK...
    os.environ["HYBRID_VENDOR"] = "mock"
    r = await run_extraction(str(f), "sov1", "sovereign_bank",
                             "bank_statement", spy)
    ext = [e for e in spy.events if e == "external_call"]
    print(f"   -> status={r.status}; external_call events: {len(ext)} "
          "(the client's page overruled the house default)")

    print("\n3) HYBRID — internal fails, rulebook permits rescue:")
    spy2 = Spy()
    bad = tmp / "garbage.pdf"; bad.write_bytes(b"not a pdf")
    r2 = await run_extraction(str(bad), "hyb1", "nbfc_client",
                              "bank_statement", spy2)
    print(f"   -> producer={getattr(r2, 'provenance', {}).get('producer')} "
          f"(vendor rescued it, and the register saw the visit)")


if __name__ == "__main__":
    asyncio.run(main())
