"""冒烟测试：用 mcp client 启动 server 并调用工具。

用法（在项目根）：
  uv run python scripts/smoke_test.py list_sources
  uv run python scripts/smoke_test.py crawl_jobs '{"source": "platform-demo"}'
  uv run python scripts/smoke_test.py --config config/companies.test.yaml crawl_jobs '{"source": "x"}'
  uv run python scripts/smoke_test.py render_briefing '{"title":"测试","markdown":"|a|b|\n|-|-|\n|1|2|"}'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _content_text(result) -> str:
    parts = []
    for c in result.content:
        if hasattr(c, "text"):
            parts.append(c.text)
        elif hasattr(c, "data"):
            parts.append(str(c.data))
        else:
            parts.append(str(c))
    return "\n".join(parts)


async def call(name: str, args: dict, config: str | None) -> None:
    server_args = ["--directory", str(PROJECT_ROOT), "run", "python", "-m", "getwork"]
    if config:
        server_args += ["--config", config]
    server = StdioServerParameters(command="uv", args=server_args, env=None)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"TOOLS: {names}")
            result = await session.call_tool(name, args)
            print(f"--- {name} ---")
            print(_content_text(result))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="companies.yaml 路径")
    parser.add_argument("tool")
    parser.add_argument("json_args", nargs="?", default="{}")
    opts = parser.parse_args()
    args = json.loads(opts.json_args)
    asyncio.run(call(opts.tool, args, opts.config))


if __name__ == "__main__":
    main()
