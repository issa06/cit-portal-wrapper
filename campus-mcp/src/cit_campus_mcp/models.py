from typing import Any, Literal

from pydantic import BaseModel, Field


class PortalPage(BaseModel):
    items: list[dict[str, Any]]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_offset: int | None
    fetched_at: str
    source: str
    kind: Literal["notices", "timetable", "attendance", "grades"]
    status: Literal["ok", "empty"]
    date_semantics: Literal["weekly_pattern_only"] | None = None


class NoticeAttachment(BaseModel):
    attachment_ref: str
    name: str
    download_supported: bool


class NoticeDetail(BaseModel):
    notice_ref: str
    title: str
    date: str | None
    category: str | None
    sender: str | None
    body: str
    attachments: list[NoticeAttachment]
    fetched_at: str
    source: str
    read_state: Literal["read"] = "read"
    read_state_unchanged: Literal[True] = True
    verification_scope: Literal["requested_list_snapshot"] = "requested_list_snapshot"


class NoticeDownload(BaseModel):
    notice_ref: str
    attachment_ref: str
    name: str
    file_path: str
    content_type: str
    size_bytes: int
    sha256: str
    fetched_at: str
    read_state_unchanged: Literal[True] = True
