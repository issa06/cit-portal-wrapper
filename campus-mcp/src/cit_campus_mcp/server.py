from __future__ import annotations

from functools import lru_cache

from mcp.server import MCPServer

from .documents import DocumentsClient
from .manaba import ManabaClient
from .portal import PortalClient, get_attendance, get_grades, get_notices, get_student_info, get_timetable

mcp = MCPServer("CIT Campus")


@lru_cache(maxsize=1)
def _portal() -> PortalClient:
    return PortalClient()


@lru_cache(maxsize=1)
def _manaba() -> ManabaClient:
    return ManabaClient()


@lru_cache(maxsize=1)
def _documents() -> DocumentsClient:
    return DocumentsClient()


@mcp.tool()
def portal_status() -> dict[str, object]:
    """Verify the CIT Portal session and authentication state."""
    return _portal().status()


@mcp.tool()
def portal_get_notices(full: bool = False) -> list[dict[str, object]]:
    """Get read-only notices from CIT Portal."""
    top = _portal().connect()
    return get_notices(top, full=full)


@mcp.tool()
def portal_get_grades() -> list[dict[str, object]]:
    """Get the student's grade records from CIT Portal."""
    top = _portal().connect()
    return get_grades(top)


@mcp.tool()
def portal_get_attendance() -> list[dict[str, object]]:
    """Get attendance records from CIT Portal."""
    top = _portal().connect()
    return get_attendance(top)


@mcp.tool()
def portal_get_timetable() -> list[dict[str, object]]:
    """Get the timetable/attendance-style snapshot exposed by the Portal menu used by the existing wrapper."""
    top = _portal().connect()
    return get_timetable(top)


@mcp.tool()
def portal_get_student_info() -> dict[str, object]:
    """Get student information from CIT Portal. Face-photo base64 data is intentionally excluded."""
    top = _portal().connect()
    return get_student_info(top, include_photo=False)


@mcp.tool()
def manaba_list_courses() -> list[dict[str, str]]:
    """List courses visible to the authenticated manaba account."""
    return _manaba().list_courses()


@mcp.tool()
def manaba_list_action_items() -> list[dict[str, str | None]]:
    """List task-like links such as reports, quizzes, surveys, and submission items from manaba."""
    return _manaba().list_action_items()


@mcp.tool()
def manaba_get_page_text(path_or_url: str) -> dict[str, str]:
    """Read text from a page on cit.manaba.jp. This tool never submits assignments or modifies data."""
    return _manaba().get_page_text(path_or_url)


@mcp.tool()
def docs_list_links() -> list[dict[str, str]]:
    """List links from the CIT student documents portal."""
    return _documents().list_links()


@mcp.tool()
def docs_search(query: str, limit: int = 20) -> list[dict[str, str]]:
    """Search HTML/PDF text under the CIT student documents portal using a bounded read-only crawler."""
    return _documents().search(query, max(1, min(limit, 50)))


@mcp.tool()
def docs_get_text(url: str, max_chars: int = 50000) -> dict[str, str]:
    """Extract text from a specific HTML or PDF URL on the CIT student documents host."""
    return _documents().get_text(url, max(1000, min(max_chars, 200000)))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
