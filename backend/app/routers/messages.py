"""
Messages router module.
Handles endpoints for fetching conversation messages and marking messages as read.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
import datetime
from backend.app.core.db import get_db
from backend.app.core.security import get_current_user
from backend.app.models import User, Conversation, ConversationMember, Message, MessageReceipt, MessageReaction
from backend.app.schemas import MessageResponse

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _serialize_message(db: Session, msg: Message) -> dict:
    """
    Build the API response dict for a single message.

    Groups raw per-user reaction rows into one entry per distinct emoji, each
    carrying the full list of reactor user IDs (see `ReactionSummary` for why
    this isn't pre-aggregated into a count/reacted_by_me pair). Also resolves
    a compact reply-to preview when this message is a reply. Every endpoint
    that returns message data goes through this helper rather than returning
    a raw ORM Message — `Message.reactions`/`Message.reply_to` are
    relationship attributes whose raw shape doesn't match the
    `ReactionSummary`/`ReplyToSummary` schemas.
    """
    reaction_rows = db.query(MessageReaction).filter(MessageReaction.message_id == msg.id).all()
    grouped: dict = {}
    for r in reaction_rows:
        grouped.setdefault(r.emoji, []).append(r.user_id)
    reactions = [{"emoji": emoji, "user_ids": user_ids} for emoji, user_ids in grouped.items()]

    reply_to = None
    if msg.reply_to_id:
        parent = db.query(Message).filter(Message.id == msg.reply_to_id).first()
        if parent:
            snippet = parent.content if len(parent.content) <= 60 else parent.content[:57] + "..."
            reply_to = {
                "id": parent.id,
                "sender_name": parent.sender.display_name,
                "content_snippet": snippet or "📎 Attachment",
            }

    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender_id": msg.sender_id,
        "content": msg.content,
        "attachment_url": msg.attachment_url,
        "attachment_type": msg.attachment_type,
        "created_at": msg.created_at,
        "status": msg.status,
        "reactions": reactions,
        "reply_to": reply_to,
        "expires_at": msg.expires_at,
    }


@router.get("/{conversation_id}", response_model=List[MessageResponse])
def get_messages(conversation_id: int, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Fetch messages for a specific conversation and update read statuses.
    
    Args:
        conversation_id: The ID of the conversation.
        limit: Maximum number of messages to retrieve.
        current_user: The authenticated user.
        db: Database session.
        
    Returns:
        A list of messages for the requested conversation.
    """
    # Verify user is a member of this conversation before fetching messages
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this conversation"
        )
        
    # Select the most recent `limit` messages (descending), then reverse in
    # Python so the response stays oldest->newest as the frontend expects.
    # (Ordering ascending-then-limiting, as this used to do, returns the
    # OLDEST messages instead of the most recent ones for any conversation
    # with more than `limit` messages.)
    # Also excludes already-expired disappearing messages defensively — the
    # background sweep in main.py should normally have deleted them already,
    # but this guards against the sweep interval not having run yet.
    now = datetime.datetime.utcnow()
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).filter((Message.expires_at.is_(None)) | (Message.expires_at > now)
    ).order_by(desc(Message.created_at)).limit(limit).all()
    messages.reverse()

    # Mark messages as read by updating last_read_message_id and adding read receipts
    if messages:
        latest_msg = messages[-1]
        member.last_read_message_id = latest_msg.id
        
        # Insert read receipts for all messages the current user hasn't read yet (excluding their own)
        unreceipted_msgs = [m for m in messages if m.sender_id != current_user.id]
        for msg in unreceipted_msgs:
            # Check if a read receipt already exists to avoid duplicates
            existing_receipt = db.query(MessageReceipt).filter(
                MessageReceipt.message_id == msg.id,
                MessageReceipt.user_id == current_user.id,
                MessageReceipt.status == "read"
            ).first()
            
            if not existing_receipt:
                receipt = MessageReceipt(
                    message_id=msg.id,
                    user_id=current_user.id,
                    status="read",
                    timestamp=datetime.datetime.utcnow()
                )
                db.add(receipt)
                
                # Check if all other members have read the message to update its overall status
                other_members = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.user_id != msg.sender_id
                ).all()
                
                # Count total read receipts for this message (excluding the original sender)
                read_receipts_count = db.query(MessageReceipt).filter(
                    MessageReceipt.message_id == msg.id,
                    MessageReceipt.status == "read"
                ).count()
                
                # If all recipients have read it, mark it as read globally; otherwise keep as delivered
                if read_receipts_count + 1 >= len(other_members):
                    msg.status = "read"
                elif msg.status != "read":
                    msg.status = "delivered"
                    
        db.commit()
        # Refetch messages to get updated statuses after creating receipts
        messages = db.query(Message).filter(
            Message.conversation_id == conversation_id
        ).filter((Message.expires_at.is_(None)) | (Message.expires_at > now)
        ).order_by(desc(Message.created_at)).limit(limit).all()
        messages.reverse()
    return [_serialize_message(db, m) for m in messages]

@router.post("/{conversation_id}/read")
def mark_as_read(conversation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Mark all unread messages in a conversation as read for the current user.
    
    Args:
        conversation_id: The ID of the conversation.
        current_user: The authenticated user.
        db: Database session.
        
    Returns:
        A status dictionary indicating success.
    """
    # Verify user is a member of the conversation
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this conversation"
        )
        
    # Find the latest message in this conversation to update the high-water mark
    latest_msg = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(desc(Message.created_at)).first()
    if latest_msg:
        member.last_read_message_id = latest_msg.id
        
        # Identify all messages sent by others that need a read receipt
        unread_msgs = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.sender_id != current_user.id,
            Message.id <= latest_msg.id
        ).all()
        
        for msg in unread_msgs:
            # Create a read receipt if it doesn't already exist
            existing = db.query(MessageReceipt).filter(
                MessageReceipt.message_id == msg.id,
                MessageReceipt.user_id == current_user.id,
                MessageReceipt.status == "read"
            ).first()
            if not existing:
                rc = MessageReceipt(
                    message_id=msg.id,
                    user_id=current_user.id,
                    status="read"
                )
                db.add(rc)
                
                # Check if all other members have read it to update the global message status
                other_members = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.user_id != msg.sender_id
                ).all()
                
                read_receipts_count = db.query(MessageReceipt).filter(
                    MessageReceipt.message_id == msg.id,
                    MessageReceipt.status == "read"
                ).count()
                
                if read_receipts_count + 1 >= len(other_members):
                    msg.status = "read"
                else:
                    msg.status = "delivered"
        db.commit()
    return {"status": "success"}
