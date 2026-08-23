"""Prove the standard doorway works: the contract must REJECT incomplete
adapters and ACCEPT complete ones.   Run:  python prove_door.py"""
from batch_ingest.external.base import BaseAnalyzer, sha256_obj


class LazyVendor(BaseAnalyzer):          # forgot to implement analyze()
    vendor_name = "lazy"


class TinyVendor(BaseAnalyzer):          # honest minimal fitting
    vendor_name = "tiny"
    cost_per_call_estimate_inr = 0.0

    def analyze(self, file_path, doc_type="bank_statement"):
        return {"doc_id": "demo", "status": "clean", "header": {},
                "n_transactions": 0, "transactions": [], "totals": {},
                "exceptions": [], "elapsed_ms": 0.1,
                "provenance": {"producer": self.vendor_name}}


if __name__ == "__main__":
    try:
        LazyVendor()
        print("PROBLEM: the door accepted an incomplete adapter")
    except TypeError as e:
        print("OK - door REJECTED an incomplete adapter:", e)

    t = TinyVendor()
    answer = t.analyze("any.pdf")
    print("OK - door ACCEPTED a complete adapter:", answer["provenance"])
    print("OK - answer fingerprint:", sha256_obj(answer)[:16], "...")
