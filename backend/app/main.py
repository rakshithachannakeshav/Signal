"""
Main application module for the Signal Clone backend API.

This module initializes the FastAPI application, sets up CORS middleware,
configures static file serving for uploads, and registers all API routers.
"""
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import datetime
import os
import shutil
import uuid
from backend.app.core.db import init_db, SessionLocal
from backend.app.seed import seed_data
from backend.app.core.connection_manager import manager
from backend.app.models import Message, ConversationMember
from backend.app.routers import auth, users, conversations, messages, ws


async def _expire_disappearing_messages():
    """
    Background sweep for the disappearing-messages bonus feature.

    Runs forever in a loop, every 5 seconds looking for messages whose
    `expires_at` has passed, deleting them, and broadcasting a
    `message_deleted` event so any open client removes them from view
    without needing to poll or refetch. A simple interval loop (rather than
    per-message `asyncio.sleep` timers) keeps this correct across backend
    restarts — nothing needs to be rescheduled on startup since eligibility
    is computed fresh from the DB on each pass.
    """
    while True:
        await asyncio.sleep(5)
        db = SessionLocal()
        try:
            now = datetime.datetime.utcnow()
            expired = db.query(Message).filter(
                Message.expires_at.isnot(None),
                Message.expires_at <= now
            ).all()
            for msg in expired:
                conv_id = msg.conversation_id
                msg_id = msg.id
                member_ids = [
                    m.user_id for m in db.query(ConversationMember).filter(
                        ConversationMember.conversation_id == conv_id
                    ).all()
                ]
                db.delete(msg)
                db.commit()
                await manager.broadcast_to_conversation(conv_id, {
                    "event": "message_deleted",
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                }, member_ids)
        except Exception:
            db.rollback()
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for the FastAPI application.

    Handles startup events like initializing the database tables and
    running the initial data seed script, and starts the background
    disappearing-messages sweep. Yields control to the app, and cancels the
    background task on shutdown.
    """
    # Initialize DB tables
    init_db()

    # Run seed script
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()

    sweep_task = asyncio.create_task(_expire_disappearing_messages())
    yield
    sweep_task.cancel()

app = FastAPI(
    title="Signal Clone API",
    description="Backend API for Signal Clone messenger assignment",
    version="1.0.0",
    lifespan=lifespan
)

# Create upload directory inside project
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static_uploads", StaticFiles(directory=UPLOAD_DIR), name="static_uploads")

# CORS setup
# CORS_ORIGINS accepts a comma-separated list, so a deployed frontend origin
# can be added via environment configuration instead of a code change.
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
origins = [
    "http://localhost:3000",
    "https://signal-pink-pi.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(conversations.router)
app.include_router(messages.router)
app.include_router(ws.router)

@app.post("/api/upload")
def upload_file(file: UploadFile = File(...)):
    """
    Endpoint to handle file uploads.

    Generates a unique filename using UUID, saves the file to the static uploads
    directory, and returns the public URL and determined MIME type category
    (image, video, audio, or file).
    """
    file_ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Return file access url. PUBLIC_BASE_URL must be set in production so
    # uploaded-file links resolve to the deployed backend, not localhost.
    

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://signal-production-c83e.up.railway.app"
)
    file_url = f"{PUBLIC_BASE_URL}/static_uploads/{unique_filename}"
    
    # Determine type category based on file extension
    mime_type = "file"
    if file_ext.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
        mime_type = "image"
    elif file_ext.lower() in [".mp4", ".webm", ".ogg"]:
        mime_type = "video"
    elif file_ext.lower() in [".mp3", ".wav", ".m4a"]:
        mime_type = "audio"
        
    return {
        "url": file_url,
        "filename": file.filename,
        "type": mime_type
    }

@app.get("/api/health")
def health_check():
    """
    Simple health check endpoint to verify the API is running.
    """
    return {"status": "healthy", "service": "signal-clone-backend"}
