"""Exercise the packaged stdio transport and background result retrieval with no search."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result) -> dict:
    if result.isError:
        raise RuntimeError("staged_tool_transport_error")
    if isinstance(result.structuredContent, dict):
        return result.structuredContent
    for block in result.content:
        if getattr(block, "type", None) == "text":
            value = json.loads(block.text)
            if isinstance(value, dict):
                return value
    raise RuntimeError("staged_tool_result_missing")


async def smoke(stage: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="pcf-stdio-") as data:
        env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "POE2_MCP_DATA": data,
            "PYTHONPATH": os.pathsep.join([str(stage / "lib"), str(stage)]),
        }
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "server.mcp.build_server"],
            cwd=str(stage),
            env=env,
        )
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert {"get_compute_operation", "cancel_compute_operation"} <= tools
                for name, arguments in (
                    ("new_build", {}),
                    ("set_class", {"class_name": "Sorceress"}),
                    ("set_level", {"level": 98}),
                    ("set_skill", {"skill": "Fireball 20/0"}),
                ):
                    result = payload(await session.call_tool(name, arguments))
                    assert result.get("ok") is not False, (name, result.get("errorCode"))
                before = payload(await session.call_tool("list_skill_groups", {}))
                result = payload(await session.call_tool("optimize_supports", {
                    "metric": "__unsupported_smoke_objective__",
                    "purpose": "final_audit",
                    "background": True,
                }))
                operation_id = result.get("operationId")
                assert operation_id, result
                for _ in range(200):
                    result = payload(await session.call_tool(
                        "get_compute_operation", {"operation_id": operation_id}
                    ))
                    if result.get("status") not in {
                        "starting", "running", "finalizing", "cancel_requested",
                        "budget_exceeded_requested",
                    }:
                        break
                    await asyncio.sleep(0.025)
                assert result["status"] == "completed", result
                assert result["result"]["ok"] is False, result
                assert "objective" in result["result"].get("errorCode", ""), result
                again = payload(await session.call_tool(
                    "get_compute_operation", {"operation_id": operation_id}
                ))
                assert again["result"] == result["result"]
                after = payload(await session.call_tool("list_skill_groups", {}))
                assert before["stateHash"] == after["stateHash"]
                health = payload(await session.call_tool("engine_health", {}))
                assert health["runtimeContract"] == health["requiredRuntimeContract"]
                assert health["status"] == "idle"
                return {
                    "status": "passed",
                    "runtimeContract": health["runtimeContract"],
                    "operationResultRetrievedTwice": True,
                    "businessFailureDistinctFromCompletion": True,
                    "inputStateRestored": True,
                    "publicUpload": False,
                    "scope": "real_staged_stdio_and_PoB_with_zero_candidate_search",
                }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    stage = args.stage.resolve()
    if not (stage / "server/mcp/build_server.py").is_file():
        raise FileNotFoundError("staged_build_server_missing")
    print(json.dumps(asyncio.run(asyncio.wait_for(smoke(stage), timeout=90)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
