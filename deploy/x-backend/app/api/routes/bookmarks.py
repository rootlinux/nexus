from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.bookmark import Bookmark
from app.models.post import Post
from app.models.user import User
from app.schemas.post import FeedResponse
from app.services.blocks import filter_blocked_posts, get_blocked_user_ids
from app.services.post_views import annotate_posts_for_user, post_query_options, post_to_read_schema, visible_post_filter

router = APIRouter(tags=["bookmarks"])


@router.get("/bookmarks", response_model=FeedResponse)
async def get_bookmarks(
    cursor: Optional[int] = Query(None, description="Bookmarks cursor for pagination"),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = max(cursor or 0, 0)

    result = await db.execute(
        select(Post)
        .join(Bookmark, Bookmark.post_id == Post.id)
        .options(*post_query_options())
        .where(Bookmark.user_id == current_user.id)
        .where(visible_post_filter())
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    posts = list(result.scalars().all())
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id)
    posts = filter_blocked_posts(posts, blocked_user_ids)
    has_more = len(posts) > limit
    page_posts = posts[:limit]

    await annotate_posts_for_user(db, page_posts, current_user.id)

    return FeedResponse(
        posts=[post_to_read_schema(post, current_user.id, blocked_user_ids=blocked_user_ids) for post in page_posts],
        next_cursor=offset + limit if has_more else None,
        has_more=has_more,
    )
