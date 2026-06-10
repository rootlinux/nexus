from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limit import (
    RATE_LIMIT_ERROR,
    RateLimitPolicy,
    build_scope_key,
    enforce_rate_limits,
)
from app.models.user import User
from app.schemas.follow import DiscoverUsersResponse
from app.schemas.post import DiscoverPostsResponse
from app.services.discovery import build_discover_posts, build_discover_users

router = APIRouter(prefix="/discover", tags=["discover"])

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20


@router.get("/users", response_model=DiscoverUsersResponse)
async def discover_users(
    request: Request,
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Number of results to return"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoverUsersResponse:
    """Return ranked user suggestions for the Discover page.

    Score formula: (mutual_count × 3) + (is_new × 2) + (recent_activity × 1)

    Excludes users already followed by the current user, the user themselves,
    and non-ACTIVE accounts.
    """
    await enforce_rate_limits(
        request,
        [
            RateLimitPolicy(
                name="discover-users-burst",
                limit=30,
                window_seconds=60,
                key=build_scope_key("discover", "users", "burst", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
            RateLimitPolicy(
                name="discover-users-sustained",
                limit=120,
                window_seconds=600,
                key=build_scope_key("discover", "users", "sustained", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
        ],
    )
    return await build_discover_users(
        db,
        current_user_id=current_user.id,
        limit=limit,
        offset=offset,
    )


@router.get("/posts", response_model=DiscoverPostsResponse)
async def discover_posts(
    request: Request,
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Number of results to return"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoverPostsResponse:
    """Return trending top-level posts from the last 7 days for the Discover page.

    Sorted by (likes_count + replies_count) DESC. Replies and hidden/deleted
    posts are excluded.
    """
    await enforce_rate_limits(
        request,
        [
            RateLimitPolicy(
                name="discover-posts-burst",
                limit=30,
                window_seconds=60,
                key=build_scope_key("discover", "posts", "burst", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
            RateLimitPolicy(
                name="discover-posts-sustained",
                limit=120,
                window_seconds=600,
                key=build_scope_key("discover", "posts", "sustained", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
        ],
    )
    return await build_discover_posts(
        db,
        current_user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
