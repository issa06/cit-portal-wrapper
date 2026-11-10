"""MCP smoke with status-only output; real notice data never enters test logs."""

import argparse
import hashlib
import json
import stat
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import anyio
import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def snapshot(rows):
    return Counter(
        (
            hashlib.sha256(
                json.dumps([r.get(k) for k in ("title", "date", "category")], ensure_ascii=False).encode()
            ).hexdigest(),
            r.get("read_state"),
        )
        for r in rows
    )


async def check(live: bool, download: bool) -> bool:
    with tempfile.TemporaryFile(mode="w+") as errors:
        async with stdio_client(
            StdioServerParameters(command=sys.executable, args=["-m", "cit_campus_mcp.server"]), errlog=errors
        ) as streams:
            async with ClientSession(*streams, read_timeout_seconds=65) as client:
                await client.initialize()
                tools = {t.name: t for t in (await client.list_tools()).tools}
                assert {"portal_get_notice", "portal_get_notice_attachment"} <= tools.keys()
                print('{"case":"notice_tools_list","status":"PASS"}', flush=True)
                if not live:
                    return True

                async def call(name, arguments):
                    tick = time.monotonic()
                    result = await client.call_tool(name, arguments)
                    if not result.is_error:
                        jsonschema.validate(result.structured_content, tools[name].output_schema)
                    return result, round(time.monotonic() - tick, 3)

                result, _ = await call("portal_query", {"kind": "notices", "limit": 200})
                assert not result.is_error
                rows = result.structured_content["items"]
                assert result.structured_content["next_offset"] is None
                before = snapshot(rows)
                unread = next((r for r in rows if r.get("read_state") == "unread"), None)
                if unread:
                    denied, _ = await call("portal_get_notice", {"notice_ref": unread["notice_ref"]})
                    assert (
                        denied.is_error and denied.structured_content["error"]["code"] == "READ_STATE_CHANGE_REQUIRED"
                    )
                    print('{"case":"unread_selection_blocked","status":"PASS"}', flush=True)
                else:
                    print('{"case":"unread_selection_blocked","status":"NOT RUN"}', flush=True)
                read = next((r for r in rows if r.get("read_state") == "read"), None)
                if read is None:
                    print('{"case":"already_read_detail","status":"NOT RUN"}', flush=True)
                    return False
                detail, seconds = await call("portal_get_notice", {"notice_ref": read["notice_ref"]})
                if detail.is_error:
                    print(
                        json.dumps(
                            {
                                "case": "already_read_detail",
                                "status": "FAIL",
                                "error_code": detail.structured_content["error"]["code"],
                            }
                        ),
                        flush=True,
                    )
                    return False
                data = detail.structured_content
                assert data["read_state_unchanged"]
                print(
                    json.dumps(
                        {
                            "case": "already_read_detail",
                            "status": "PASS",
                            "body_present": bool(data["body"]),
                            "sender_present": bool(data["sender"]),
                            "attachments_present": bool(data["attachments"]),
                            "seconds": seconds,
                        }
                    ),
                    flush=True,
                )
                if download:
                    attachment = next((a for a in data["attachments"] if a["download_supported"]), None)
                    if attachment is None:
                        print('{"case":"attachment_download","status":"NOT RUN"}', flush=True)
                        return False
                    file, seconds = await call(
                        "portal_get_notice_attachment",
                        {"notice_ref": read["notice_ref"], "attachment_ref": attachment["attachment_ref"]},
                    )
                    if file.is_error:
                        print(
                            json.dumps(
                                {
                                    "case": "attachment_download",
                                    "status": "FAIL",
                                    "error_code": file.structured_content["error"]["code"],
                                }
                            ),
                            flush=True,
                        )
                        return False
                    metadata = file.structured_content
                    path = Path(metadata["file_path"])
                    assert metadata["read_state_unchanged"] and stat.S_IMODE(path.stat().st_mode) == 0o600
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]
                    print(
                        json.dumps(
                            {
                                "case": "attachment_download",
                                "status": "PASS",
                                "private_file": True,
                                "integrity": True,
                                "seconds": seconds,
                            }
                        ),
                        flush=True,
                    )
                result, _ = await call("portal_query", {"kind": "notices", "limit": 200, "refresh": True})
                assert not result.is_error and snapshot(result.structured_content["items"]) == before
                print('{"case":"independent_final_list_snapshot","status":"PASS"}', flush=True)
                return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--download", action="store_true", help="Save one already-read notice attachment privately after verification."
    )
    args = parser.parse_args()
    if args.download and not args.live:
        parser.error("--download requires --live")
    try:
        passed = anyio.run(check, args.live, args.download)
    except Exception:
        print('{"case":"notice_smoke","status":"FAIL","error_code":"VERIFICATION_FAILED"}')
        passed = False
    raise SystemExit(0 if passed else 1)
