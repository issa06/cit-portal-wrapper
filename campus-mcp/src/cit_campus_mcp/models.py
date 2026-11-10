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
