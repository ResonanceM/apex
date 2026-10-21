"""ApexDesk's fake company database: plans, customers, and support tickets.

The rows are deliberately messy, like real enterprise data: inconsistent casing,
stray whitespace, NULLs, a duplicate account, and two spellings of "canceled".
Run `python apexdesk_db.py` to (re)create customers.db.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).with_name("customers.db")

TIER_ORDER = ["basic", "pro", "enterprise"]
_BASE = ["task_boards", "email_notifications", "csv_export"]
_PRO = _BASE + ["custom_reports", "workflow_automation", "api_access"]
PLANS = {
    "basic": {"price": 29, "features": _BASE},
    "pro": {"price": 79, "features": _PRO},
    "enterprise": {"price": 199, "features": _PRO + ["sso", "audit_logs", "priority_support"]},
}

# (user_id, company, contact_email, plan_tier, status, seats, signup_date, notes)
CUSTOMERS = [
    (1042, "Brightline Logistics", "ops@brightline.example", "Basic", "Active", 5, "2024-03-12", "Asked about reports twice"),
    (1043, "Harbor & Pine Dental", None, "PRO", "active ", 12, "2023-11-02", None),
    (1044, "Kestrel Studios", "hello@kestrel.example", "enterprise", "Cancelled", 40, "2022-06-30", "Churned after price change"),
    (1045, "Northwind Bakery", "orders@northwind.example", "basic", "past_due", 3, "2025-01-20", "Card declined twice"),
    (1046, "Brightline Logistics (old)", "ops@brightline.example", "pro", "canceled", 8, "2021-09-15", "Duplicate account, migrated to 1042"),
]
# (user_id, subject, body, status, created_at)
TICKETS = [
    (1042, "Reports tab missing", "I can't find the Reports tab on my dashboard.", "open", "2025-02-03"),
    (1042, "Invoice question", "Why was I charged for 5 seats?", "closed", "2025-01-10"),
    (1043, "API key not working", "My integration returns 403.", "open", "2025-02-01"),
    (1045, "Payment failed", "Please retry my card.", "open", "2025-02-05"),
]


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def seed(reset: bool = True) -> None:
    with connect() as conn:
        if reset:
            conn.executescript("DROP TABLE IF EXISTS tickets; DROP TABLE IF EXISTS customers; DROP TABLE IF EXISTS plans;")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS plans (plan_tier TEXT PRIMARY KEY, monthly_price INTEGER, features TEXT);
            CREATE TABLE IF NOT EXISTS customers (
                user_id INTEGER PRIMARY KEY, company TEXT, contact_email TEXT, plan_tier TEXT,
                status TEXT, seats INTEGER, signup_date TEXT, notes TEXT);
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, subject TEXT,
                body TEXT, status TEXT, created_at TEXT);
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO plans VALUES (?, ?, ?)",
            [(tier, p["price"], json.dumps(p["features"])) for tier, p in PLANS.items()],
        )
        conn.executemany("INSERT OR REPLACE INTO customers VALUES (?,?,?,?,?,?,?,?)", CUSTOMERS)
        conn.executemany(
            "INSERT INTO tickets (user_id, subject, body, status, created_at) VALUES (?,?,?,?,?)", TICKETS
        )


def get_raw_customer(user_id: int):
    """Return the customer row exactly as stored (messy), or None."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_plan_catalog() -> dict:
    """tier -> {"price": int, "features": [..]} read from the plans table."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM plans").fetchall()
    return {r["plan_tier"]: {"price": r["monthly_price"], "features": json.loads(r["features"])} for r in rows}


if __name__ == "__main__":
    seed()
    with connect() as conn:
        for table in ("plans", "customers", "tickets"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table:<10} {n} rows")
    print(f"Created {DB_PATH.name}")
