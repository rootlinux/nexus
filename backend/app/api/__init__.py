from fastapi import APIRouter
from app.api.routes import admin, admin_service, admin_staff, auth, bookmarks, discover, feedback, invite, invites, notifications, posts, search, users, webauthn, waitlist
from app.api import dm

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(webauthn.router, prefix="/webauthn", tags=["webauthn"])
api_router.include_router(invite.router, prefix="/invite", tags=["invite"])
api_router.include_router(invites.router)
api_router.include_router(search.router, prefix="", tags=["search"])
api_router.include_router(posts.router, prefix="/posts", tags=["posts"])
api_router.include_router(bookmarks.router, prefix="", tags=["bookmarks"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(notifications.router, prefix="", tags=["notifications"])
api_router.include_router(feedback.router)
api_router.include_router(dm.router, prefix="/dm", tags=["dm"])
api_router.include_router(admin.router, prefix="", tags=["admin"])
api_router.include_router(admin_staff.router, prefix="", tags=["admin"])
api_router.include_router(admin_service.router, prefix="", tags=["admin"])
api_router.include_router(waitlist.router, prefix="", tags=["waitlist"])
api_router.include_router(discover.router, prefix="", tags=["discover"])
