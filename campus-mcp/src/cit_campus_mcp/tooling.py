from __future__ import annotations

import json
from functools import partial, wraps
from threading import RLock

import anyio
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel

from .errors import RequestTimeout, ResponseTooLarge, public_error

_operations = RLock()


def _invoke(function, args, kwargs):
    with _operations:
        anyio.from_thread.check_cancelled()
        return function(*args, **kwargs)


def safe_tool(function):
    """Keep sync HTTP work off the MCP loop; return allowlisted errors only."""

    @wraps(function)
    async def call(*args, **kwargs):
        try:
            with anyio.fail_after(60):
                value = await anyio.to_thread.run_sync(partial(_invoke, function, args, kwargs), abandon_on_cancel=True)
            encoded = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
            if len(json.dumps(encoded, ensure_ascii=False).encode()) > 128 * 1024:
                raise ResponseTooLarge("Use a smaller page size.")
            return value
        except TimeoutError:
            error = public_error(RequestTimeout())
        except Exception as exc:
            error = public_error(exc)
        payload = {"error": error}
        return CallToolResult(
            is_error=True, structured_content=payload, content=[TextContent(type="text", text=json.dumps(payload))]
        )

    return call
