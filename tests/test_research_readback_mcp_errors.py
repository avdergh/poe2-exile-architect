"""Research readback errors retain readable MCP content without structured output."""

from __future__ import annotations

import asyncio
import json

from mcp import types
import pytest

from scripts import research_mature_builds
from server import main
from server.knowledge import research_workflow
from server.mcp import research_server


@pytest.mark.parametrize(
    "mcp_server", [main.mcp, research_server.mcp], ids=["aggregate", "research"]
)
@pytest.mark.parametrize("should_fail", [True, False], ids=["error", "success"])
def test_read_research_case_mcp_response_shape(monkeypatch, tmp_path, mcp_server, should_fail):
    # Keep the real MCP -> main -> workflow chain. Only the filesystem boundary and
    # underlying section reader are synthetic; no run, lease, database or PoB is used.
    run_ref = "research-run:synthetic-error-shape"
    run_dir = tmp_path / "uncreated-run"
    resolved_refs = []
    reads = []
    safe_error = "unsafe transient research payload: ['long_guide_prose_like']"
    success = {
        "status": "ok",
        "section": "pob-readback",
        "items": [],
        "complete": True,
        "nextCursor": None,
        "noRawMatureBuildMaterial": True,
    }

    def resolve_run(value):
        resolved_refs.append(value)
        return run_dir

    def read_section(**kwargs):
        reads.append(kwargs)
        if should_fail:
            raise ValueError(safe_error)
        return success

    monkeypatch.setattr(research_workflow, "_run_dir", resolve_run)
    monkeypatch.setattr(research_mature_builds, "read_case_section", read_section)
    monkeypatch.setattr(main.tool_telemetry, "record_tool_call", lambda **_: None)
    request = types.CallToolRequest(
        params=types.CallToolRequestParams(
            name="read_research_case",
            arguments={
                "run_ref": run_ref,
                "lease_token": "synthetic-lease",
                "section": "pob-readback",
                "cursor": 2,
                "limit": 3,
            },
        )
    )
    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]
    result = asyncio.run(handler(request))
    wire = result.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert resolved_refs == [run_ref]
    assert reads == [
        {
            "output_dir": run_dir,
            "lease_token": "synthetic-lease",
            "section": "pob-readback",
            "cursor": 2,
            "limit": 3,
            "node_type": None,
            "exclude_routing": False,
        }
    ]
    assert not run_dir.exists()
    readable_content = "\n".join(
        block["text"] for block in wire["content"] if block["type"] == "text"
    )
    if should_fail:
        assert wire["isError"] is True
        assert safe_error in readable_content
        # This is a valid SDK error response. Consumers must read content instead
        # of assuming structuredContent exists or storing its undefined JS value.
        assert "structuredContent" not in wire
    else:
        assert wire["isError"] is False
        assert wire["structuredContent"] == success
        assert json.loads(readable_content) == success
