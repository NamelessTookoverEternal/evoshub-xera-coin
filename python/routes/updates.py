"""
App "Updates" channel (phase 1) — mounted in main.py as:

    app.include_router(updates_router,       prefix="/api/updates",       tags=["updates"])
    app.include_router(updates_admin_router, prefix="/api/admin/updates")

  GET    /api/updates            public  — newest first, cursor = ?before=<id>
  POST   /api/admin/updates      admin   — multipart: body (text) + up to 4 images
  PATCH  /api/admin/updates/{id} admin   — edit the text
  DELETE /api/admin/updates/{id} admin   — delete the post AND its images

Who may post: only an ACTIVE admin agent. This is enforced here, per request: the bearer token must verify and
admin_agents.is_active must be true right now (revoking an agent takes effect immediately). Hiding buttons in the
app is not the protection.

Images: every upload is decoded and re-encoded with Pillow, which proves it is a real JPEG/PNG/WebP, strips EXIF/GPS,
caps the size in pixels and bytes, and gives it a random server-chosen name. SVG and anything else is refused.
Text is stored as typed and always rendered with textContent by the app (never as HTML).

Environment: SUPABASE_URL (already required), APP_UPDATES_BUCKET (default app-updates).
"""
import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from main import limiter, supabase
from xera.admin_auth import AdminTokenInvalid, require_active_admin

logger = logging.getLogger(__name__)

router = APIRouter()
admin_router = APIRouter(include_in_schema=False)

MAX_BODY_CHARS = 4000
MAX_IMAGES = 4
MAX_UPLOAD_BYTES = 8 * 1024 * 1024      # per file as received (phones send big photos; we shrink them)
MAX_STORED_BYTES = 2 * 1024 * 1024      # per file after re-encoding (matches the bucket limit)
MAX_PIXELS = 40_000_000
MAX_SIDE = 1600
PAGE_DEFAULT, PAGE_MAX = 20, 30
BADGE = "Evoxera Admin"


class ImageError(Exception):
    """Machine-readable code; the route maps it to an HTTP response."""


def _bucket() -> str:
    return os.getenv("APP_UPDATES_BUCKET", "app-updates").strip() or "app-updates"


def _public_base() -> str:
    return f"{os.getenv('SUPABASE_URL', '').rstrip('/')}/storage/v1/object/public/{_bucket()}"


# ------------------------------------------------------------ storage (thin, replaceable in tests)

def _put(path: str, data: bytes, content_type: str) -> None:
    supabase.storage.from_(_bucket()).upload(path, data, {"content-type": content_type, "upsert": "false"})


def _remove(paths: list) -> None:
    if paths:
        supabase.storage.from_(_bucket()).remove(paths)


# ------------------------------------------------------------ text + images

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_body(value: str) -> str:
    """Normalise line breaks, drop control characters, collapse big blank gaps. No HTML handling: it is never rendered as HTML."""
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    value = _CTRL.sub("", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def clean_image(raw: bytes) -> tuple:
    """Return (bytes, content_type, ext, width, height) — re-encoded, no metadata. Raises ImageError."""
    if not raw:
        raise ImageError("image_missing")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError("image_too_large")
    try:
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ("JPEG", "PNG", "WEBP"):
            raise ImageError("image_invalid")
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        for quality, scale in ((85, 1.0), (75, 1.0), (65, 0.85), (55, 0.7)):
            work = img if scale == 1.0 else img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
            out = io.BytesIO()
            if has_alpha:
                work.save(out, format="PNG", optimize=True)          # keeps transparency; no exif= so metadata is dropped
                ctype, ext = "image/png", "png"
            else:
                work.save(out, format="JPEG", quality=quality, optimize=True)
                ctype, ext = "image/jpeg", "jpg"
            if out.tell() <= MAX_STORED_BYTES:
                return out.getvalue(), ctype, ext, work.width, work.height
            if has_alpha:
                img = img.resize((max(1, int(img.width * 0.75)), max(1, int(img.height * 0.75))))
        raise ImageError("image_too_large")
    except ImageError:
        raise
    except Exception:
        raise ImageError("image_invalid")


_IMAGE_MESSAGES = {
    "image_missing": "One of the images was empty.",
    "image_too_large": "An image is too large. Use a photo under 8 MB.",
    "image_invalid": "Only real JPEG, PNG or WebP images are allowed.",
}


# ------------------------------------------------------------ shaping

def _image_out(img: dict, post_id: int, n: int) -> dict:
    path = img.get("path", "")
    ext = path.rsplit(".", 1)[-1] if "." in path else "jpg"
    url = f"{_public_base()}/{path}"
    # Supabase's ?download= makes the response a file download even cross-origin, where <a download> is ignored.
    return {
        "url": url,
        "download_url": f"{url}?download=evoxera-update-{post_id}-{n + 1}.{ext}",
        "width": img.get("width"),
        "height": img.get("height"),
    }


def _out(row: dict) -> dict:
    return {
        "id": row["id"],
        "body": row.get("body") or "",
        "badge": BADGE,
        "created_at": row.get("created_at"),
        "edited_at": row.get("edited_at"),
        "images": [_image_out(i, row["id"], n) for n, i in enumerate(row.get("images") or [])],
    }


def _admin(authorization: str) -> int:
    try:
        return require_active_admin(supabase, authorization)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")


# ------------------------------------------------------------ public read

def _list(limit: int, before: int | None) -> dict:
    q = supabase.table("app_updates").select("*").order("id", desc=True)
    if before:
        q = q.lt("id", before)
    rows = q.limit(limit + 1).execute().data or []
    return {"status": "ok", "updates": [_out(r) for r in rows[:limit]], "has_more": len(rows) > limit}


@router.get("")
@limiter.limit("60/minute")
async def list_updates(request: Request, limit: int = PAGE_DEFAULT, before: int | None = None):
    limit = max(1, min(int(limit), PAGE_MAX))
    return await run_in_threadpool(_list, limit, before)


# ------------------------------------------------------------ admin write

def _create(admin_id: int, body: str, files: list) -> dict:
    # 1) validate + re-encode everything BEFORE touching storage, so a bad third image leaves nothing behind
    cleaned = []
    for raw in files:
        try:
            cleaned.append(clean_image(raw))
        except ImageError as exc:
            raise HTTPException(status_code=400, detail=_IMAGE_MESSAGES.get(str(exc), "Invalid image."))
    # 2) upload
    now = datetime.now(timezone.utc)
    stored, images = [], []
    try:
        for data, ctype, ext, w, h in cleaned:
            path = f"{now:%Y/%m}/{uuid.uuid4().hex}.{ext}"
            _put(path, data, ctype)
            stored.append(path)
            images.append({"path": path, "width": w, "height": h})
    except Exception:
        logger.exception("app_updates: image upload failed")
        _remove_quietly(stored)
        raise HTTPException(status_code=502, detail="Could not store the images. Try again.")
    # 3) insert; if that fails, do not leave orphaned files
    try:
        row = supabase.table("app_updates").insert({"author_id": admin_id, "body": body, "images": images}).execute().data[0]
    except Exception:
        logger.exception("app_updates: insert failed")
        _remove_quietly(stored)
        raise HTTPException(status_code=502, detail="Could not save the update. Try again.")
    return {"status": "ok", "update": _out(row)}


def _remove_quietly(paths: list) -> None:
    try:
        _remove(paths)
    except Exception:
        logger.error("app_updates: could not remove %d stored image(s); they are orphaned", len(paths))


@admin_router.post("")
@limiter.limit("30/hour")
async def create_update(
    request: Request,
    body: str = Form(""),
    images: list[UploadFile] = File(default=[]),
    authorization: str = Header(default=""),
):
    admin_id = await run_in_threadpool(_admin, authorization)
    text = clean_body(body)
    if len(text) > MAX_BODY_CHARS:
        raise HTTPException(status_code=400, detail=f"Text is too long (max {MAX_BODY_CHARS} characters).")
    if len(images) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_IMAGES} images per update.")
    raws = []
    for f in images:
        raws.append(await f.read(MAX_UPLOAD_BYTES + 1))
    if not text and not raws:
        raise HTTPException(status_code=400, detail="Write something or attach an image.")
    return await run_in_threadpool(_create, admin_id, text, raws)


class EditBody(BaseModel):
    body: str = Field(..., max_length=MAX_BODY_CHARS * 2)


def _edit(post_id: int, text: str) -> dict:
    rows = supabase.table("app_updates").select("*").eq("id", post_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Update not found.")
    if not text and not (rows[0].get("images") or []):
        raise HTTPException(status_code=400, detail="An update needs text or an image.")
    upd = supabase.table("app_updates").update(
        {"body": text, "edited_at": datetime.now(timezone.utc).isoformat()}).eq("id", post_id).execute().data
    return {"status": "ok", "update": _out((upd or rows)[0])}


@admin_router.patch("/{post_id}")
@limiter.limit("60/hour")
async def edit_update(request: Request, post_id: int, data: EditBody, authorization: str = Header(default="")):
    await run_in_threadpool(_admin, authorization)
    text = clean_body(data.body)
    if len(text) > MAX_BODY_CHARS:
        raise HTTPException(status_code=400, detail=f"Text is too long (max {MAX_BODY_CHARS} characters).")
    return await run_in_threadpool(_edit, post_id, text)


def _delete(post_id: int) -> dict:
    rows = supabase.table("app_updates").select("*").eq("id", post_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Update not found.")
    paths = [i.get("path") for i in (rows[0].get("images") or []) if i.get("path")]
    # Images first: if storage fails the post stays, so the admin can retry (no invisible orphans).
    try:
        _remove(paths)
    except Exception:
        logger.exception("app_updates: image delete failed for post %s", post_id)
        raise HTTPException(status_code=502, detail="Could not delete the images. Try again.")
    supabase.table("app_updates").delete().eq("id", post_id).execute()
    return {"status": "ok", "deleted": post_id}


@admin_router.delete("/{post_id}")
@limiter.limit("60/hour")
async def delete_update(request: Request, post_id: int, authorization: str = Header(default="")):
    await run_in_threadpool(_admin, authorization)
    return await run_in_threadpool(_delete, post_id)
