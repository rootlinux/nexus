from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits
from app.models.user import User
from app.schemas.search import SearchResponse, SearchType
from app.services.search import perform_search

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search(
    request: Request,
    q: str = Query("", description="Search query"),
    type: SearchType = Query("top", description="Search mode"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(
        request,
        [
            RateLimitPolicy(
                name="search-global-burst",
                limit=20,
                window_seconds=60,
                key=build_scope_key("search", "global", "burst", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
            RateLimitPolicy(
                name="search-global-sustained",
                limit=80,
                window_seconds=600,
                key=build_scope_key("search", "global", "sustained", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
        ],
    )
    return await perform_search(
        db,
        query=q,
        search_type=type,
        current_user_id=current_user.id,
    )
