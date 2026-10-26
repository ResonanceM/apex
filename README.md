# ApexDesk Tier-1 Support Agent

## Task statement

A guided lab project: you are the Lead AI Engineer at **ApexDesk**, a fake B2B SaaS company that sells
workflow software to small businesses. Your mandate: build an AI Tier-1 Support Agent that reduces
ticket load, using messy data, internal database lookups, and multi-step tasks.

You build it in five steps, one script per step. Each step adds one production layer.

```
[Step 1: Pydantic schema] -> [Step 2: SQLite memory] -> [Step 3: Guardrails]
                -> [Step 4: Tools & routing] -> [Step 5: Full ReAct loop]
```

## Setup (Python 3.10+)

```bash
pip install -r requirements.txt
cp .env.example .env        # then put your OpenAI key in .env
python apexdesk_db.py       # creates customers.db with deliberately messy data
```

No key yet? Steps 3 and 4 (offline part), the tests, and `demo_offline.py` all run without one.

**How one request flows through all the layers:** see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The five steps

| Step | Script | You build | You learn |
|---|---|---|---|
| 1 | `step1_schema.py` | `CustomerSummary` Pydantic model | Instructor forces strict JSON, retrying on validation errors |
| 2 | `step2_memory.py` | `apexdesk_chat.db` with `(session_id, role, content)` | State lives in a database, not a Python variable |
| 3 | `step3_guardrails.py` | Regex pre-flight filter + post-flight audit | Deterministic code protects sensitive logic |
| 4 | `step4_tools.py` | `get_customer_plan(user_id)` and friends, behind `run_tool()` | The model proposes arguments; your code validates, authorizes, and executes |
| 5 | `step5_react_agent.py` | The full loop with every layer | Reason, act, observe, with memory and safety |

Supporting files: `apexdesk_db.py` (fake company data), `llm.py` (client setup), `fake_llm.py` (scripted model
for offline runs), `demo_offline.py`, and `tests/test_offline.py`.

## Run order

```bash
python step1_schema.py
python step2_memory.py          # then: python step2_memory.py --show   (history survives restarts)
python step3_guardrails.py      # no key needed
python step4_tools.py           # offline checks, plus a live demo if a key is set
python step5_react_agent.py     # scripted customer scenarios
python step5_react_agent.py --chat --user 1042    # talk to it yourself
python demo_offline.py          # the whole loop with a scripted model, no key
python -m unittest discover -s tests -v           # 23 offline tests
```

## Design decisions worth knowing

- **The model never touches the database.** It proposes `{"user_id": 1042}`; `run_tool()` validates the
  arguments, checks the signed-in customer is allowed that account, then runs parameterized SQL.
- **`run_tool()` always returns JSON, even for errors,** so the model can read the error and correct itself.
- **Blocked messages are not saved to history.** Replaying an injection attempt on later turns would
  re-attack the model.
- **Regex guardrails are one layer, not the whole defense.** `step3_guardrails.py` shows a paraphrased attack
  slipping past them on purpose. Tool authorization and the output audit still protect you.
- **A hard `MAX_TURNS` cap** stops a runaway loop and escalates to a human.

## Proof for your write-up

Every run appends to `logs/react_trace.jsonl`. Use it as evidence. A scripted example from `demo_offline.py`:

```
CUSTOMER: Hi! I can't access Custom Reports on my account.
  step 0 | preflight   | allowed=True category=ok
  step 1 | thought     | text=The customer can't use Custom Reports. I'll check their plan first.
  step 1 | action      | tool=get_customer_plan args={"user_id": 1042}
  step 1 | observation | result={"found": true, "user_id": 1042, "company": "Brightline Logistics", ...
  step 2 | final       | text=Thanks for reaching out! Custom Reports isn't included in your Basic plan. ...
  step 6 | postflight  | allowed=True category=ok
```

Portfolio write-up outline:

1. **The business problem:** automating Tier-1 customer resolutions without risking wrong answers or leaks.
2. **The architecture:** schema enforcement, SQLite state, pre/post-flight guardrails, validated tools, ReAct loop.
3. **The proof:** your trace logs, the 23 passing tests, and the cases that were blocked or denied.

## Harder next steps

- Gate `create_escalation` behind a human approval prompt (roadmap Week 4).
- Add an LLM-as-judge eval over a golden set of support questions (tutorial Day 13).
- Trace the loop with Langfuse and measure cost per resolved ticket (roadmap Weeks 9 to 10).
