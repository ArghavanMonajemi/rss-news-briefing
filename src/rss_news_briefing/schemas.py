from datetime import datetime

from pydantic import BaseModel


class UsageResponse(BaseModel):
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class BriefingResponse(BaseModel):
    briefing: str
    article_count: int
    sources: list[str]
    cached: bool
    generated_at: datetime
    usage: UsageResponse | None = None
    mode: str  # "single" or "map-reduce"
    failed_summaries: int


class HealthResponse(BaseModel):
    status: str
