# BankCore — a medium-range Finacle-like core with a real database.
"""SQLite-backed core banking system for testing PrefectOS governance:
CIF (customer) creation, account opening under schemes, cash transactions,
double-entry fund transfers, statements, beneficiary master, and an EOD
batch that posts SB interest accrual. Deliberately Finacle-flavoured:
scheme codes, CIF ids, narrations, E-codes.

Run:  uvicorn bank_core:app --port 9000        (db file: bankcore.db)
Seed: python3 bank_core.py --seed
Only ever exposed to agents via cbs_gateway (the governed doorway).
"""
from __future__ import annotations
import sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body

DB = Path(__file__).parent / "bankcore.db"
app = FastAPI(title="BankCore (Finacle-like, SQLite)")


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS customers(
      cif TEXT PRIMARY KEY, name TEXT NOT NULL, kyc TEXT DEFAULT 'PENDING',
      segment TEXT DEFAULT 'RETAIL', sol_id TEXT DEFAULT '1001', created_at TEXT);
    CREATE TABLE IF NOT EXISTS accounts(
      acct_no TEXT PRIMARY KEY, cif TEXT NOT NULL REFERENCES customers(cif),
      scheme TEXT NOT NULL, balance REAL NOT NULL DEFAULT 0,
      status TEXT DEFAULT 'ACTIVE', opened_at TEXT);
    CREATE TABLE IF NOT EXISTS transactions(
      txn_id TEXT PRIMARY KEY, ts TEXT, type TEXT, dr_acct TEXT, cr_acct TEXT,
      amount REAL, narration TEXT, channel TEXT, value_date TEXT);
    CREATE TABLE IF NOT EXISTS beneficiaries(
      ben_id TEXT PRIMARY KEY, name TEXT, bank_account TEXT, ifsc TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS eod_log(
      run_id TEXT PRIMARY KEY, ts TEXT, txns_posted INTEGER, interest_posted REAL);
    """)
    conn.commit()


def now(): return datetime.now(timezone.utc).isoformat()
def txn_id(): return "T" + uuid.uuid4().hex[:10].upper()


@app.on_event("startup")
def _startup():
    init(db())


# ── customers (CIF) ────────────────────────────────────────────────────
@app.post("/cbs/customers")
def create_customer(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name: raise HTTPException(422, "E-CIF-422: name required")
    cif = "C" + uuid.uuid4().hex[:6].upper()
    with db() as c:
        c.execute("INSERT INTO customers(cif,name,kyc,segment,created_at) VALUES(?,?,?,?,?)",
                  (cif, name, body.get("kyc", "VERIFIED"), body.get("segment", "RETAIL"), now()))
    return {"status": "CIF_CREATED", "cif": cif, "name": name}


@app.get("/cbs/customers/{cif}")
def get_customer(cif: str):
    r = db().execute("SELECT * FROM customers WHERE cif=?", (cif,)).fetchone()
    if not r: raise HTTPException(404, "E-CIF-404")
    accts = db().execute("SELECT acct_no,scheme,balance,status FROM accounts WHERE cif=?", (cif,)).fetchall()
    return {**dict(r), "accounts": [dict(a) for a in accts]}


@app.get("/cbs/customers")
def list_customers():
    rs = db().execute("SELECT * FROM customers ORDER BY created_at").fetchall()
    return {"customers": [dict(r) for r in rs]}


# ── accounts ───────────────────────────────────────────────────────────
@app.post("/cbs/accounts")
def open_account(body: dict = Body(...)):
    cif, scheme = body.get("cif"), body.get("scheme", "SBGEN")
    if not db().execute("SELECT 1 FROM customers WHERE cif=?", (cif,)).fetchone():
        raise HTTPException(404, "E-CIF-404: unknown customer")
    prefix = "SB" if scheme.startswith("SB") else "CA"
    acct = prefix + str(int(datetime.now().timestamp() * 100) % 10**6).zfill(6)
    with db() as c:
        c.execute("INSERT INTO accounts(acct_no,cif,scheme,balance,opened_at) VALUES(?,?,?,?,?)",
                  (acct, cif, scheme, float(body.get("initial_deposit", 0)), now()))
        if float(body.get("initial_deposit", 0)) > 0:
            c.execute("""INSERT INTO transactions(txn_id,ts,type,dr_acct,cr_acct,amount,narration,channel,value_date)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (txn_id(), now(), "CASH_DEP", "CASH", acct,
                       float(body["initial_deposit"]), "Initial deposit", "BRANCH", now()[:10]))
    return {"status": "ACCT_OPENED", "acct_no": acct, "cif": cif, "scheme": scheme}


@app.get("/cbs/accounts")
def list_accounts():
    rs = db().execute("""SELECT a.acct_no,a.scheme,a.balance,a.status,c.name
                         FROM accounts a JOIN customers c ON c.cif=a.cif
                         ORDER BY a.opened_at""").fetchall()
    return {"accounts": [dict(r) for r in rs]}


@app.get("/cbs/accounts/{acct}/balance")
def balance(acct: str):
    r = db().execute("SELECT * FROM accounts WHERE acct_no=?", (acct,)).fetchone()
    if not r: raise HTTPException(404, "E-ACCT-404")
    return {"acct": acct, "balance": r["balance"], "currency": "INR",
            "status": r["status"], "as_of": now()}


@app.get("/cbs/accounts/{acct}/statement")
def statement(acct: str, n: int = 15):
    rs = db().execute("""SELECT * FROM transactions WHERE dr_acct=? OR cr_acct=?
                         ORDER BY ts DESC LIMIT ?""", (acct, acct, n)).fetchall()
    out = []
    for r in rs:
        d = dict(r)
        d["direction"] = "CR" if r["cr_acct"] == acct else "DR"
        out.append(d)
    return {"acct": acct, "entries": out}


# ── money movement ─────────────────────────────────────────────────────
@app.post("/cbs/tx/cash")
def cash(body: dict = Body(...)):
    acct, amt = body.get("acct"), float(body.get("amount", 0))
    kind = body.get("kind", "DEPOSIT").upper()
    r = db().execute("SELECT balance FROM accounts WHERE acct_no=? AND status='ACTIVE'", (acct,)).fetchone()
    if not r: raise HTTPException(404, "E-ACCT-404")
    if amt <= 0: raise HTTPException(422, "E-AMT-422")
    if kind == "WITHDRAW" and r["balance"] < amt:
        raise HTTPException(422, "E-FUNDS-422: insufficient funds")
    delta = amt if kind == "DEPOSIT" else -amt
    with db() as c:
        c.execute("UPDATE accounts SET balance=balance+? WHERE acct_no=?", (delta, acct))
        c.execute("""INSERT INTO transactions(txn_id,ts,type,dr_acct,cr_acct,amount,narration,channel,value_date)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  (txn_id(), now(), "CASH_" + ("DEP" if kind == "DEPOSIT" else "WDL"),
                   "CASH" if kind == "DEPOSIT" else acct,
                   acct if kind == "DEPOSIT" else "CASH",
                   amt, body.get("narration", f"Cash {kind.lower()}"), "BRANCH", now()[:10]))
    nb = db().execute("SELECT balance FROM accounts WHERE acct_no=?", (acct,)).fetchone()["balance"]
    return {"status": "POSTED", "acct": acct, "new_balance": nb}


@app.post("/cbs/payments/transfer")
def transfer(body: dict = Body(...)):
    src, dst, amt = body.get("from"), body.get("to"), float(body.get("amount", 0))
    a = db().execute("SELECT balance FROM accounts WHERE acct_no=? AND status='ACTIVE'", (src,)).fetchone()
    b = db().execute("SELECT 1 FROM accounts WHERE acct_no=? AND status='ACTIVE'", (dst,)).fetchone()
    if not a or not b: raise HTTPException(404, "E-ACCT-404")
    if amt <= 0 or a["balance"] < amt: raise HTTPException(422, "E-FUNDS-422")
    t = txn_id()
    with db() as c:   # double entry, one txn row with both legs
        c.execute("UPDATE accounts SET balance=balance-? WHERE acct_no=?", (amt, src))
        c.execute("UPDATE accounts SET balance=balance+? WHERE acct_no=?", (amt, dst))
        c.execute("""INSERT INTO transactions(txn_id,ts,type,dr_acct,cr_acct,amount,narration,channel,value_date)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  (t, now(), "TRANSFER", src, dst, amt,
                   body.get("narration", f"TRF {src}->{dst}"), "AGENT", now()[:10]))
    return {"status": "POSTED", "txn_id": t, "from": src, "to": dst, "amount": amt}


# ── beneficiary master (the fraud target) ──────────────────────────────
@app.get("/cbs/beneficiaries")
def list_ben():
    return {"beneficiaries": [dict(r) for r in db().execute("SELECT * FROM beneficiaries").fetchall()]}


@app.put("/cbs/beneficiaries/{ben_id}/bank-account")
def change_ben(ben_id: str, body: dict = Body(...)):
    if not db().execute("SELECT 1 FROM beneficiaries WHERE ben_id=?", (ben_id,)).fetchone():
        raise HTTPException(404, "E-BEN-404")
    with db() as c:
        c.execute("UPDATE beneficiaries SET bank_account=?, ifsc=?, updated_at=? WHERE ben_id=?",
                  (body.get("bank_account"), body.get("ifsc", ""), now(), ben_id))
    return {"status": "UPDATED", "ben_id": ben_id}


# ── EOD: post 0.01% daily interest accrual on SB balances ──────────────
@app.post("/cbs/eod/run")
def eod():
    run, total, count = "EOD" + uuid.uuid4().hex[:6].upper(), 0.0, 0
    with db() as c:
        for r in c.execute("SELECT acct_no,balance FROM accounts WHERE scheme LIKE 'SB%' AND status='ACTIVE'").fetchall():
            interest = round(r["balance"] * 0.0001, 2)
            if interest <= 0: continue
            c.execute("UPDATE accounts SET balance=balance+? WHERE acct_no=?", (interest, r["acct_no"]))
            c.execute("""INSERT INTO transactions(txn_id,ts,type,dr_acct,cr_acct,amount,narration,channel,value_date)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (txn_id(), now(), "INT_CR", "INTPOOL", r["acct_no"], interest,
                       "SB interest accrual", "EOD", now()[:10]))
            total += interest; count += 1
        c.execute("INSERT INTO eod_log VALUES(?,?,?,?)", (run, now(), count, total))
    return {"status": "EOD_COMPLETE", "run_id": run, "interest_txns": count,
            "interest_posted": round(total, 2)}


if __name__ == "__main__":
    import sys
    if "--seed" in sys.argv:
        if DB.exists(): DB.unlink()
        conn = db(); init(conn)
        cs = [("C000001", "R. Sharma", "RETAIL"), ("C000002", "Acme Traders", "MSME"),
              ("C000003", "P. Iyer", "RETAIL")]
        for cif, name, seg in cs:
            conn.execute("INSERT INTO customers(cif,name,kyc,segment,created_at) VALUES(?,?,?,?,?)",
                         (cif, name, "VERIFIED", seg, now()))
        accts = [("SB100101", "C000001", "SBGEN", 245000.0), ("CA200201", "C000002", "CAGEN", 1830000.0),
                 ("SB100301", "C000003", "SBGEN", 88000.0), ("SB100102", "C000001", "SBPRM", 512000.0)]
        for a, cif, sch, bal in accts:
            conn.execute("INSERT INTO accounts(acct_no,cif,scheme,balance,opened_at) VALUES(?,?,?,?,?)",
                         (a, cif, sch, bal, now()))
        conn.execute("INSERT INTO beneficiaries VALUES(?,?,?,?,?)",
                     ("B901", "Sunrise Suppliers", "UTIB000123456", "UTIB0000012", now()))
        conn.commit()
        print("bankcore.db seeded: 3 customers, 4 accounts, 1 beneficiary")
