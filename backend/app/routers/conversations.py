"""
Conversations router module.
Handles endpoints for listing conversations, creating direct chats, and creating group chats.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional
from datetime import datetime
from backend.app.core.db import get_db
from backend.app.core.security import get_current_user
from backend.app.core.connection_manager import manager
from backend.app.models import User, Conversation, ConversationMember, Message
from backend.app.schemas import ConversationResponse, GroupCreate, MemberAdd, DisappearingUpdate
from backend.app.routers.messages import _serialize_message

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _serialize_conversation(
    db: Session,
    conv: Conversation,
    current_user: User,
    members: Optional[List[ConversationMember]] = None,
    last_message: Optional[Message] = None,
    unread_count: int = 0,
) -> dict:
    """
    Build the API response dict for a single conversation.

    Direct conversations have no stored name/avatar of their own (unlike
    groups), so for `type == "direct"` this resolves the display name/avatar
    from the *other* participant's profile. A membership with no other
    participant (self-chat) falls back to "Notes to Self". Used by every
    endpoint in this router so the name/avatar-resolution logic lives in
    exactly one place.
    """
    if members is None:
        members = db.query(ConversationMember).filter(ConversationMember.conversation_id == conv.id).all()
    if last_message is None:
        last_message = db.query(Message).filter(Message.conversation_id == conv.id).order_by(desc(Message.created_at)).first()
    last_message_dict = _serialize_message(db, last_message) if last_message else None

    conv_name = conv.name
    conv_avatar = conv.avatar_url
    if conv.type == "direct":
        other_member = next((m for m in members if m.user_id != current_user.id), None)
        if other_member:
            conv_name = other_member.user.display_name
            conv_avatar = other_member.user.avatar_url
        else:
            conv_name = "Notes to Self"
            conv_avatar = current_user.avatar_url

    return {
        "id": conv.id,
        "type": conv.type,
        "name": conv_name,
        "avatar_url": conv_avatar,
        "created_at": conv.created_at,
        "last_message_at": conv.last_message_at,
        "members": members,
        "last_message": last_message_dict,
        "unread_count": unread_count,
        "disappearing_seconds": conv.disappearing_seconds,
    }


def _require_admin(db: Session, conversation_id: int, user_id: int) -> ConversationMember:
    """
    Fetch the caller's membership row for a conversation and raise 403 if
    they are not an admin. Gates the group-management endpoints below so
    only admins can add/remove other members.
    """
    membership = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id
    ).first()
    if not membership or membership.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only group admins can do this")
    return membership

@router.get("", response_model=List[ConversationResponse])
def list_conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    List all conversations the current user is a part of.
    Calculates unread message counts and formats direct conversation names dynamically.
    
    Args:
        current_user: The authenticated user.
        db: Database session.
        
    Returns:
        A list of conversation objects with metadata like unread counts and last messages.
    """
    # Find all conversations current user is a member of
    memberships = db.query(ConversationMember).filter(ConversationMember.user_id == current_user.id).all()
    conversation_ids = [m.conversation_id for m in memberships]
    
    # Fetch conversation details ordered by the most recent activity
    conversations = db.query(Conversation).filter(
        Conversation.id.in_(conversation_ids)
    ).order_by(desc(Conversation.last_message_at)).all()
    
    response_list = []
    for conv in conversations:
        # Get all members of the conversation
        members = db.query(ConversationMember).filter(ConversationMember.conversation_id == conv.id).all()

        # Get the latest message for preview purposes
        last_msg = db.query(Message).filter(Message.conversation_id == conv.id).order_by(desc(Message.created_at)).first()

        # Find current user's membership to calculate unread messages
        user_membership = next((m for m in members if m.user_id == current_user.id), None)
        unread_count = 0
        if user_membership:
            if user_membership.last_read_message_id:
                # Count messages newer than the last read message
                unread_count = db.query(func.count(Message.id)).filter(
                    Message.conversation_id == conv.id,
                    Message.id > user_membership.last_read_message_id
                ).scalar() or 0
            else:
                # Count all messages in this conversation if none have been read
                unread_count = db.query(func.count(Message.id)).filter(
                    Message.conversation_id == conv.id
                ).scalar() or 0

        response_list.append(_serialize_conversation(
            db, conv, current_user, members=members, last_message=last_msg, unread_count=unread_count
        ))

    return response_list

@router.post("/direct", response_model=ConversationResponse)
def get_or_create_direct(other_user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get an existing direct conversation with another user or create a new one.
    
    Args:
        other_user_id: The ID of the user to chat with.
        current_user: The authenticated user.
        db: Database session.
        
    Returns:
        The direct conversation details.
    """
    # Check if direct conversation already exists between current_user and other_user_id
    if other_user_id == current_user.id:
        # Notes to self: handled normally below by adding only one member
        pass
        
    # Query conversations of type "direct" that have exactly these two users (or one if self)
    subquery = db.query(ConversationMember.conversation_id).filter(
        ConversationMember.user_id.in_([current_user.id, other_user_id])
    ).group_by(ConversationMember.conversation_id).having(func.count(ConversationMember.user_id) == (2 if other_user_id != current_user.id else 1)).all()
    
    existing_conv_ids = [r[0] for r in subquery]
    
    direct_conv = db.query(Conversation).filter(
        Conversation.id.in_(existing_conv_ids),
        Conversation.type == "direct"
    ).first()
    
    if direct_conv:
        # Conversation exists; fetch members and return
        members = db.query(ConversationMember).filter(ConversationMember.conversation_id == direct_conv.id).all()
        last_msg = db.query(Message).filter(Message.conversation_id == direct_conv.id).order_by(desc(Message.created_at)).first()
        return _serialize_conversation(db, direct_conv, current_user, members=members, last_message=last_msg, unread_count=0)

    # Create new conversation since one does not exist
    new_conv = Conversation(type="direct")
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)
    
    # Add participants to the new conversation
    member1 = ConversationMember(conversation_id=new_conv.id, user_id=current_user.id, role="member")
    db.add(member1)
    if other_user_id != current_user.id:
        member2 = ConversationMember(conversation_id=new_conv.id, user_id=other_user_id, role="member")
        db.add(member2)
    db.commit()
    
    members = db.query(ConversationMember).filter(ConversationMember.conversation_id == new_conv.id).all()
    return _serialize_conversation(db, new_conv, current_user, members=members, last_message=None, unread_count=0)

@router.post("/group", response_model=ConversationResponse)
def create_group(group_in: GroupCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Create a new group conversation with the specified members.
    
    Args:
        group_in: Group creation payload containing name and member IDs.
        current_user: The authenticated user who will become the group admin.
        db: Database session.
        
    Returns:
        The newly created group conversation.
    """
    # Create group conversation with a default avatar if none provided
    avatar = group_in.avatar_url or f"https://api.dicebear.com/7.x/identicon/svg?seed={group_in.name}"
    new_conv = Conversation(
        type="group",
        name=group_in.name,
        avatar_url=avatar
    )
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)
    
    # Add the user who created the group as an admin
    creator_member = ConversationMember(
        conversation_id=new_conv.id,
        user_id=current_user.id,
        role="admin"
    )
    db.add(creator_member)
    
    # Add other requested members to the group (avoiding double-adding the creator)
    for m_id in set(group_in.member_ids):
        if m_id != current_user.id:
            member = ConversationMember(
                conversation_id=new_conv.id,
                user_id=m_id,
                role="member"
            )
            db.add(member)
            
    db.commit()

    members = db.query(ConversationMember).filter(ConversationMember.conversation_id == new_conv.id).all()
    return _serialize_conversation(db, new_conv, current_user, members=members, last_message=None, unread_count=0)


@router.post("/{conversation_id}/members", response_model=ConversationResponse)
async def add_member(
    conversation_id: int,
    member_in: MemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Add a new member to a group conversation. Admin-only.

    Broadcasts a `member_added` event over WebSocket to every current member
    (including the newly added one) so open clients update their member list
    live instead of requiring a manual refetch.
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conv.type != "group":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot add members to a direct conversation")

    _require_admin(db, conversation_id, current_user.id)

    new_user = db.query(User).filter(User.id == member_in.user_id).first()
    if not new_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == new_user.id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already a member")

    db.add(ConversationMember(conversation_id=conversation_id, user_id=new_user.id, role="member"))
    db.commit()

    members = db.query(ConversationMember).filter(ConversationMember.conversation_id == conversation_id).all()
    member_ids = [m.user_id for m in members]

    await manager.broadcast_to_conversation(conversation_id, {
        "event": "member_added",
        "conversation_id": conversation_id,
        "user": {"id": new_user.id, "display_name": new_user.display_name, "avatar_url": new_user.avatar_url},
    }, member_ids)

    return _serialize_conversation(db, conv, current_user, members=members, last_message=None, unread_count=0)


@router.delete("/{conversation_id}/members/{user_id}", response_model=ConversationResponse)
async def remove_member(
    conversation_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Remove a member from a group conversation.

    Allowed for a group admin removing anyone, or a member removing
    themselves (leaving the group). If the removed member was the group's
    only admin and other members remain, the earliest-joined remaining
    member is promoted to admin — the assignment doc doesn't specify this
    edge case, but leaving a group with no admin at all would make it
    unmanageable, so this keeps every non-empty group admin'd.
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conv.type != "group":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove members from a direct conversation")

    is_self_leave = user_id == current_user.id
    if not is_self_leave:
        _require_admin(db, conversation_id, current_user.id)

    target_membership = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id
    ).first()
    if not target_membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User is not a member of this group")

    was_admin = target_membership.role == "admin"
    notify_ids = [m.user_id for m in db.query(ConversationMember).filter(ConversationMember.conversation_id == conversation_id).all()]

    db.delete(target_membership)
    db.commit()

    remaining = db.query(ConversationMember).filter(ConversationMember.conversation_id == conversation_id).all()
    if was_admin and remaining and not any(m.role == "admin" for m in remaining):
        promoted = sorted(remaining, key=lambda m: m.joined_at)[0]
        promoted.role = "admin"
        db.commit()
        remaining = db.query(ConversationMember).filter(ConversationMember.conversation_id == conversation_id).all()

    await manager.broadcast_to_conversation(conversation_id, {
        "event": "member_removed",
        "conversation_id": conversation_id,
        "user_id": user_id,
    }, notify_ids)

    return _serialize_conversation(db, conv, current_user, members=remaining, last_message=None, unread_count=0)


@router.patch("/{conversation_id}/disappearing", response_model=ConversationResponse)
async def set_disappearing_timer(
    conversation_id: int,
    update: DisappearingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enable, change, or disable disappearing messages for a conversation.

    Any current member may change this (matches Signal's own behavior for
    direct chats and small groups — it's a shared conversation setting, not
    an admin-only control like membership). New messages sent after this is
    set get an `expires_at` stamp in ws.py; a background sweep (main.py)
    deletes them once it passes and notifies members over WebSocket.
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    membership = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this conversation")

    seconds = update.seconds if update.seconds and update.seconds > 0 else None
    conv.disappearing_seconds = seconds
    db.commit()

    members = db.query(ConversationMember).filter(ConversationMember.conversation_id == conversation_id).all()
    member_ids = [m.user_id for m in members]

    await manager.broadcast_to_conversation(conversation_id, {
        "event": "disappearing_updated",
        "conversation_id": conversation_id,
        "disappearing_seconds": seconds,
        "changed_by": current_user.display_name,
    }, member_ids)

    return _serialize_conversation(db, conv, current_user, members=members, last_message=None, unread_count=0)
