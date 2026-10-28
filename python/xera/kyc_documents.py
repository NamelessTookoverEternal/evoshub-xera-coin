"""
Manual KYC documents: ID front/back + selfie, kept ONLY until the admin decides.

Rules this module enforces
  * Images are re-encoded to JPEG with Pillow (proves they are real images, strips EXIF/GPS, caps size and pixels).
  * They are stored in a PRIVATE bucket under random paths. There are no public or signed URLs: an admin reads an image
    only through the backend, and every read is written to xera_kyc_access_log BEFORE the bytes are returned.
  * A user can never read, list or delete documents. An admin cannot open their own submission.
  * VERIFIED needs the reviewing admin to have opened the ID front and the selfie (and the back, if there is one).
  * On VERIFIED or FAILED the files are erased from storage and the rows marked deleted. Unreviewed files are erased
    after XERA_KYC_DOC_RETENTION_DAYS (default 30). A failed erase is kept for retry and logged as CRITICAL.
  * Consent (time + notice version) is required and stored. File contents, names and hashes are never logged.

Environment: XERA_KYC_DOC_UPLOAD=true (switch on), XERA_KYC_BUCKET (default xera-kyc),
XERA_KYC_DOC_RETENTION_DAYS (default 30), XERA_KYC_NOTICE_VERSION (default 1).
"""
import hashlib
import io
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from main import supabase

logger = logging.getLogger(__name__)

KINDS = ("id_front", "id_back", "selfie")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024          # per file, as received
MAX_STORED_BYTES = 5 * 1024 * 1024          # per file, after re-encoding (matches the bucket limit)
MAX_PIXELS = 40_000_000
MAX_SIDE = 2000


class DocError(Exception):
    """Short machine-readable code; the route maps it to an HTTP response."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enabled() -> bool:
    return os.getenv("XERA_KYC_DOC_UPLOAD", "false").strip().lower() in ("1", "true", "yes", "on")


def _bucket() -> str:
    return os.getenv("XERA_KYC_BUCKET", "xera-kyc").strip() or "xera-kyc"


def retention_days() -> int:
    try:
        return max(1, int(os.getenv("XERA_KYC_DOC_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def notice_version() -> str:
    return os.getenv("XERA_KYC_NOTICE_VERSION", "1").strip() or "1"


# ------------------------------------------------------------ storage (thin, replaceable in tests)

def _put(path: str, data: bytes) -> None:
    supabase.storage.from_(_bucket()).upload(path, data, {"content-type": "image/jpeg", "upsert": "false"})


def _get(path: str) -> bytes:
    return supabase.storage.from_(_bucket()).download(path)


def _remove(paths: list) -> None:
    supabase.storage.from_(_bucket()).remove(paths)


def _first(res):
    data = getattr(res, "data", None)
    return (data[0] if data else None) if isinstance(data, list) else (data or None)


# ------------------------------------------------------------ image handling

def clean_image(raw: bytes) -> bytes:
    """Return a re-encoded JPEG (no metadata). Anything that is not a real JPEG/PNG/WEBP image is refused."""
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise DocError("image_too_large" if raw else "image_missing")
    try:
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ("JPEG", "PNG", "WEBP"):
            raise DocError("image_invalid")
        probe.verify()                                  # integrity check
        img = Image.open(io.BytesIO(raw))               # verify() leaves the object unusable: reopen
        img = ImageOps.exif_transpose(img)              # honour the phone's rotation before the EXIF is dropped
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)      # no exif= argument: metadata is dropped
    except DocError:
        raise
    except Exception:
        raise DocError("image_invalid")
    data = out.getvalue()
    if len(data) > MAX_STORED_BYTES:
        raise DocError("image_too_large")
    return data


# ------------------------------------------------------------ erase

def _live_documents(user_id: int) -> list:
    res = (supabase.table("xera_kyc_documents").select("*").eq("user_id", user_id).is_("deleted_at", "null")
           .order("id").execute())
    return res.data or []


def _erase(rows: list, reason: str) -> dict:
    """Remove files from storage, then mark the rows deleted. A file that cannot be erased stays 'live' for retry."""
    erased = failed = 0
    for row in rows:
        try:
            _remove([row["storage_path"]])
        except Exception as exc:
            failed += 1
            logger.critical("KYC DOCUMENT ERASE FAILED (document %s, user %s): %s", row.get("id"), row.get("user_id"), type(exc).__name__)
            continue
        supabase.table("xera_kyc_documents").update({"deleted_at": _now(), "deleted_reason": reason}).eq("id", row["id"]).execute()
        erased += 1
    return {"erased": erased, "failed": failed}


def purge_user(user_id: int, reason: str) -> dict:
    return _erase(_live_documents(user_id), reason)


def purge_expired() -> dict:
    """Erase live documents older than the retention period, and any left behind by a decided case."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days())
    res = supabase.table("xera_kyc_documents").select("*").is_("deleted_at", "null").execute()
    decided = {r["user_id"]: r.get("status") for r in (supabase.table("xera_kyc").select("user_id,status").in_(
        "user_id", sorted({d["user_id"] for d in (res.data or [])}) or [0]).execute().data or [])}
    expired, leftover = [], []
    for d in res.data or []:
        try:
            created = datetime.fromisoformat(str(d["created_at"]).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            created = None
        if decided.get(d["user_id"]) in ("VERIFIED", "FAILED"):
            leftover.append(d)
        elif created is not None and created < cutoff:
            expired.append(d)
    a, b = _erase(expired, "EXPIRED"), _erase(leftover, "DECIDED")
    for uid in sorted({d["user_id"] for d in expired}):
        if not _live_documents(uid):
            # Nothing left to review: ask the user to upload again instead of leaving the case stuck.
            supabase.table("xera_kyc").update({
                "status": "INFO_REQUIRED", "review_note": "Your uploaded documents were removed after the retention period. Please upload them again.",
                "updated_at": _now()}).eq("user_id", uid).eq("status", "PENDING").eq("method", "MANUAL").execute()
    return {"erased": a["erased"] + b["erased"], "failed": a["failed"] + b["failed"]}


# ------------------------------------------------------------ user: submit

def submit(user_id: int, *, legal_name: str, country: str, id_type: str, consent: bool, files: dict) -> dict:
    """
    files: {"id_front": bytes, "id_back": bytes | None, "selfie": bytes}. Can only ever result in PENDING.
    """
    from xera import readiness
    if not enabled():
        raise DocError("upload_not_enabled")
    if not consent:
        raise DocError("consent_required")
    legal_name = " ".join((legal_name or "").split())
    country = (country or "").strip().upper()
    id_type = (id_type or "").strip().lower()
    if len(legal_name) < 3 or len(legal_name) > 120:
        raise DocError("invalid_name")
    if len(country) < 2 or len(country) > 56:
        raise DocError("invalid_country")
    if id_type not in readiness._ID_TYPES:
        raise DocError("invalid_id_type")
    if not files.get("id_front") or not files.get("selfie"):
        raise DocError("documents_missing")
    if id_type != "passport" and not files.get("id_back"):
        raise DocError("documents_missing")            # a passport has no back page; every other ID does

    current = readiness.get_kyc(user_id)
    if current.get("unavailable"):
        raise DocError("kyc_unavailable")
    if current["status"] in ("VERIFIED", "PENDING"):
        raise DocError("kyc_already_" + current["status"].lower())

    cleaned = {k: clean_image(v) for k, v in files.items() if k in KINDS and v}      # validate everything before storing anything

    purge_expired_safely()
    stale = purge_user(user_id, "RESUBMITTED")
    if stale["failed"]:
        raise DocError("storage_unavailable")          # never pile new files on top of ones we could not erase

    stored = []
    try:
        for kind, data in cleaned.items():
            path = f"kyc/{int(user_id)}/{uuid.uuid4().hex}.jpg"
            _put(path, data)
            stored.append(path)
            supabase.table("xera_kyc_documents").insert({
                "user_id": user_id, "kind": kind, "storage_path": path, "content_type": "image/jpeg",
                "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "created_at": _now(),
            }).execute()
        row = {
            "user_id": user_id, "status": "PENDING", "method": "MANUAL", "provider": "MANUAL",
            "legal_name": legal_name, "country": country, "id_type": id_type, "id_last4": None,
            "docs_consent_at": _now(), "docs_consent_version": notice_version(),
            "submitted_at": _now(), "reviewed_at": None, "reviewed_by": None, "review_note": None, "updated_at": _now(),
        }
        existing = supabase.table("xera_kyc").select("user_id").eq("user_id", user_id).limit(1).execute()
        if existing.data:
            supabase.table("xera_kyc").update(row).eq("user_id", user_id).execute()
        else:
            supabase.table("xera_kyc").insert(row).execute()
    except Exception as exc:
        logger.error("KYC document submit failed for user %s: %s", user_id, type(exc).__name__)
        _erase(_live_documents(user_id), "ABORTED")
        if stored:
            try:
                _remove(stored)
            except Exception:
                logger.critical("KYC DOCUMENT CLEANUP FAILED after an aborted submit (user %s)", user_id)
        raise DocError("storage_unavailable")
    try:
        supabase.table("xera_readiness_events").insert({"user_id": user_id, "actor_id": None, "event": "KYC_DOCS_SUBMITTED",
                                                        "detail": {"consent_version": notice_version(), "files": sorted(cleaned)}}).execute()
    except Exception:
        pass
    return {"status": "PENDING"}


def purge_expired_safely() -> None:
    try:
        purge_expired()
    except Exception as exc:
        logger.warning("KYC expiry purge skipped: %s", type(exc).__name__)


# ------------------------------------------------------------ admin: view

def list_documents(admin_id: int, user_id: int) -> list:
    if admin_id == user_id:
        raise DocError("cannot_review_own_kyc")
    return [{"id": d["id"], "kind": d["kind"], "size_bytes": d["size_bytes"], "created_at": d["created_at"]}
            for d in _live_documents(user_id)]


def read_document(admin_id: int, document_id: int) -> tuple:
    """(bytes, content_type). The view is recorded FIRST; if it cannot be recorded, nothing is returned."""
    doc = _first(supabase.table("xera_kyc_documents").select("*").eq("id", document_id).limit(1).execute())
    if not doc or doc.get("deleted_at"):
        raise DocError("document_not_found")
    if admin_id == doc["user_id"]:
        raise DocError("cannot_review_own_kyc")
    try:
        supabase.table("xera_kyc_access_log").insert({"user_id": doc["user_id"], "admin_id": admin_id,
                                                      "document_id": doc["id"], "action": "view", "created_at": _now()}).execute()
    except Exception:
        raise DocError("audit_unavailable")
    try:
        data = _get(doc["storage_path"])
    except Exception:
        raise DocError("document_unavailable")
    return data, doc.get("content_type") or "image/jpeg"


def review_precheck(admin_id: int, user_id: int) -> None:
    """Before VERIFIED: this admin must have opened every live document, so a tick can't be a blind tick."""
    live = _live_documents(user_id)
    if not live:
        return
    seen = {r["document_id"] for r in (supabase.table("xera_kyc_access_log").select("document_id")
                                       .eq("user_id", user_id).eq("admin_id", admin_id).execute().data or [])}
    if any(d["id"] not in seen for d in live):
        raise DocError("documents_not_viewed")


def counts_for(rows: list) -> None:
    """Add documents=<live count> to admin list rows (in place)."""
    ids = sorted({r["user_id"] for r in rows})
    if not ids:
        return
    live = supabase.table("xera_kyc_documents").select("user_id").is_("deleted_at", "null").in_("user_id", ids).execute().data or []
    n = {}
    for d in live:
        n[d["user_id"]] = n.get(d["user_id"], 0) + 1
    for r in rows:
        r["documents"] = n.get(r["user_id"], 0)
