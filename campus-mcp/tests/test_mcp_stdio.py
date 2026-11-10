import os
import sys
import time
from pathlib import Path

import anyio
import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ARGUMENTS = {
    "portal_status": {},
    "portal_query": {"kind": "notices"},
    "portal_get_notices": {},
    "portal_get_grades": {},
    "portal_get_attendance": {},
    "portal_get_timetable": {},
    "portal_get_student_info": {},
    "manaba_list_courses": {},
    "manaba_list_action_items": {},
    "manaba_get_page_text": {"path_or_url": "/ct/home"},
    "docs_list_links": {},
    "docs_search": {"query": "synthetic"},
    "docs_get_text": {"url": "https://kmsk.is.it-chiba.ac.jp/portal/test"},
}


def test_stdio_initialize_list_and_every_tool(tmp_path):
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).with_name("fixture_server.py"))],
            env={"CIT_SESSION_DIR": str(tmp_path / "sessions"), "PATH": os.environ.get("PATH", "")},
        )
        with (tmp_path / "stderr").open("w+") as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                async with ClientSession(*streams, read_timeout_seconds=10) as client:
                    info = await client.initialize()
                    assert info.server_info.name == "CIT Campus"
                    tools = (await client.list_tools()).tools
                    assert {t.name for t in tools} == set(ARGUMENTS)
                    for tool in tools:
                        assert tool.description and tool.input_schema and tool.output_schema
                        assert tool.annotations.read_only_hint
                        jsonschema.validate(ARGUMENTS[tool.name], tool.input_schema)
                        result = await client.call_tool(tool.name, ARGUMENTS[tool.name])
                        assert not result.is_error
                        jsonschema.validate(result.structured_content, tool.output_schema)
                    page = await client.call_tool("portal_query", {"kind": "notices", "offset": 1})
                    assert page.structured_content["items"] == []
                    assert page.structured_content["next_offset"] is None
                    bad = await client.call_tool("portal_query", {"kind": "notices", "limit": 201})
                    assert bad.is_error
                    assert bad.structured_content["error"]["code"] == "INVALID_TOOL_CALL"
                    bad = await client.call_tool("portal_query", {"kind": "synthetic-private-argument"})
                    assert bad.is_error and "synthetic-private-argument" not in bad.model_dump_json()
            errlog.seek(0)
            assert "Synthetic" not in errlog.read()

    anyio.run(check)


def test_stdio_machine_readable_errors_and_privacy(tmp_path):
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).with_name("fixture_server.py"))],
            env={"CIT_TEST_MODE": "errors"},
        )
        with (tmp_path / "stderr").open("w+") as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                async with ClientSession(*streams, read_timeout_seconds=10) as client:
                    await client.initialize()
                    for tool, code in [("portal_status", "AUTHENTICATION_FAILED"), ("portal_get_grades", "TIMEOUT")]:
                        result = await client.call_tool(tool)
                        assert result.is_error and result.structured_content["error"]["code"] == code
                        assert "synthetic-secret" not in result.model_dump_json()
                        assert "synthetic-password" not in result.model_dump_json()
            errlog.seek(0)
            assert "synthetic-" not in errlog.read()

    anyio.run(check)


def test_stdio_cancellation_keeps_initialize_ping_responsive(tmp_path):
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).with_name("fixture_server.py"))],
            env={"CIT_TEST_MODE": "slow"},
        )
        with (tmp_path / "stderr").open("w+") as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                async with ClientSession(*streams, read_timeout_seconds=10) as client:
                    await client.initialize()
                    with anyio.move_on_after(0.1) as scope:
                        await client.call_tool("portal_get_notices")
                    assert scope.cancel_called
                    tick = time.monotonic()
                    await client.send_ping()
                    assert time.monotonic() - tick < 0.5

    anyio.run(check)
