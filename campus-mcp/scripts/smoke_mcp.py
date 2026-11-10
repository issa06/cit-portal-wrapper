"""Protocol/live smoke: output status and timings only, never returned university data."""

import argparse
import json
import resource
import sys
import tempfile
import time

import anyio
import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(live: bool) -> bool:
    start = time.perf_counter()
    ok = True
    params = StdioServerParameters(command=sys.executable, args=["-m", "cit_campus_mcp.server"])
    with tempfile.TemporaryFile(mode="w+") as errors:
        async with stdio_client(params, errlog=errors) as streams:
            async with ClientSession(*streams, read_timeout_seconds=65) as client:
                info = await client.initialize()
                tools = {t.name: t for t in (await client.list_tools()).tools}
                print(
                    json.dumps(
                        {
                            "case": "initialize_tools_list",
                            "status": "PASS",
                            "version": info.server_info.version,
                            "tool_count": len(tools),
                            "milliseconds": round((time.perf_counter() - start) * 1000, 2),
                        }
                    ),
                    flush=True,
                )
                if live:
                    calls = [
                        ("portal_status", {}),
                        *[
                            ("portal_query", {"kind": kind})
                            for kind in ["notices", "timetable", "attendance", "grades"]
                        ],
                        ("portal_get_notices", {"full": True}),
                        ("portal_query", {"kind": "notices"}),
                    ]
                    for index, (name, args) in enumerate(calls):
                        tick = time.perf_counter()
                        result = await client.call_tool(name, args)
                        label = args.get("kind", name) + ("_warm" if index == len(calls) - 1 else "")
                        report = {
                            "case": label,
                            "status": "FAIL" if result.is_error else "PASS",
                            "milliseconds": round((time.perf_counter() - tick) * 1000, 2),
                        }
                        if result.is_error:
                            report["error_code"] = (
                                (result.structured_content or {}).get("error", {}).get("code", "PROTOCOL_ERROR")
                            )
                            ok = False
                        else:
                            jsonschema.validate(result.structured_content, tools[name].output_schema)
                        print(json.dumps(report), flush=True)
    # macOS reports bytes; Linux reports KiB. No private payloads enter stdout/stderr.
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    print(json.dumps({"child_peak_rss_mib": round(rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 2)}))
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use existing Keychain/session for read-only Portal calls.")
    args = parser.parse_args()
    try:
        passed = anyio.run(check, args.live)
    except Exception:
        print('{"case":"protocol_smoke","status":"FAIL","error_code":"PROTOCOL_ERROR"}')
        passed = False
    raise SystemExit(0 if passed else 1)
