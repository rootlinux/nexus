from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class FollowRead(BaseModel):
    """Schema for reading follow data (response)."""
    id: int
    follower_id: int
    following_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FollowStatus(BaseModel):
    """Schema for follow status response."""
    following: bool
    followers_count: int = 0
    following_count: int = 0


class BlockStatus(BaseModel):
    is_blocked: bool


class AssignedInviteProfile(BaseModel):
    id: int
    code: str
    internal_note: str | None
    status: str
    expires_at: Optional[datetime] = None
    used_at: Optional[datetime] = None
    invited_user_id: Optional[int] = None
    invited_username: Optional[str] = None


class InviterProfile(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class UserProfile(BaseModel):
    """Schema for user profile with follow info."""
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None
    cover_url: str | None = None
    bio: str | None
    location: str | None = None
    website: str | None = None
    created_at: datetime
    is_following: bool = False
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    replies_count: int = 0
    reposts_count: int = 0
    is_blocked_by_me: bool = False
    has_blocked_me: bool = False
    is_access_limited: bool = False
    assigned_invite: Optional[AssignedInviteProfile] = None
    inviter: Optional[InviterProfile] = None

    model_config = ConfigDict(from_attributes=True)


class SuggestedUser(UserProfile):
    score: int
    reason: str


class SuggestionsList(BaseModel):
    users: List[SuggestedUser]


class FollowersList(BaseModel):
    """Schema for followers list."""
    users: List[UserProfile]
    total: int
    skip: int
    limit: int


class FollowingList(BaseModel):
    """Schema for following list."""
    users: List[UserProfile]
    total: int
    skip: int
    limit: int
