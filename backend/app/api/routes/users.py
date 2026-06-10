from io import BytesIO
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status, Request
from PIL import Image, ImageOps, UnidentifiedImageError

# Prevent decompression bombs and pixel DoS from user-uploaded images
Image.MAX_IMAGE_PIXELS = 50_000_000
from pydantic import BaseModel

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_interactive_user, get_current_user, get_optional_user
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits, get_client_ip, hash_key_part
from app.core.security import get_password_hash, verify_password
from app.models.block import Block
from app.models.follow import Follow
from app.models.user import User
from app.schemas.post import PostList
from app.schemas.follow import BlockStatus, FollowStatus, FollowersList, FollowingList, SuggestionsList, UserProfile
from app.schemas.user import AvatarUploadResponse, CoverUploadResponse, PasswordChangeRequest, UserProfileUpdate
from app.models.moderation_signal import ModerationSignal, ModerationSurface, ModerationDetectionStatus, ModerationReviewStatus
from app.services.blocks import (
    filter_blocked_users,
    get_block_relationship,
    get_blocked_user_ids,
    raise_blocked_interaction_error,
    raise_blocked_profile_error,
    remove_follow_relationships_between,
)
from app.services.profile_tabs import ProfileTimelineView, get_profile_timeline
from app.services.moderation_intake import (
    assess_media_input,
    assess_text_content,
    create_moderation_signal,
    raise_blocked_content_error,
    raise_review_required_error,
)
from app.services.audit import write_audit_log
from app.services.account_security import revoke_all_password_reset_tokens_for_user
from app.services.admin_security import revoke_all_refresh_tokens_for_user
from app.services.notifications import create_follow_notification
from app.services.staff_permissions import derive_admin_response_flags
from app.services.social_graph import (
    build_suggested_users,
    build_user_profile,
    get_assigned_invite_for_user,
    get_content_counts_map,
    get_follow_counts_map,
    get_following_state_map,
)
from app.storage import get_storage_provider
from app.schemas.user import UserPrivateProfile, UserPublicProfile, UserAdminProfile

router = APIRouter(tags=["users"])

MAX_AVATAR_FILE_SIZE = 5 * 1024 * 1024
MAX_COVER_FILE_SIZE = 8 * 1024 * 1024
PROFILE_IMAGE_BACKGROUND = "#0d0e12"


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _user_search_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="user-search-burst",
            limit=5,
            window_seconds=60,
            key=build_scope_key("users", "search", "burst", user_id),
            message=RATE_LIMIT_ERROR,
        ),
        RateLimitPolicy(
            name="user-search-sustained",
            limit=20,
            window_seconds=600,
            key=build_scope_key("users", "search", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _profile_read_policies(scope_key: str, *, authenticated: bool = False) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="profile-read",
            limit=60 if authenticated else 30,
            window_seconds=60,
            key=scope_key,
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _social_graph_read_policies(scope_key: str, *, authenticated: bool = False) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="social-graph-read",
            limit=60 if authenticated else 30,
            window_seconds=60,
            key=scope_key,
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _suggestions_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="suggestions-read",
            limit=30,
            window_seconds=60,
            key=build_scope_key("suggestions", "read", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _profile_update_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="profile-update",
            limit=10,
            window_seconds=60,
            key=build_scope_key("users", "me", "profile", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _profile_image_upload_policies(user_id: int, image_type: str) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name=f"profile-{image_type}-upload",
            limit=5,
            window_seconds=60,
            key=build_scope_key("users", "me", image_type, user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _password_change_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="password-change",
            limit=5,
            window_seconds=60,
            key=build_scope_key("users", "me", "password", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _report_user_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="user-report-burst",
            limit=3,
            window_seconds=60,
            key=build_scope_key("users", "report", "burst", user_id),
            message=RATE_LIMIT_ERROR,
        ),
        RateLimitPolicy(
            name="user-report-sustained",
            limit=10,
            window_seconds=3600,
            key=build_scope_key("users", "report", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _profile_scope_key(request: Request, current_user: Optional[User], prefix: str) -> str:
    if current_user:
        return build_scope_key(prefix, "user", current_user.id)
    return build_scope_key(prefix, "ip", hash_key_part(get_client_ip(request)))


def _current_session_id(current_user: User) -> int | None:
    raw_value = getattr(current_user, "_current_session_id", None)
    if raw_value is None:
        return None
    return int(raw_value)


def _follow_toggle_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="follow-toggle-burst",
            limit=8,
            window_seconds=60,
            key=build_scope_key("follow", "toggle", "burst", user_id),
            message=RATE_LIMIT_ERROR,
        ),
        RateLimitPolicy(
            name="follow-toggle-sustained",
            limit=30,
            window_seconds=3600,
            key=build_scope_key("follow", "toggle", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


class UserSearchResult(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class UserSearchResponse(BaseModel):
    users: List[UserSearchResult]


@router.get("/search", response_model=UserSearchResponse)
async def search_users(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Search users by username or display name.
    
    - Case-insensitive partial match
    - Excludes current user from results
    - Returns max 10 results
    - Requires authentication
    """
    await enforce_rate_limits(request, _user_search_policies(current_user.id))

    # Search users by username (case-insensitive, partial match)
    # Exclude current user
    search_pattern = f"%{_escape_like_pattern(q.strip())}%"
    result = await db.execute(
        select(User)
        .where(User.id != current_user.id)
        .where(
            or_(
                User.username.ilike(search_pattern, escape="\\"),
                User.display_name.ilike(search_pattern, escape="\\"),
            )
        )
        .limit(10)
    )
    users = result.scalars().all()
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id)
    users = filter_blocked_users(users, blocked_user_ids)
    
    return UserSearchResponse(
        users=[
            UserSearchResult(
                id=u.id,
                username=u.username,
                display_name=u.display_name,
                avatar_url=u.avatar_url,
            )
            for u in users
        ]
    )


async def get_user_profile(
    db: AsyncSession,
    username: str,
    current_user_id: Optional[int] = None
) -> Optional[UserProfile]:
    """Helper function to get user profile with follow info."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.inviter))
        .where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        return None

    block_relationship = await get_block_relationship(
        db,
        current_user_id=current_user_id,
        target_user_id=user.id,
    )
    if block_relationship.has_blocked_me:
        return None

    follow_counts_map = await get_follow_counts_map(db, [user.id])
    content_counts_map = await get_content_counts_map(db, [user.id])
    following_state_map = await get_following_state_map(db, current_user_id, [user.id])
    assigned_invite = None if block_relationship.blocked_by_me else await get_assigned_invite_for_user(db, user, current_user_id)

    return build_user_profile(
        user,
        is_following=False if block_relationship.is_blocked else following_state_map.get(user.id, False),
        is_blocked_by_me=block_relationship.blocked_by_me,
        has_blocked_me=block_relationship.has_blocked_me,
        is_access_limited=block_relationship.blocked_by_me,
        follow_counts={} if block_relationship.blocked_by_me else follow_counts_map.get(user.id),
        content_counts={} if block_relationship.blocked_by_me else content_counts_map.get(user.id),
        assigned_invite=assigned_invite,
    )


async def _read_uploaded_image(file: UploadFile) -> bytes:
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded file",
        ) from exc

    return content


def _image_has_transparency(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        alpha = image.getchannel("A")
        minimum_alpha, maximum_alpha = alpha.getextrema()
        return minimum_alpha < 255 or maximum_alpha < 255

    if image.mode == "P":
        transparency = image.info.get("transparency")
        if transparency is None:
            return False
        if isinstance(transparency, bytes):
            return any(alpha < 255 for alpha in transparency)
        if isinstance(transparency, int):
            return transparency in image.getdata()

    return False


def _normalize_profile_image_upload(content: bytes) -> bytes:
    try:
        with Image.open(BytesIO(content)) as uploaded_image:
            image = ImageOps.exif_transpose(uploaded_image)

            if _image_has_transparency(image):
                background = Image.new("RGBA", image.size, PROFILE_IMAGE_BACKGROUND)
                image = Image.alpha_composite(background, image.convert("RGBA"))

            rgb_image = image.convert("RGB")
            output = BytesIO()
            rgb_image.save(output, format="JPEG", quality=91, optimize=True)
            return output.getvalue()
    except (Image.DecompressionBombError, ValueError) as exc:
        # Covers decompression bombs and excessive pixel dimensions (MAX_IMAGE_PIXELS)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image dimensions too large",
        ) from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to process uploaded file",
        ) from exc

@router.patch("/me/profile", response_model=UserProfile)
async def update_my_profile(
    request: Request,
    profile_update: UserProfileUpdate,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _profile_update_policies(current_user.id))
    assessments = []
    if "display_name" in profile_update.model_fields_set:
        assessments.append(
            assess_text_content(ModerationSurface.PROFILE_DISPLAY_NAME, profile_update.display_name)
        )
    if "bio" in profile_update.model_fields_set:
        assessments.append(
            assess_text_content(ModerationSurface.PROFILE_BIO, profile_update.bio)
        )

    for assessment in assessments:
        await create_moderation_signal(db, user_id=current_user.id, assessment=assessment)
        if assessment.is_blocked:
            await db.commit()
            raise_blocked_content_error(assessment.surface_type)

    if "display_name" in profile_update.model_fields_set:
        current_user.display_name = profile_update.display_name
    if "bio" in profile_update.model_fields_set:
        current_user.bio = profile_update.bio
    if "location" in profile_update.model_fields_set:
        current_user.location = profile_update.location
    if "website" in profile_update.model_fields_set:
        current_user.website = profile_update.website
    await db.commit()
    await db.refresh(current_user)
    profile = await get_user_profile(db, current_user.username, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return profile


@router.post("/me/avatar", response_model=AvatarUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_my_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _profile_image_upload_policies(current_user.id, "avatar"))
    content = await _read_uploaded_image(file)
    assessment = assess_media_input(
        ModerationSurface.PROFILE_AVATAR,
        content_type=file.content_type,
        original_filename=file.filename,
        content=content,
        content_size=len(content),
        max_size=MAX_AVATAR_FILE_SIZE,
    )
    signal = await create_moderation_signal(db, user_id=current_user.id, assessment=assessment)
    if assessment.is_blocked:
        await db.commit()
        raise_blocked_content_error(assessment.surface_type)
    if assessment.requires_review:
        await db.commit()
        raise_review_required_error(assessment.surface_type)

    storage_provider = get_storage_provider()
    normalized_content = _normalize_profile_image_upload(content)

    try:
        stored_media = await storage_provider.save_file(
            content=normalized_content,
            content_type="image/jpeg",
            original_filename=file.filename,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file",
        ) from exc

    signal.media_url = stored_media.public_url
    current_user.avatar_url = stored_media.public_url
    await db.commit()
    await db.refresh(current_user)
    return AvatarUploadResponse(avatar_url=stored_media.public_url)


@router.post("/me/cover", response_model=CoverUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_my_cover(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _profile_image_upload_policies(current_user.id, "cover"))
    content = await _read_uploaded_image(file)
    assessment = assess_media_input(
        ModerationSurface.PROFILE_COVER,
        content_type=file.content_type,
        original_filename=file.filename,
        content=content,
        content_size=len(content),
        max_size=MAX_COVER_FILE_SIZE,
    )
    signal = await create_moderation_signal(db, user_id=current_user.id, assessment=assessment)
    if assessment.is_blocked:
        await db.commit()
        raise_blocked_content_error(assessment.surface_type)
    if assessment.requires_review:
        await db.commit()
        raise_review_required_error(assessment.surface_type)

    storage_provider = get_storage_provider()
    normalized_content = _normalize_profile_image_upload(content)

    try:
        stored_media = await storage_provider.save_file(
            content=normalized_content,
            content_type="image/jpeg",
            original_filename=file.filename,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file",
        ) from exc

    signal.media_url = stored_media.public_url
    current_user.cover_url = stored_media.public_url
    await db.commit()
    await db.refresh(current_user)
    return CoverUploadResponse(cover_url=stored_media.public_url)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    request: Request,
    password_change: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _password_change_policies(current_user.id))
    current_session_id = _current_session_id(current_user)
    if not verify_password(password_change.current_password, current_user.password_hash):
        await write_audit_log(
            db,
            action="password.change_denied",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"reason": "step_up_password_invalid"},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if verify_password(password_change.new_password, current_user.password_hash):
        await write_audit_log(
            db,
            action="password.change_denied",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"reason": "password_reuse"},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password",
        )

    must_change_password_before = bool(current_user.must_change_password)
    current_user.password_hash = get_password_hash(password_change.new_password)
    current_user.must_change_password = False
    revoked_public_reset_tokens, revoked_admin_reset_tokens = await revoke_all_password_reset_tokens_for_user(
        db,
        current_user.id,
    )
    revoked_sessions = await revoke_all_refresh_tokens_for_user(db, current_user.id)
    await write_audit_log(
        db,
        action="password.change",
        actor_user=current_user,
        target_type="user",
        target_id=current_user.id,
        before={"must_change_password": must_change_password_before},
        after={
            "must_change_password": False,
            "revoked_public_reset_tokens": revoked_public_reset_tokens,
            "revoked_admin_reset_tokens": revoked_admin_reset_tokens,
            "revoked_session_count": revoked_sessions,
        },
        request=request,
        session_id=current_session_id,
        success=True,
    )
    await db.commit()


@router.get("/suggestions", response_model=SuggestionsList)
async def get_follow_suggestions(
    request: Request,
    limit: int = Query(5, ge=1, le=20),
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _suggestions_policies(current_user.id))
    users = await build_suggested_users(db, current_user, limit)
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id)
    return SuggestionsList(users=list(filter_blocked_users(users, blocked_user_ids)))


@router.get("/{username}", response_model=UserPublicProfile | UserPrivateProfile)
async def get_user_profile_endpoint(
    request: Request,
    username: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get user profile by username.

    - Returns user profile with follow information
    - Shows if current user is following this user
    """
    await enforce_rate_limits(request, _profile_read_policies(_profile_scope_key(request, current_user, "profile:view"), authenticated=current_user is not None))
    current_user_id = current_user.id if current_user else None
    profile = await get_user_profile(db, username, current_user_id)
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if current_user is None:
        return UserPublicProfile.model_validate(profile.model_dump())

    if current_user.id != profile.id and current_user.staff_permission is None:
        return UserPublicProfile.model_validate(profile.model_dump())

    user_result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == profile.id)
    )
    target_user = user_result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    is_admin, admin_role = derive_admin_response_flags(target_user)
    
    if is_admin and target_user.staff_permission is not None:
        # Admin users get full moderation details
        return UserAdminProfile.model_validate(
            {
                **profile.model_dump(),
                "is_admin": is_admin,
                "admin_role": admin_role,
                "status": target_user.status,
                "banned_at": target_user.banned_at,
                "ban_reason": target_user.ban_reason,
                "status_reason": target_user.status_reason,
                "status_changed_at": target_user.status_changed_at,
                "status_changed_by_user_id": target_user.status_changed_by_user_id,
            }
        )
    
    # Account owner or non-admin staff get UserPrivateProfile (no moderation fields)
    return UserPrivateProfile.model_validate(
        {
            **profile.model_dump(),
            "is_admin": is_admin,
            "admin_role": admin_role,
            "status": target_user.status,
        }
    )


@router.get("/{username}/posts", response_model=PostList)
async def get_user_posts(
    request: Request,
    username: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    view: ProfileTimelineView = Query("posts", pattern="^(posts|replies|media|likes|reposts)$"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get posts by username.

    - Returns paginated list of user's posts
    - Sorted by created_at (newest first)
    """
    await enforce_rate_limits(request, _profile_read_policies(_profile_scope_key(request, current_user, "profile:posts"), authenticated=current_user is not None))
    # Find user
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    block_relationship = await get_block_relationship(
        db,
        current_user_id=current_user.id if current_user else None,
        target_user_id=user.id,
    )
    if block_relationship.is_blocked:
        raise_blocked_profile_error()
    
    current_user_id = current_user.id if current_user else None
    timeline = await get_profile_timeline(
        db,
        user=user,
        view=view,
        skip=skip,
        limit=limit,
        current_user_id=current_user_id,
    )
    return PostList(**timeline)


@router.post("/{username}/follow", response_model=FollowStatus)
async def toggle_follow(
    request: Request,
    username: str,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggle follow on a user.
    
    - Requires authentication
    - If already following, unfollows the user
    - If not following, follows the user
    - Returns current follow status
    """
    await enforce_rate_limits(request, _follow_toggle_policies(current_user.id))

    # Find target user
    result = await db.execute(
        select(User).where(User.username == username)
    )
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Cannot follow yourself
    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot follow yourself"
        )

    if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=target_user.id)).is_blocked:
        raise_blocked_interaction_error()
    
    # Check if already following
    follow_result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == target_user.id
        )
    )
    existing_follow = follow_result.scalar_one_or_none()
    
    if existing_follow:
        # Unfollow
        await db.delete(existing_follow)
        following = False
    else:
        # Follow
        new_follow = Follow(
            follower_id=current_user.id,
            following_id=target_user.id
        )
        db.add(new_follow)
        await db.flush()
        await create_follow_notification(db, actor_user_id=current_user.id, target_user_id=target_user.id)
        following = True
    
    await db.commit()
    
    follow_counts_map = await get_follow_counts_map(db, [target_user.id])
    target_counts = follow_counts_map.get(target_user.id, {})
    
    return FollowStatus(
        following=following,
        followers_count=int(target_counts.get("followers_count", 0)),
        following_count=int(target_counts.get("following_count", 0)),
    )


@router.get("/{username}/followers", response_model=FollowersList)
async def get_user_followers(
    request: Request,
    username: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get followers of a user.

    - Returns paginated list of followers
    - Sorted by follow created_at (newest first)
    """
    await enforce_rate_limits(request, _social_graph_read_policies(_profile_scope_key(request, current_user, "graph:followers"), authenticated=current_user is not None))
    # Find user
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if (await get_block_relationship(db, current_user_id=current_user.id if current_user else None, target_user_id=user.id)).is_blocked:
        raise_blocked_profile_error()
    
    # Get followers count
    count_result = await db.execute(
        select(func.count())
        .select_from(Follow)
        .where(Follow.following_id == user.id)
    )
    total = count_result.scalar()
    
    # Get followers with user details
    result = await db.execute(
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.following_id == user.id)
        .order_by(Follow.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    followers = result.scalars().all()
    
    current_user_id = current_user.id if current_user else None
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    followers = filter_blocked_users(followers, blocked_user_ids)
    follower_ids = [follower.id for follower in followers]
    follow_counts_map = await get_follow_counts_map(db, follower_ids)
    content_counts_map = await get_content_counts_map(db, follower_ids)
    following_state_map = await get_following_state_map(db, current_user_id, follower_ids)

    profiles = [
        build_user_profile(
            follower,
            is_following=following_state_map.get(follower.id, False),
            follow_counts=follow_counts_map.get(follower.id),
            content_counts=content_counts_map.get(follower.id),
        )
        for follower in followers
    ]

    return FollowersList(users=profiles, total=int(total or 0), skip=skip, limit=limit)


@router.get("/{username}/following", response_model=FollowingList)
async def get_user_following(
    request: Request,
    username: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get users that a user is following.

    - Returns paginated list of following
    - Sorted by follow created_at (newest first)
    """
    await enforce_rate_limits(request, _social_graph_read_policies(_profile_scope_key(request, current_user, "graph:following"), authenticated=current_user is not None))
    # Find user
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if (await get_block_relationship(db, current_user_id=current_user.id if current_user else None, target_user_id=user.id)).is_blocked:
        raise_blocked_profile_error()
    
    # Get following count
    count_result = await db.execute(
        select(func.count())
        .select_from(Follow)
        .where(Follow.follower_id == user.id)
    )
    total = count_result.scalar()
    
    # Get following with user details
    result = await db.execute(
        select(User)
        .join(Follow, Follow.following_id == User.id)
        .where(Follow.follower_id == user.id)
        .order_by(Follow.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    following = result.scalars().all()
    
    current_user_id = current_user.id if current_user else None
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    following = filter_blocked_users(following, blocked_user_ids)
    following_ids = [followed.id for followed in following]
    follow_counts_map = await get_follow_counts_map(db, following_ids)
    content_counts_map = await get_content_counts_map(db, following_ids)
    following_state_map = await get_following_state_map(db, current_user_id, following_ids)

    profiles = [
        build_user_profile(
            followed,
            is_following=following_state_map.get(followed.id, False),
            follow_counts=follow_counts_map.get(followed.id),
            content_counts=content_counts_map.get(followed.id),
        )
        for followed in following
    ]

    return FollowingList(users=profiles, total=int(total or 0), skip=skip, limit=limit)


@router.post("/{username}/block", response_model=BlockStatus)
async def toggle_block(
    username: str,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == username))
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target_user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot block yourself")

    existing_result = await db.execute(
        select(Block).where(Block.blocker_id == current_user.id, Block.blocked_id == target_user.id)
    )
    existing_block = existing_result.scalar_one_or_none()

    if existing_block:
        await db.delete(existing_block)
        is_blocked = False
    else:
        db.add(Block(blocker_id=current_user.id, blocked_id=target_user.id))
        await remove_follow_relationships_between(db, current_user.id, target_user.id)
        is_blocked = True

    await db.commit()
    return BlockStatus(is_blocked=is_blocked)


class UserReportRequest(BaseModel):
    reason: str | None = None


@router.post("/{username}/report", status_code=status.HTTP_200_OK)
async def report_user(
    request: Request,
    username: str,
    report: UserReportRequest,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Report a user profile.

    - Authenticated users only
    - Creates a ModerationSignal with source='user_report', surface_type='USER_PROFILE'
    - Returns 200 if already reported (idempotent)
    - Rate limited to 10 reports per hour per user
    - Cannot report yourself
    """
    await enforce_rate_limits(request, _report_user_policies(current_user.id))

    result = await db.execute(select(User).where(User.username == username))
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target_user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot report yourself")

    existing_result = await db.execute(
        select(ModerationSignal).where(
            ModerationSignal.user_id == target_user.id,
            ModerationSignal.actor_user_id == current_user.id,
            ModerationSignal.surface_type == ModerationSurface.USER_PROFILE,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return {"message": "Report already submitted"}

    signal = ModerationSignal(
        user_id=target_user.id,
        actor_user_id=current_user.id,
        surface_type=ModerationSurface.USER_PROFILE,
        detection_status=ModerationDetectionStatus.SUSPICIOUS,
        review_status=ModerationReviewStatus.OPEN,
        reason_codes=[report.reason] if report.reason else [],
        reason_summary=report.reason or "Kullanıcı rapor edildi.",
        risk_score=40,
        content_preview=f"@{current_user.username} kullanıcısı @{target_user.username} profilini raporladı.",
    )
    db.add(signal)
    await db.commit()

    return {"message": "Report submitted"}
