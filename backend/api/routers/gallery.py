import os
import json
import uuid
import time
import asyncio
import logging
import subprocess
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from core.db import get_db
from core.config import VOICES_DIR, OUTPUTS_DIR

logger = logging.getLogger("omnivoice.gallery")

router = APIRouter()

VOICE_GALLERY_DIR = Path(os.path.join(OUTPUTS_DIR, "voice_gallery"))
VOICE_GALLERY_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    {
        "id": "disney",
        "name": "Disney",
        "icon": "🎬",
        "description": "Disney characters, Pixar, and animated films",
    },
    {
        "id": "anime",
        "name": "Anime",
        "icon": "🎌",
        "description": "Japanese anime characters",
    },
    {
        "id": "marvel",
        "name": "Marvel/DC",
        "icon": "🦸",
        "description": "Superhero movies and TV shows",
    },
    {
        "id": "celebs",
        "name": "Celebrities",
        "icon": "⭐",
        "description": "Famous actors and personalities",
    },
    {
        "id": "politicians",
        "name": "Politicians",
        "icon": "🏛️",
        "description": "World leaders and politicians",
    },
    {
        "id": "news",
        "name": "News Anchors",
        "icon": "📰",
        "description": "News broadcasters",
    },
    {
        "id": "gaming",
        "name": "Gaming",
        "icon": "🎮",
        "description": "Video game characters",
    },
    {
        "id": "books",
        "name": "Books/Movies",
        "icon": "📚",
        "description": "Literary and film characters",
    },
]


class VoiceEntry(BaseModel):
    id: str
    name: str
    character: str
    category: str
    source_type: str  # "youtube", "upload", "preset"
    source_url: Optional[str] = None
    audio_path: str
    duration: float
    description: Optional[str] = None
    thumbnail: Optional[str] = None
    tags: List[str] = []
    created_at: float


def _init_gallery_db():
    """Initialize the voice gallery table."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS voice_gallery (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            character TEXT NOT NULL,
            category TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT,
            audio_path TEXT NOT NULL,
            duration REAL NOT NULL,
            description TEXT,
            thumbnail TEXT,
            tags TEXT,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()


@router.get("/gallery/categories")
def list_categories():
    """List all voice gallery categories."""
    return CATEGORIES


@router.get("/gallery/voices")
def list_voices(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by name or character"),
    limit: int = Query(50, ge=1, le=200),
):
    """List voices in the gallery, optionally filtered by category or search."""
    conn = get_db()
    query = "SELECT * FROM voice_gallery"
    params = []
    conditions = []

    if category:
        conditions.append("category = ?")
        params.append(category)
    if search:
        conditions.append("(name LIKE ? OR character LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        r["tags"] = json.loads(r.get("tags", "[]") or "[]")
        results.append(r)
    return results


@router.get("/gallery/voices/{voice_id}")
def get_voice(voice_id: str):
    """Get a specific voice from the gallery."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM voice_gallery WHERE id = ?", (voice_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Voice not found")
    r = dict(row)
    r["tags"] = json.loads(r.get("tags", "[]") or "[]")
    return r


@router.delete("/gallery/voices/{voice_id}")
def delete_voice(voice_id: str):
    """Delete a voice from the gallery."""
    conn = get_db()
    row = conn.execute(
        "SELECT audio_path FROM voice_gallery WHERE id = ?", (voice_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Voice not found")

    audio_path = row["audio_path"]
    if audio_path and os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except Exception:
            pass

    conn.execute("DELETE FROM voice_gallery WHERE id = ?", (voice_id,))
    conn.commit()
    conn.close()
    return {"success": True}


@router.post("/gallery/search/youtube")
async def search_youtube(
    query: str = Query(..., description="Character or celebrity name to search"),
    category: str = Query(..., description="Category to associate results with"),
    max_results: int = Query(5, ge=1, le=20),
):
    """Search YouTube for character/celebrity clips using yt-dlp."""
    try:
        result = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--flat-playlist",
            "--print",
            "%(title)s|%(id)s|%(duration)s|%(thumbnail)s",
            f"ytsearch{max_results}:{query}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            logger.error(f"yt-dlp search failed: {stderr.decode()}")
            raise HTTPException(
                status_code=500, detail=f"YouTube search failed: {stderr.decode()}"
            )

        lines = stdout.decode().strip().split("\n")
        results = []
        for line in lines:
            if line.strip():
                parts = line.split("|")
                if len(parts) >= 2:
                    results.append(
                        {
                            "title": parts[0],
                            "video_id": parts[1] if len(parts) > 1 else "",
                            "duration": parts[2] if len(parts) > 2 else None,
                            "thumbnail": parts[3] if len(parts) > 3 else None,
                        }
                    )

        return {"results": results, "query": query, "category": category}
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="yt-dlp not installed")
    except Exception as e:
        logger.error(f"YouTube search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gallery/download")
async def download_youtube_clip(
    video_url: str = Query(..., description="YouTube video URL"),
    start_time: float = Query(0, ge=0, description="Start time in seconds"),
    duration: float = Query(10, ge=1, le=30, description="Clip duration in seconds"),
    character_name: str = Query(..., description="Character/celebrity name"),
    category: str = Query(..., description="Category"),
    description: str = Query("", description="Optional description"),
):
    """Download a clip from YouTube for voice cloning."""
    voice_id = str(uuid.uuid4())[:8]
    output_path = str(VOICE_GALLERY_DIR / f"{voice_id}.wav")
    temp_path = str(VOICE_GALLERY_DIR / f"{voice_id}.%(ext)s")

    try:
        cmd = [
            "yt-dlp",
            "-f",
            "bestaudio",
            "--download-sections",
            f"*{start_time:.1f}-{start_time + duration:.1f}",
            "-x",
            "--audio-format",
            "wav",
            "--audio-quality",
            "0",
            "-o",
            temp_path,
            video_url,
        ]

        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            logger.error(f"yt-dlp download failed: {stderr.decode()}")
            raise HTTPException(
                status_code=500, detail=f"Download failed: {stderr.decode()}"
            )

        # Find the downloaded file (yt-dlp replaces %s with actual extension)
        downloaded_files = list(VOICE_GALLERY_DIR.glob(f"{voice_id}.*"))
        if not downloaded_files:
            raise HTTPException(status_code=500, detail="Downloaded file not found")

        actual_path = downloaded_files[0]
        # Rename to output_path
        final_path = Path(output_path)
        actual_path.rename(final_path)

        conn = get_db()
        conn.execute(
            """
            INSERT INTO voice_gallery 
            (id, name, character, category, source_type, source_url, audio_path, duration, description, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                voice_id,
                character_name,
                character_name,
                category,
                "youtube",
                video_url,
                output_path,
                duration,
                description,
                json.dumps([character_name.lower(), category]),
                time.time(),
            ),
        )
        conn.commit()
        conn.close()

        return {
            "success": True,
            "voice_id": voice_id,
            "audio_path": output_path,
            "duration": duration,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="yt-dlp not installed")
    except Exception as e:
        logger.error(f"Download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gallery/upload")
async def upload_voice_clip(
    name: str = Form(...),
    character: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    audio: UploadFile = File(...),
):
    """Upload a voice clip directly to the gallery."""
    voice_id = str(uuid.uuid4())[:8]
    ext = os.path.splitext(audio.filename or ".wav")[1]
    audio_path = str(VOICE_GALLERY_DIR / f"{voice_id}{ext}")

    with open(audio_path, "wb") as f:
        f.write(await audio.read())

    try:
        import soundfile as sf

        info = sf.info(audio_path)
        duration = info.frames / info.samplerate
    except Exception:
        duration = 10.0

    conn = get_db()
    conn.execute(
        """
        INSERT INTO voice_gallery 
        (id, name, character, category, source_type, source_url, audio_path, duration, description, tags, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            voice_id,
            name,
            character,
            category,
            "upload",
            None,
            audio_path,
            duration,
            description,
            json.dumps([character.lower(), category]),
            time.time(),
        ),
    )
    conn.commit()
    conn.close()

    return {
        "id": voice_id,
        "name": name,
        "audio_path": audio_path,
        "duration": duration,
    }


@router.post("/gallery/voices/{voice_id}/save-as-profile")
async def save_voice_as_profile(
    voice_id: str,
    profile_name: str = Query(..., description="Name for the voice profile"),
):
    """Save a gallery voice as a voice profile for cloning."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM voice_gallery WHERE id = ?", (voice_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Voice not found")

    profile_id = str(uuid.uuid4())[:8]
    import shutil

    ext = os.path.splitext(row["audio_path"])[1]
    new_audio_path = os.path.join(VOICES_DIR, f"{profile_id}{ext}")
    shutil.copy(row["audio_path"], new_audio_path)

    conn = get_db()
    conn.execute(
        """
        INSERT INTO voice_profiles (id, name, ref_audio_path, ref_text, instruct, language, seed, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            profile_id,
            profile_name,
            f"{profile_id}{ext}",
            row["description"] or "",
            row["character"] or "",
            "Auto",
            None,
            time.time(),
        ),
    )
    conn.commit()
    conn.close()

    return {"profile_id": profile_id, "name": profile_name}


@router.get("/gallery/voices/{voice_id}/preview")
def preview_voice(voice_id: str):
    """Get a voice clip for preview playback."""
    conn = get_db()
    row = conn.execute(
        "SELECT audio_path FROM voice_gallery WHERE id = ?", (voice_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Voice not found")

    audio_path = row["audio_path"]

    # Debug logging
    is_absolute = os.path.isabs(audio_path)
    path_exists = os.path.exists(audio_path) if audio_path else False

    # If absolute path, serve directly or redirect
    if is_absolute and path_exists:
        # Get just the relative path from outputs dir
        outputs_path = str(OUTPUTS_DIR)
        if audio_path.startswith(outputs_path):
            # Remove outputs_dir prefix to get relative path within outputs
            rel_path = os.path.relpath(audio_path, outputs_path)
            # The audio_path is like: /Users/user4/.../outputs/voice_gallery/file.wav
            # rel_path becomes: voice_gallery/file.wav
            # We want to serve from /audio/ so: /audio/voice_gallery/file.wav
            return RedirectResponse(f"/audio/{rel_path}")
        return FileResponse(audio_path, media_type="audio/wav")

    raise HTTPException(
        status_code=404,
        detail=f"Audio not found: abs={is_absolute}, exists={path_exists}, path={audio_path}",
    )
