from __future__ import annotations

from enum import Enum


class AdminRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    INVITE_ADMIN = "invite_admin"
    MODERATOR = "moderator"
    SUPPORT_ADMIN = "support_admin"


class Capability:
    USER_READ = "user.read"
    USER_MODERATE = "user.moderate"
    USER_READ_BASIC = "user.read_basic"
    USER_READ_SENSITIVE_MASKED = "user.read_sensitive_masked"
    INVITE_READ = "invite.read"
    INVITE_MANAGE = "invite.manage"
    INVITE_CREATE = "invite.create"
    INVITE_ASSIGN = "invite.assign"
    INVITE_REVEAL_FULL = "invite.reveal_full"
    INVITE_REVOKE = "invite.revoke"
    MODERATION_SUSPEND = "moderation.suspend"
    MODERATION_BAN = "moderation.ban"
    MODERATION_FREEZE = "moderation.freeze"
    MODERATION_USER_READ = "moderation.user_read"
    MODERATION_POST_READ = "moderation.post_read"
    MODERATION_POST_HIDE = "moderation.post_hide"
    MODERATION_POST_UNHIDE = "moderation.post_unhide"
    MODERATION_POST_DELETE = "moderation.post_delete"
    MODERATION_SIGNAL_READ = "moderation.signal_read"
    MODERATION_SIGNAL_RESOLVE = "moderation.signal_resolve"
    ROLE_CHANGE = "role.change"
    AUDIT_READ = "audit.read"
    WAITLIST_READ = "waitlist.read"
    WAITLIST_MANAGE = "waitlist.manage"
def user_has_capability(user, capability: str) -> bool:
    from app.services.staff_permissions import staff_has_capability

    return staff_has_capability(user, capability)
