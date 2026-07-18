"""
Database models for the Signal Clone application.

This module defines the SQLAlchemy declarative models for the database
schema, including User, Contact, Conversation, Message, and related tables.
"""
import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Table, Index, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    """
    Represents a user in the system.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_or_username = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    status = Column(String, default="offline")  # online, offline, last_seen:...
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    contacts = relationship(
        "Contact",
        foreign_keys="[Contact.owner_id]",
        back_populates="owner",
        cascade="all, delete-orphan"
    )
    memberships = relationship("ConversationMember", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="sender")
    receipts = relationship("MessageReceipt", back_populates="user", cascade="all, delete-orphan")


class Contact(Base):
    """
    Represents a contact relationship between two users.
    
    This is a one-way relationship where 'owner' has 'contact_user' in their contacts.
    """
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    contact_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id], back_populates="contacts")
    contact_user = relationship("User", foreign_keys=[contact_user_id])


class Conversation(Base):
    """
    Represents a chat conversation, which can be either a direct message or a group chat.
    """
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, nullable=False)  # direct, group
    name = Column(String, nullable=True)   # null for direct, filled for group
    avatar_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    # Disappearing messages timer, in seconds. None/0 means disabled. When
    # set, new messages sent into this conversation get an expires_at stamp
    # and a background sweep (see main.py) deletes them once it passes.
    disappearing_seconds = Column(Integer, nullable=True)

    # Relationships
    members = relationship("ConversationMember", back_populates="conversation", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class ConversationMember(Base):
    """
    Represents a user's membership in a conversation.
    
    Tracks the user's role and the last message they have read in this conversation.
    """
    __tablename__ = "conversation_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, default="member")  # admin, member
    joined_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_read_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    conversation = relationship("Conversation", back_populates="members")
    user = relationship("User", back_populates="memberships")
    last_read_message = relationship("Message", foreign_keys=[last_read_message_id])


class Message(Base):
    """
    Represents a single message sent within a conversation.
    
    Includes support for text content and optional attachments.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(String, nullable=False)
    attachment_url = Column(String, nullable=True)
    attachment_type = Column(String, nullable=True)
    reply_to_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    # Set at creation time from the conversation's disappearing_seconds (if
    # any); a background sweep in main.py deletes messages past this point.
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    status = Column(String, default="sending")  # sending, sent, delivered, read

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", back_populates="messages")
    receipts = relationship("MessageReceipt", back_populates="message", cascade="all, delete-orphan")
    # Self-referential: the message this one is replying to, if any.
    # remote_side=[id] tells SQLAlchemy which side of the FK is the "one"
    # (parent) side, required for self-referential relationships.
    reply_to = relationship("Message", remote_side=[id], foreign_keys=[reply_to_id])
    reactions = relationship("MessageReaction", back_populates="message", cascade="all, delete-orphan")

    # Composite Index for fast pagination sorted by created_at
    __table_args__ = (
        Index("idx_conv_created", "conversation_id", "created_at"),
    )


class MessageReceipt(Base):
    """
    Represents the delivery and read status of a message for a specific user.
    """
    __tablename__ = "message_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)  # delivered, read
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    message = relationship("Message", back_populates="receipts")
    user = relationship("User", back_populates="receipts")


class MessageReaction(Base):
    """
    Represents one user's emoji reaction to a message.

    Unique per (message_id, user_id): a user has at most one active reaction
    per message. Picking a different emoji replaces it, and reacting again
    with the same emoji removes it (both handled at the application layer in
    ws.py — this constraint just prevents duplicate rows).
    """
    __tablename__ = "message_reactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    emoji = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    message = relationship("Message", back_populates="reactions")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_reaction_per_user_per_message"),
    )
