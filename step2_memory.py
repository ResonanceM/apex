"""STEP 2: Durable memory (state management).

Goal: a customer sends several messages over many minutes. The conversation lives in
SQLite, keyed by session_id, not in a Python variable that disappears on restart.

Each turn:  hydrate (load history)  ->  call the model  ->  persist (save both turns)

Run:  python step2_memory.py          # 3-message demo (needs OPENAI_API_KEY)
      python step2_memory.py --show   # print the stored history, even after a restart
"""
import argparse
import sqlite3
from contextlib import contextmanager
from pathlib import Path

CHAT_DB = Path(__file__).with_name("apexdesk_chat.db")
SYSTEM_PROMPT = "You are ApexDesk's friendly Tier-1 support assistant. Be concise and use the conversation so far."


@contextmanager
def connect():
    conn = sqlite3.connect(CHAT_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_chat_db() -> None:
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)")


def save_turn(session_id: str, role: str, content: str) -> None:
    init_chat_db()
    with connect() as conn:
        conn.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))


def load_history(session_id: str, limit: int = 20) -> list:
    """Hydrate: the last `limit` messages, oldest first. The limit is a simple window
    so a long conversation can't grow the prompt (and your bill) without bound."""
    init_chat_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT role, content FROM (
                   SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
               ) ORDER BY id ASC""",
            (session_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def clear_session(session_id: str) -> None:
    init_chat_db()
    with connect() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))


def chat_turn(session_id: str, user_text: str, client=None) -> str:
    from llm import MODEL, get_client

    client = client or get_client()
    history = load_history(session_id)                                    # 1. hydrate
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": user_text}]
    response = client.chat.completions.create(model=MODEL, messages=messages, temperature=0)
    reply = response.choices[0].message.content
    save_turn(session_id, "user", user_text)                              # 2. persist
    save_turn(session_id, "assistant", reply)
    return reply


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true", help="print the stored history and exit")
    parser.add_argument("--session", default="demo-session-1")
    args = parser.parse_args()

    if args.show:
        for turn in load_history(args.session, limit=100):
            print(f"{turn['role']:>9}: {turn['content']}")
    else:
        try:
            clear_session(args.session)
            for text in [
                "Hi, I'm Dana from Brightline Logistics.",
                "We're on the Basic plan with 5 seats.",
                "Quick check: which company did I say I was from, and which plan are we on?",
            ]:
                print(f"\nCUSTOMER: {text}\nAGENT:    {chat_turn(args.session, text)}")
            print(f"\n{len(load_history(args.session))} messages stored in {CHAT_DB.name}.")
            print("Run `python step2_memory.py --show` in a fresh process: the history is still there.")
        except RuntimeError as err:
            print(err)
