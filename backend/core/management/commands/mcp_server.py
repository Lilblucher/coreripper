"""MCP (Model Context Protocol) server exposing CoreRipper's network toolbox.

Built on the official `mcp` SDK (`pip install "mcp[cli]"`, confirmed working
on this box's anaconda Python  an earlier assumption that this dev box has
no PyPI access at all turned out to be stale for this environment specifically).

Run it with:
    /home/clive/anaconda3/bin/python manage.py mcp_server

Point an MCP client at it via stdio, e.g. in Claude Desktop's
claude_desktop_config.json:
    {
      "mcpServers": {
        "coreripper": {
          "command": "/home/clive/anaconda3/bin/python",
          "args": ["manage.py", "mcp_server"],
          "cwd": "/home/clive/Documents/Core/backend"
        }
      }
    }

Only "local" tier, "operational" status tools are exposed  the same tools a
logged-out guest can already reach for free through /api/toolbox/. Premium
("api" tier) tools are deliberately left out: this server has no concept of
a logged-in CoreRipper user, so it can't bill/gate them.
"""
from typing import Annotated

from django.core.management.base import BaseCommand
from pydantic import Field

from core.models import Tool
from network_tools.views import run_tool_internal

# Tools whose run_tool_internal() signature needs more than just `target`.
# Maps tool_key -> {param_name: description}. Every tool implicitly also
# takes `target`.
EXTRA_PARAMS = {
    "dkim_check": {"selector": "DKIM selector to look up (default: \"default\")"},
    "robots_check": {
        "path": "Path to test against robots.txt rules (default: \"/\")",
        "user_agent": "User-agent string to test (default: \"*\")",
    },
    "scam_detector": {"region_hint": "Optional region/country hint to improve scam heuristics"},
}

TARGET_DESCRIPTIONS = {
    "scam_detector": "The message text to scan for scam indicators.",
    "port_scan": "Host to scan (hostname or IP).",
    "traceroute": "Host to trace (hostname or IP).",
    "ping": "Host to ping (hostname or IP).",
}
DEFAULT_TARGET_DESCRIPTION = "Domain, URL, or IP address to run the tool against."


def _target_desc(tool_key):
    return TARGET_DESCRIPTIONS.get(tool_key, DEFAULT_TARGET_DESCRIPTION)


def _make_tool_fn(tool_key):
    """Build a function whose signature matches this tool_key's extra params
    exactly, so FastMCP's schema introspection only exposes fields the tool
    actually accepts. Only 4 signature shapes exist among all 32 tools."""
    target_field = Annotated[str, Field(description=_target_desc(tool_key))]
    extra = EXTRA_PARAMS.get(tool_key)

    if tool_key == "dkim_check":
        def fn(target: target_field, selector: Annotated[str, Field(description=extra["selector"])] = "default") -> dict:
            return run_tool_internal(tool_key, target, selector=selector)
    elif tool_key == "robots_check":
        def fn(
            target: target_field,
            path: Annotated[str, Field(description=extra["path"])] = "/",
            user_agent: Annotated[str, Field(description=extra["user_agent"])] = "*",
        ) -> dict:
            return run_tool_internal(tool_key, target, path=path, user_agent=user_agent)
    elif tool_key == "scam_detector":
        def fn(target: target_field, region_hint: Annotated[str, Field(description=extra["region_hint"])] = "") -> dict:
            return run_tool_internal(tool_key, target, region_hint=region_hint)
    else:
        def fn(target: target_field) -> dict:
            return run_tool_internal(tool_key, target)

    fn.__name__ = tool_key
    return fn


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("coreripper-toolbox")
    tools = Tool.objects.filter(tier="local", status="operational").exclude(tool_key="").order_by("tool_key")
    for t in tools:
        mcp.add_tool(_make_tool_fn(t.tool_key), name=t.tool_key, description=f"{t.name}  CoreRipper network tool.")
    return mcp


class Command(BaseCommand):
    help = "Run CoreRipper's network toolbox as an MCP server over stdio."

    def handle(self, *args, **options):
        server = build_server()
        server.run(transport="stdio")
