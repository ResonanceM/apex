"""STEP 6 (extension): an MCP client, and the Step 5 agent loop running through it.

The client starts the server as a subprocess, then DISCOVERS what it offers (tools, a resource, a
prompt) instead of having the tools hard-coded. The agent loop is the same as Step 5, except a tool
call now goes over MCP to the server, which does the validation and authorization.

Needs:  pip install -r requirements.txt   (the mcp package, version 2)

Run:  python step6_mcp_client.py          # walkthrough + scripted agent, no API key needed
      python step6_mcp_client.py --live   # the same scenarios with a real model (needs OPENAI_API_KEY)
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from step3_guardrails import SAFE_FALLBACK, postflight_audit, preflight_check
from step5_react_agent import LIMIT_MESSAGE

HERE = Path(__file__).parent
MAX_TURNS = 5


def server_params(user_id: int, extra_env: dict | None = None) -> StdioServerParameters:
    """How to start the server. The HOST (this code) tells it who is signed in, not the model."""
    env = {"APEXDESK_USER_ID": str(user_id), **(extra_env or {})}
    if "APEXDESK_LOG" in os.environ:   # lets you silence the server's log: APEXDESK_LOG=CRITICAL
        env.setdefault("APEXDESK_LOG", os.environ["APEXDESK_LOG"])
    return StdioServerParameters(command=sys.executable, args=[str(HERE / "step6_mcp_server.py")],
                                 env=env, cwd=str(HERE))


def text_of(result) -> str:
    return "".join(c.text for c in result.content if hasattr(c, "text"))


def to_openai_tools(mcp_tools) -> list:
    """MCP tool descriptions -> the format a chat model expects."""
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.input_schema}} for t in mcp_tools]


async def ask_agent(user_text: str, user_id: int, model=None, extra_env: dict | None = None) -> str:
    """Step 5's loop, but every tool call goes over MCP."""
    verdict = preflight_check(user_text)
    if not verdict.allowed:
        return verdict.message
    if model is None:
        from llm import get_client
        model = get_client()
    from llm import MODEL

    async with Client(server_params(user_id, extra_env)) as client:
        tools = to_openai_tools((await client.list_tools()).tools)             # discovered, not hard-coded
        system = (await client.get_prompt("support_agent")).messages[0].content.text
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_text}]
        final = None
        for _step in range(MAX_TURNS):
            msg = model.chat.completions.create(model=MODEL, messages=messages, tools=tools,
                                                tool_choice="auto", temperature=0).choices[0].message
            if not msg.tool_calls:
                final = msg.content or ""
                break
            messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = None
                if not isinstance(args, dict):
                    out = json.dumps({"error": "Arguments were not valid JSON"})
                else:
                    try:
                        result = await client.call_tool(tc.function.name, args)   # <- over MCP
                        out = text_of(result)
                    except Exception as err:                                      # unknown tool, transport trouble...
                        out = json.dumps({"error": f"Tool call failed: {err}"})
                print(f"    mcp call: {tc.function.name}({tc.function.arguments}) -> {out[:110]}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        if final is None:
            final = LIMIT_MESSAGE
    audit = postflight_audit(final)
    return final if audit.allowed else SAFE_FALLBACK


async def tour(user_id: int = 1042) -> None:
    print(f"Starting the server for signed-in customer {user_id} ...")
    async with Client(server_params(user_id)) as client:
        print(f"Connected to '{client.server_info.name}' using protocol version {client.protocol_version}\n")
        print("TOOLS (discovered):")
        for t in (await client.list_tools()).tools:
            print(f"  {t.name}({', '.join(t.input_schema.get('required', []))}): {t.description}")
        print("\nRESOURCES:", [r.uri for r in (await client.list_resources()).resources])
        print("  apexdesk://plans ->", (await client.read_resource("apexdesk://plans")).contents[0].text[:70], "...")
        print("PROMPTS:  ", [p.name for p in (await client.list_prompts()).prompts])

        print("\nCALLS (server is bound to the signed-in customer)")
        for label, name, args in [
            ("good call", "get_customer_plan", {"user_id": user_id}),
            ("wrong type", "get_customer_plan", {"user_id": "abc"}),
            ("negative id", "get_customer_plan", {"user_id": -5}),
            ("someone else's account", "get_customer_plan", {"user_id": 1044}),
        ]:
            r = await client.call_tool(name, args)
            print(f"  [{label}] is_error={r.is_error}  {text_of(r)[:120]!r}")


if __name__ == "__main__":
    from fake_llm import FakeClient, reply, tool_call

    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="use a real model instead of the scripted one")
    live = parser.parse_args().live
    try:
        asyncio.run(tour())
        print("\nAGENT OVER MCP" + (" (live model)" if live else " (scripted model, no API calls)"))
        scenarios = [
            ("I can't access Custom Reports on my account.", lambda: FakeClient([
                reply("Let me check.", [tool_call("c1", "get_customer_plan", '{"user_id": 1042}')]),
                reply("Custom Reports isn't in your Basic plan. Pro ($79/month) adds it. Want help upgrading?")])),
            ("What plan is customer 1044 on?", lambda: FakeClient([
                reply(None, [tool_call("c2", "get_customer_plan", '{"user_id": 1044}')]),
                reply("I can only help with the account you're signed in to.")])),
        ]
        for text, scripted in scenarios:
            print(f"\nCUSTOMER: {text}")
            print("AGENT:   ", asyncio.run(ask_agent(text, 1042, model=None if live else scripted())))
    except RuntimeError as err:
        print(err)
