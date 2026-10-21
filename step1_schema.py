"""STEP 1: Schema enforcement (the output contract).

Goal: turn a messy database row into a clean CustomerSummary that a dashboard can
trust. If the model returns something invalid, Instructor sends the validation
error back and the model fixes it (max_retries).

Run:  python apexdesk_db.py   (once, to create the database)
      python step1_schema.py
"""
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

import apexdesk_db as db
from llm import MODEL, get_structured_client


class CustomerSummary(BaseModel):
    user_id: int
    company: str
    plan_tier: str = Field(description="One of: basic, pro, enterprise (lowercase).")
    status: Literal["active", "canceled"]
    seats: int = Field(ge=1)
    summary: str = Field(description="One sentence about the account, 25 words maximum.")

    @field_validator("plan_tier")
    @classmethod
    def plan_must_be_known(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in db.PLANS:
            raise ValueError(f"plan_tier must be one of {list(db.PLANS)}, got {v!r}")
        return v

    @field_validator("summary")
    @classmethod
    def summary_must_be_short(cls, v: str) -> str:
        if len(v.split()) > 25:
            raise ValueError("summary is longer than 25 words, make it shorter")
        return v


SYSTEM_PROMPT = """You convert one raw ApexDesk customer database row into a clean CustomerSummary.
Normalization rules:
- plan_tier: lowercase (basic, pro, or enterprise).
- status: "canceled" for any spelling of cancelled/canceled; "active" for everything else
  (active, past_due, trial). Mention past-due billing in the summary instead.
- Use only facts in the row. Never invent data."""


def summarize_account(raw_row: dict, client=None) -> CustomerSummary:
    client = client or get_structured_client()
    return client.chat.completions.create(
        model=MODEL,
        response_model=CustomerSummary,   # the contract
        max_retries=3,                    # validation errors are fed back to the model
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(raw_row)},
        ],
    )


if __name__ == "__main__":
    try:
        for user_id in (1042, 1044, 1045):
            raw = db.get_raw_customer(user_id)
            print(f"\nRAW ROW      {raw}")
            print("CLEAN JSON  ", summarize_account(raw).model_dump_json(indent=2))
    except RuntimeError as err:
        print(err)
