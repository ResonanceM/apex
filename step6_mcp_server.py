"""STEP 6 (extension): the same tools, behind an MCP server.

In Step 4 your tools sat in a Python dict inside one program. Here they move into a separate
server process that ANY MCP client can connect to. The server exposes all three MCP primitives:
  - tools      the three actions from Step 4
  - a resource read-only data (the plan catalog)
  - a prompt   the support-agent system prompt

Security: the model never says who the customer is. The host that launches this server does,
through the APEXDESK_USER_ID environment variable. Every tool call still goes through run_tool()
from Step 4, so validation and the "only the signed-in customer" check live inside the server.

Run it yourself:  APEXDESK_USER_ID=1042 python step6_mcp_server.py   (it waits for a client on stdio)
Normally a client starts it for you: see step6_mcp_client.py.

Note: a stdio server must never print to stdout. That stream carries the protocol messages.
"""
import json
import os
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import apexdesk_db as db
from step4_tools import run_tool
from step5_react_agent import SYSTEM_PROMPT

AUTH_USER = None   # set at startup from the environment, never from the model

mcp = MCPServer(
    "apexdesk",
    instructions="ApexDesk support tools. Every call is limited to the one signed-in customer.",
    log_level=os.environ.get("APEXDESK_LOG", "INFO"),   # logs go to stderr, never stdout
)


def _call(name: str, arguments: dict) -> str:
    """Hand the call to the same validate -> authorize -> execute boundary used in Step 4."""
    if AUTH_USER is None:   # fail closed: no signed-in customer, no data
        raise ToolError("This server was started without a signed-in customer.")
    result = run_tool(name, json.dumps(arguments), authenticated_user_id=AUTH_USER)
    if "error" in json.loads(result):
        raise ToolError(result)   # MCP's native error flag (isError), so any client can tell failure from data
    return result


@mcp.tool()
def get_customer_plan(user_id: int) -> str:
    """Look up a customer's plan tier, status, included features and upgrade options."""
    return _call("get_customer_plan", {"user_id": user_id})


@mcp.tool()
def get_open_tickets(user_id: int) -> str:
    """List a customer's open support tickets."""
    return _call("get_open_tickets", {"user_id": user_id})


@mcp.tool()
def create_escalation(user_id: int, reason: str) -> str:
    """Hand the conversation to a human teammate by creating an escalated ticket."""
    return _call("create_escalation", {"user_id": user_id, "reason": reason})


@mcp.resource("apexdesk://plans", mime_type="application/json")
def plan_catalog() -> str:
    """Read-only: every plan with its monthly price and features."""
    return json.dumps(db.get_plan_catalog())


@mcp.prompt()
def support_agent() -> str:
    """The Tier-1 support agent's system prompt for the signed-in customer."""
    return SYSTEM_PROMPT.format(user_id=AUTH_USER)


def main() -> None:
    global AUTH_USER
    raw = os.environ.get("APEXDESK_USER_ID", "")
    if not raw.isdigit() or int(raw) <= 0:
        sys.exit("Set APEXDESK_USER_ID to the signed-in customer's id, for example 1042.")
    AUTH_USER = int(raw)
    if not db.DB_PATH.exists():
        db.seed()
    mcp.run("stdio")


if __name__ == "__main__":
    main()
