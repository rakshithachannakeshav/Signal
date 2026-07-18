"""
Pydantic schemas for the Signal Clone application.

This module defines the data validation and serialization schemas used
for API requests and responses.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# User Schemas
class UserBase(BaseModel):
    """Base schema for user data."""
    phone_or_username: str
    display_name: str
    avatar_url: Optional[str] = None
    status: Optional[str] = "offline"

class UserCreate(BaseModel):
    """Schema for creating a new user."""
    phone_or_username: str
    display_name: str
    avatar_url: Optional[str] = None

class UserLogin(BaseModel):
    """Schema for user login credentials."""
    phone_or_username: str
    otp: str

class UserResponse(UserBase):
    """Schema for returning user data in API responses."""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# Contact Schemas
class ContactCreate(BaseModel):
    """Schema for adding a new contact."""
    contact_username: str

class ContactResponse(BaseModel):
    """Schema for returning contact relationships."""
    id: int
    contact_user: UserResponse
    created_at: datetime

    class Config:
        from_attributes = True

# Message Schemas
class MessageCreate(BaseModel):
    """Schema for sending a new message."""
    content: str

class ReactionSummary(BaseModel):
    """
    Raw reactor list for one emoji on a message (not pre-aggregated per-viewer).
    Deliberately NOT `{emoji, count, reacted_by_me}` — `reacted_by_me` is
    viewer-specific, which would make WS-broadcast reaction updates (seen by
    every member at once) ambiguous about whose perspective they're from.
    Sending the raw `user_ids` list lets every client derive `count` and
    "did I react" the same way, regardless of whether the data came from a
    REST fetch or a live WS update.
    """
    emoji: str
    user_ids: List[int]

class ReplyToSummary(BaseModel):
    """Compact preview of the message being replied to, shown as a quoted block."""
    id: int
    sender_name: str
    content_snippet: str

class MessageResponse(BaseModel):
    """Schema for returning message data."""
    id: int
    conversation_id: int
    sender_id: int
    content: str
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None
    created_at: datetime
    status: str
    reactions: List[ReactionSummary] = []
    reply_to: Optional[ReplyToSummary] = None
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Conversation Schemas
class ConversationMemberResponse(BaseModel):
    """Schema for returning conversation membership details."""
    id: int
    user_id: int
    role: str
    joined_at: datetime
    last_read_message_id: Optional[int] = None
    user: UserResponse

    class Config:
        from_attributes = True

class ConversationResponse(BaseModel):
    """Schema for returning conversation details."""
    id: int
    type: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime
    last_message_at: datetime
    members: List[ConversationMemberResponse]
    last_message: Optional[MessageResponse] = None
    unread_count: Optional[int] = 0
    disappearing_seconds: Optional[int] = None

    class Config:
        from_attributes = True

class GroupCreate(BaseModel):
    """Schema for creating a new group conversation."""
    name: str
    avatar_url: Optional[str] = None
    member_ids: List[int]

class MemberAdd(BaseModel):
    """Schema for adding an existing user to a group conversation."""
    user_id: int

class DisappearingUpdate(BaseModel):
    """Schema for setting a conversation's disappearing-messages timer."""
    seconds: Optional[int] = None  # None or 0 disables it

# Token Schema
class Token(BaseModel):
    """Schema for returning JWT authentication tokens."""
    access_token: str
    token_type: str
    user: UserResponse

class TokenData(BaseModel):
    """Schema for data extracted from a JWT token."""
    phone_or_username: Optional[str] = None
