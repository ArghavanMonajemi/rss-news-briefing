import logging
import threading
import time
from contextlib import asynccontextmanager
from .models import BriefingFormatError
from decouple import config
from fastapi import FastAPI, HTTPException
from openai import OpenAIError

from .config import BRIEFING_TTL_MINUTES
from .pipeline import BriefingResult, NoArticlesError, generate_briefing
from .schemas import BriefingResponse, HealthResponse, UsageResponse

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config("API-KEY")  # fail at startup if it's missing
    yield


app = FastAPI(title="RSS News Briefing", lifespan=lifespan)

# in-memory cache of the latest briefing: (monotonic timestamp, result).
_latest: tuple[float, BriefingResult] | None = None
_lock = threading.Lock()


def _get_fresh_result() -> BriefingResult | None:
    latest = _latest
    if latest is None:
        return None
    saved_at, result = latest
    if time.monotonic() - saved_at < BRIEFING_TTL_MINUTES * 60:
        return result
    return None


def _to_response(result: BriefingResult, cached: bool) -> BriefingResponse:
    usage = None
    if result.usage is not None:
        usage = UsageResponse(
            input_tokens=result.usage.input_tokens,
            cached_tokens=result.usage.cached_tokens,
            output_tokens=result.usage.output_tokens,
            estimated_cost_usd=result.usage.cost,
        )
    return BriefingResponse(
        briefing=result.briefing,
        unknown_sources=result.unknown_sources,
        article_count=result.article_count,
        sources=result.sources,
        generated_at=result.generated_at,
        cached=cached,
        usage=usage,
        mode=result.mode,
        failed_summaries=result.failed_summaries,
    )


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.get("/briefing", response_model=BriefingResponse)
def get_briefing():
    global _latest

    result = _get_fresh_result()
    if result is not None:
        return _to_response(result=result, cached=True)

    with _lock:
        # Another request may have regenrated while we waited for the lock
        result = _get_fresh_result()
        if result is not None:
            return _to_response(result=result, cached=True)
        try:
            result = generate_briefing()
        except (OpenAIError, BriefingFormatError):
            log.exception("LLM request failed")
            raise HTTPException(status_code=502, detail="The summarization service failed.")
        except NoArticlesError:
            raise HTTPException(
                status_code=503, detail="The summarization service failed."
            )
        _latest = (time.monotonic(), result)

    return _to_response(result=result, cached=False)
