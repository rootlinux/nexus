from typing import Literal

from pydantic import BaseModel

from app.schemas.follow import UserProfile
from app.schemas.post import PostRead

SearchType = Literal["top", "latest", "people"]


class SearchResponse(BaseModel):
    query: str
    type: SearchType
    posts: list[PostRead]
    users: list[UserProfile]
