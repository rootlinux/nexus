from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.post import PostModerationStatus
from app.schemas.user import UserPublicRead


class PostBase(BaseModel):
    """Base post schema with common fields."""
    content: str = Field(default="", max_length=280)
    media_url: Optional[str] = None
    
    @field_validator('content', mode='before')
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Strip whitespace while allowing media-only or repost payloads."""
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ValueError('Content must be a string')
        v = v.strip()
        if len(v) > 280:
            raise ValueError('Content cannot exceed 280 characters')
        return v


class PostCreate(PostBase):
    """Schema for creating a new post."""
    parent_id: Optional[int] = None
    repost_of_id: Optional[int] = None
    quoted_post_id: Optional[int] = None


class PostRead(BaseModel):
    """Schema for reading post data (response)."""
    content: str
    media_url: Optional[str] = None
    id: int
    user_id: int
    parent_id: Optional[int] = None
    repost_of_id: Optional[int] = None
    quoted_post_id: Optional[int] = None
    is_repost: bool
    is_quote: bool = False
    likes_count: int
    replies_count: int
    reposts_count: int
    created_at: datetime
    is_liked_by_me: bool = False
    is_bookmarked: bool = False
    is_bookmarked_by_me: bool = False
    has_reposted: bool = False
    moderation_status: PostModerationStatus = PostModerationStatus.VISIBLE
    moderation_reason: Optional[str] = None
    moderated_at: Optional[datetime] = None
    moderated_by_user_id: Optional[int] = None
    feed_reason: Optional[str] = None
    author: "UserPublicRead"
    original_post: Optional["PostRead"] = None
    parent_post: Optional["PostRead"] = None
    quoted_post: Optional["PostRead"] = None
    quoted_post_unavailable: bool = False
    quoted_post_placeholder: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PostList(BaseModel):
    """Schema for listing posts."""
    posts: List[PostRead]
    total: int
    page: int
    limit: int
    has_more: bool


class FeedResponse(BaseModel):
    """Schema for cursor-based feed response."""
    posts: List[PostRead]
    next_cursor: Optional[int] = None
    has_more: bool


class LikeResponse(BaseModel):
    """Schema for like toggle response."""
    liked: bool
    likes_count: int


class RepostResponse(BaseModel):
    """Schema for repost response."""
    reposted: bool
    reposts_count: int


class BookmarkResponse(BaseModel):
    """Schema for bookmark toggle response."""
    post_id: int
    is_bookmarked: bool


class TrendingPost(BaseModel):
    """Schema for a trending post entry."""
    score: int
    post: PostRead


class DiscoveryAuthorSummary(BaseModel):
    """Compact author metadata for discovery surfaces."""
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class DiscoveryEngagement(BaseModel):
    """Engagement counts exposed on discovery surfaces."""
    likes: int
    replies: int
    reposts: int


class DiscoveryPostEntry(BaseModel):
    """Structured discovery item used by Explore and trending widgets."""
    rank: int
    score: int
    post_id: int
    created_at: datetime
    author: DiscoveryAuthorSummary
    content_preview: str
    has_media: bool
    media_url: Optional[str] = None
    engagement: DiscoveryEngagement
    category_label: Optional[str] = None
    discovery_reason: Optional[str] = None
    post: PostRead


class DiscoveryFeedResponse(BaseModel):
    """Response schema for Explore feeds."""
    mode: Literal["for_you", "trending"]
    window_hours: int
    items: List[DiscoveryPostEntry]


class DiscoverPostsResponse(BaseModel):
    """Paginated response for GET /api/discover/posts."""
    posts: List[PostRead]
    total: int
    limit: int
    offset: int
    has_more: bool


class ReplyCreate(BaseModel):
    """Schema for creating a reply."""
    content: str = Field(..., min_length=1, max_length=280)
    
    @field_validator('content', mode='before')
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Strip whitespace and reject empty content."""
        if not isinstance(v, str):
            raise ValueError('Content must be a string')
        v = v.strip()
        if not v:
            raise ValueError('Content cannot be empty or whitespace only')
        if len(v) > 280:
            raise ValueError('Content cannot exceed 280 characters')
        return v


class ReplyResponse(BaseModel):
    """Schema for reply response."""
    reply: PostRead
    replies_count: int


# Rebuild PostRead model to resolve forward references
PostRead.model_rebuild()
