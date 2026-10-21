"""STEP 4: Tools and routing.

Goal: the model decides WHICH tool to call and with WHAT arguments; your Python code
validates, authorizes, and executes it. The model never touches the database.

run_tool() is the safety boundary. It always returns a JSON string, even for errors,
so the model can read the error and correct itself.

Run:  python apexdesk_db.py   (once)
      python step4_tools.py
"""
import json
import sqlite3
from datetime import date

from pydantic import BaseModel, Field, ValidationError

import apexdesk_db as db


# ---- 1. Argument contracts (validated BEFORE anything executes) --------------------
class GetCustomerPlanArgs(BaseModel):
    user_id: int = Field(gt=0, description="The customer's numeric user_id, e.g. 1042")


class GetOpenTicketsArgs(BaseModel):
    user_id: int = Field(gt=0, description="The customer's numeric user_id")


class CreateEscalationArgs(BaseModel):
    user_id: int = Field(gt=0, description="The customer's numeric user_id")
    reason: str = Field(min_length=10, max_length=300, description="Why a human needs to step in")


# ---- 2. The tools themselves (plain Python + parameterized SQL) --------------------
def _clean_status(raw) -> str:
    s = (raw or "").strip().lower()
    return "canceled" if s in ("canceled", "cancelled") else s


def get_customer_plan(user_id: int) -> dict:
    row = db.get_raw_customer(user_id)
    if not row:
        return {"found": False, "error": f"No customer with user_id {user_id}"}
    catalog = db.get_plan_catalog()
    tier = row["plan_tier"].strip().lower()
    current = set(catalog[tier]["features"])
    upgrades = {
        t: {"price_per_month": catalog[t]["price"], "adds_features": [f for f in catalog[t]["features"] if f not in current]}
        for t in db.TIER_ORDER
        if db.TIER_ORDER.index(t) > db.TIER_ORDER.index(tier)
    }
    return {
        "found": True, "user_id": user_id, "company": row["company"], "plan_tier": tier,
        "price_per_month": catalog[tier]["price"], "status": _clean_status(row["status"]),
        "seats": row["seats"], "included_features": catalog[tier]["features"], "upgrade_options": upgrades,
    }


def get_open_tickets(user_id: int) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT ticket_id, subject, status, created_at FROM tickets "
            "WHERE user_id = ? AND status IN ('open', 'escalated') ORDER BY ticket_id", (user_id,)
        ).fetchall()
    return {"user_id": user_id, "open_tickets": [dict(r) for r in rows]}


def create_escalation(user_id: int, reason: str) -> dict:
    """The only tool with a side effect (it writes). In production, gate it behind human approval."""
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (user_id, subject, body, status, created_at) VALUES (?, ?, ?, 'escalated', ?)",
            (user_id, "Escalated by AI agent", reason, date.today().isoformat()),
        )
        return {"ticket_id": cur.lastrowid, "status": "escalated"}


# ---- 3. Registry: tool name (text from the model) -> arguments model + function ----
REGISTRY = {
    "get_customer_plan": (GetCustomerPlanArgs, get_customer_plan,
                          "Look up a customer's plan tier, status, included features and upgrade options."),
    "get_open_tickets": (GetOpenTicketsArgs, get_open_tickets, "List a customer's open support tickets."),
    "create_escalation": (CreateEscalationArgs, create_escalation,
                          "Hand the conversation to a human teammate by creating an escalated ticket."),
}

# JSON schemas the model sees, generated from the same Pydantic models (one source of truth)
TOOLS = [
    {"type": "function", "function": {"name": name, "description": desc, "parameters": args_model.model_json_schema()}}
    for name, (args_model, _fn, desc) in REGISTRY.items()
]


# ---- 4. The safety boundary ---------------------------------------------------------
def run_tool(name: str, raw_arguments: str, authenticated_user_id: int | None = None) -> str:
    """Validate -> authorize -> execute. Always returns a JSON string."""
    if name not in REGISTRY:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(REGISTRY)}"})
    args_model, fn, _desc = REGISTRY[name]
    try:
        args = args_model.model_validate_json(raw_arguments)      # catches bad JSON and wrong types
    except ValidationError as err:
        problems = [{"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in err.errors()]
        return json.dumps({"error": "Invalid arguments", "details": problems})
    if authenticated_user_id is not None and args.user_id != authenticated_user_id:
        return json.dumps({"error": "Not authorized: you can only access the signed-in customer's account."})
    try:
        return json.dumps(fn(**args.model_dump()))
    except sqlite3.Error:
        return json.dumps({"error": "The database is temporarily unavailable."})


if __name__ == "__main__":
    print("OFFLINE: what run_tool does with each model output")
    cases = [
        ("good call", "get_customer_plan", '{"user_id": 1042}', 1042),
        ("wrong type", "get_customer_plan", '{"user_id": "abc"}', 1042),
        ("negative id", "get_customer_plan", '{"user_id": -5}', 1042),
        ("not JSON", "get_customer_plan", "user 1042 please", 1042),
        ("hallucinated tool", "delete_customer", '{"user_id": 1042}', 1042),
        ("other customer's data", "get_customer_plan", '{"user_id": 1044}', 1042),
    ]
    for label, name, args, auth in cases:
        print(f"\n[{label}] {name}({args})\n  -> {run_tool(name, args, auth)[:230]}")

    try:  # optional: let a real model choose the tool (needs OPENAI_API_KEY)
        from llm import MODEL, get_client
        client = get_client()
        r = client.chat.completions.create(
            model=MODEL, temperature=0, tools=TOOLS, tool_choice="auto",
            messages=[{"role": "user", "content": "What plan is customer 1042 on?"}],
        )
        call = r.choices[0].message.tool_calls[0]
        print(f"\nLIVE MODEL chose: {call.function.name}({call.function.arguments})")
        print("Your code ran it ->", run_tool(call.function.name, call.function.arguments, 1042)[:230])
    except RuntimeError as err:
        print(f"\n(Skipping the live-model demo: {err})")
