#!/usr/bin/env python3
"""End-to-end check of the whole NorthBank platform using only the standard library.

Local mode (default): talks straight to each service port started by scripts/run_local.sh.
Gateway mode: BASE=http://localhost:8080 python3 scripts/smoke_test.py
   Internal endpoints are not reachable through the gateway (by design), so KYC approval and the audit
   check are skipped unless you provide KYC_ADMIN_URL / AUDIT_URL yourself.
"""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "").rstrip("/")
INTERNAL = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "local-internal-token")}
if BASE:
    AUTH, CUST, ACC, TX = f"{BASE}/auth", f"{BASE}/customers", f"{BASE}/accounts", f"{BASE}/transfers"
    CARDS, LOANS, LEDGER, NOTE = f"{BASE}/cards", f"{BASE}/loans", f"{BASE}/ledger", f"{BASE}/notifications"
    KYC_ADMIN, AUDIT = os.environ.get("KYC_ADMIN_URL", ""), os.environ.get("AUDIT_URL", "")
else:
    AUTH, CUST, ACC, TX = ("http://127.0.0.1:8001", "http://127.0.0.1:8005/customers",
                           "http://127.0.0.1:8002/accounts", "http://127.0.0.1:8003/transfers")
    CARDS, LOANS, LEDGER, NOTE = ("http://127.0.0.1:8007/cards", "http://127.0.0.1:8008/loans",
                                  "http://127.0.0.1:8009/ledger", "http://127.0.0.1:8004/notifications")
    KYC_ADMIN, AUDIT = os.environ.get("KYC_ADMIN_URL", "http://127.0.0.1:8005"), os.environ.get("AUDIT_URL", "http://127.0.0.1:8010")

failures = 0


def call(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "null")
        except ValueError:
            return e.code, None
    except OSError as e:  # connection refused, timeout, DNS failure: report it as status 0
        return 0, {"detail": f"cannot reach {url}: {e}"}


def check(name, condition, detail=""):
    global failures
    print(("PASS: " if condition else "FAIL: ") + name + ("" if condition else f"   ({detail})"))
    failures += 0 if condition else 1


def wait_for(fn, seconds=12):
    end = time.time() + seconds
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.5)
    return fn()


user, pw = f"user{random.randint(10000, 99999)}", "correct-horse-battery"
s, _ = call("POST", f"{AUTH}/register", {"username": user, "password": pw})
check("register", s == 201, s)
s, body = call("POST", f"{AUTH}/login", {"username": user, "password": pw})
check("login", s == 200, s)
H = {"Authorization": f"Bearer {body['access_token']}"}
uid = json.loads(__import__("base64").urlsafe_b64decode(body["access_token"].split(".")[1] + "==")).get("sub")

s, _ = call("POST", CUST, {"full_name": "Test Customer", "email": f"{user}@example.com"}, H)
check("create customer profile", s == 201, s)

if KYC_ADMIN:
    s, body = call("POST", ACC, {}, H)
    check("account opening is blocked before KYC", s == 403, f"{s} {body}")
    s, _ = call("POST", f"{KYC_ADMIN}/internal/customers/{uid}/kyc", {"status": "verified"}, INTERNAL)
    check("KYC verified by compliance", s == 200, s)

s, a1 = call("POST", ACC, {}, H)
s2, a2 = call("POST", ACC, {}, H)
check("open two accounts", s == 201 and s2 == 201, f"{s} {s2} {a1}")
A1, A2 = a1["id"], a2["id"]
s, _ = call("POST", f"{ACC}/{A1}/deposit", {"amount_cents": 10_000}, H)
check("deposit", s == 200, s)

key = f"smoke-{random.randint(0, 10**9)}"
transfer = {"from_account": A1, "to_account": A2, "amount_cents": 2_500}
s, t = call("POST", TX, transfer, {**H, "Idempotency-Key": key})
check("transfer completed", s == 201 and t["status"] == "completed", f"{s} {t}")
s, _ = call("POST", TX, transfer, {**H, "Idempotency-Key": key})
check("replaying the same key returns 200", s == 200, s)
_, acc = call("GET", f"{ACC}/{A1}", None, H)
check("no double spend (balance 7500)", acc["balance_cents"] == 7_500, acc)

s, t = call("POST", TX, {**transfer, "amount_cents": 9_000_000}, {**H, "Idempotency-Key": key + "-big"})
check("fraud denies a huge transfer", t and t["status"] == "failed" and "fraud" in t["reason"], f"{s} {t}")
s, t = call("POST", TX, {**transfer, "amount_cents": 1_500_000}, {**H, "Idempotency-Key": key + "-rev"})
check("fraud holds a large transfer for review", t and t["status"] == "held", f"{s} {t}")

s, card = call("POST", CARDS, {"account_id": A1}, H)
check("issue card (number shown once)", s == 201 and len(card.get("card_number", "")) == 16, f"{s} {card}")
s, c2 = call("POST", f"{CARDS}/{card['id']}/freeze", None, H)
check("freeze card", s == 200 and c2["status"] == "frozen", f"{s} {c2}")

s, loan = call("POST", LOANS, {"account_id": A1, "amount_cents": 100_000, "term_months": 12}, H)
check("loan approved", s == 201 and loan["status"] == "approved", f"{s} {loan}")
_, acc = call("GET", f"{ACC}/{A1}", None, H)
check("loan paid out into the account (balance 107500)", acc["balance_cents"] == 107_500, acc)
s, sched = call("GET", f"{LOANS}/{loan['id']}/schedule", None, H)
check("repayment schedule has 12 rows", s == 200 and len(sched) == 12, s)

# ---- asynchronous side effects: these arrive through the Redis stream, so we poll ----
def notes():
    s, n = call("GET", NOTE, None, H)
    return n if s == 200 and n and len(n) >= 6 else None

n = wait_for(notes)
text = " | ".join(x["message"] for x in (n or []))
check("notifications arrived via the event stream", n is not None, "none arrived: is Redis running?")
for needle in ("completed", "fraud", "on hold", "identity was verified", "card ending", "loan of"):
    check(f"notification mentions '{needle}'", needle in text, text[:200])

def statement():
    s, st = call("GET", f"{LEDGER}/accounts/{A1}/statement", None, H)
    return st if s == 200 and st["total_debits_cents"] == 2_500 else None

st = wait_for(statement)
check("ledger statement shows the 2500 debit exactly once", st is not None, st)

if AUDIT:
    def audited():
        s, rows = call("GET", f"{AUDIT}/audit?user_id={uid}", None, INTERNAL)
        return rows if s == 200 and len({r["type"] for r in rows}) >= 6 else None
    rows = wait_for(audited)
    check("audit service recorded the whole journey", rows is not None, rows and sorted({r["type"] for r in rows}))

print("\nALL SMOKE CHECKS PASSED" if failures == 0 else f"\n{failures} CHECK(S) FAILED")
sys.exit(1 if failures else 0)
