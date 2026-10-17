"""
EVOSGPT — served by the EVOS Hub backend at /api/evosgpt.

Migrated from the standalone evosgpt-rebirth backend. Same endpoints, same tables
(users.evosgpt_tier, evosgpt_*), same behaviour — now:
  * one FastAPI app / one Render service (mounted by routes/evosgpt.py),
  * one login: /auth/login issues the Hub session token, and every user-scoped route
    verifies it (the old backend trusted a bare user_id from the browser),
  * the Hub's shared Supabase service client (no second SUPABASE_KEY),
  * visitor currency (default GHS, follows the visitor's country) in services/evosgpt/currency.py.
"""
from fastapi import APIRouter, HTTPException, Request, Header
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, EmailStr
from typing import Optional
from passlib.context import CryptContext
from datetime import datetime, timezone
import os, uuid, hmac, hashlib, requests, re, logging
from io import BytesIO

from reportlab.lib.pagesizes import A4, LETTER, LEGAL, A5
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, Table, TableStyle
from reportlab.lib import colors

from docx import Document as DocxDocument
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 fallback
    from backports.zoneinfo import ZoneInfo

from services.evosdata.db import get_supabase
from services.evosgpt import currency as _currency
from utils.rate_limit import limiter
from xera.user_auth import XeraTokenInvalid, make_user_token, verify_user_token

logger = logging.getLogger(__name__)

router = APIRouter()

# ENV (AI + payments only; Supabase comes from the Hub's shared client)
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
PAYSTACK_SECRET = os.getenv("EVOSGPT_PAYSTACK_SECRET_KEY") or os.getenv("PAYSTACK_SECRET_KEY")
# Where Paystack sends the customer back after paying (the Hub-mounted app).
EVOSGPT_APP_URL = os.getenv("EVOSGPT_APP_URL", "https://evoshub.xyz/evosgpt").rstrip("/")

db_client = get_supabase()

# Names core.py's missing-env check can report (OpenAI is only needed when someone chats).
MISSING_ENVS = [k for k, v in (("OPENAI_API_KEY", OPENAI_API_KEY), ("PAYSTACK_SECRET_KEY", PAYSTACK_SECRET)) if not v]


def install(app):
    """Startup hook: create the storage buckets (same behaviour as the standalone app)."""
    @app.on_event("startup")
    def _evosgpt_startup():
        ensure_image_bucket()
        ensure_document_bucket()


# =========================
# AUTH — Hub session token (same token /api/xera/auth/login issues)
# =========================
def _bearer(request: Request) -> str:
    h = request.headers.get("Authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.headers.get("X-User-Token", "").strip()

def require_user(request: Request, user_id: int) -> int:
    """403 unless the request carries a valid Hub session token for exactly this user."""
    token = _bearer(request)
    try:
        uid = verify_user_token(token) if token else None
    except (XeraTokenInvalid, RuntimeError):
        uid = None
    if uid is None or int(uid) != int(user_id):
        raise HTTPException(status_code=403, detail="Please sign in again")
    return int(user_id)

def _issue_token(user_id: int) -> Optional[str]:
    try:
        return make_user_token(int(user_id))
    except RuntimeError:       # XERA_TOKEN_SECRET not configured
        logger.error("EVOSGPT: XERA_TOKEN_SECRET missing — cannot issue session token")
        return None


_IDENTIFIER_RE = re.compile(r"^[a-z0-9._%+\-@]{1,120}$")

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
def hash_password(p): return pwd.hash(p)
def verify_password(p, h): return pwd.verify(p, h)

TIERS = {
    "Basic":   {"model": "gpt-4o-mini", "memory_limit": 20,   "day_limit": 10,   "price_ghs": 0,   "icon": "🧊"},
    "Pro":     {"model": "gpt-4o",      "memory_limit": 100,  "day_limit": None, "price_ghs": 20,  "icon": "⚡"},
    "Core":    {"model": "gpt-4o",      "memory_limit": 300,  "day_limit": None, "price_ghs": 70, "icon": "🔥"},
    "Founder": {"model": "gpt-4o",      "memory_limit": 1000, "day_limit": None, "price_ghs": 0,   "icon": "👑"},
}
PURCHASABLE_TIERS = {"Pro", "Core"}
IMAGE_GEN_TIERS = {"Pro", "Core", "Founder"}  # Basic tier cannot generate or edit images
DOCUMENT_GEN_TIERS = {"Pro", "Core", "Founder"}  # Basic tier cannot generate PDF/Word documents
LETTERHEAD_ALLOWED_TIER = "Founder"  # only Founder tier may create/edit institutional letterheads

# Paper sizes: reportlab pagesize (points) for PDF, and (width_cm, height_cm) for docx.
PAPER_SIZES = {
    "A4":     {"pdf": A4,     "docx_cm": (21.0, 29.7)},
    "A5":     {"pdf": A5,     "docx_cm": (14.8, 21.0)},
    "LETTER": {"pdf": LETTER, "docx_cm": (21.59, 27.94)},
    "LEGAL":  {"pdf": LEGAL,  "docx_cm": (21.59, 35.56)},
}
DEFAULT_PAPER_SIZE = "A4"

BASE_PROMPT = """You are EVOSGPT — an evolving AI assistant built by Evoxera Technology.
You adapt, remember, and grow with each user over time.

FORMATTING RULES (always follow):
- Code -> wrap in markdown code blocks with language tag: ```python, ```javascript, etc.
- Letters / formal writing -> proper structure: date, salutation, body, closing. Clean and copy-paste ready.
- Lists -> numbered or bullet points.
- Tables -> markdown table format.
- Explanations -> short paragraphs with bold headers where helpful.
- Never output a wall of unformatted text.
- After code blocks or letters, add: "Copy the above and paste directly."

You serve users primarily in Ghana and across Africa. Be smart, direct, and practical.

IMAGE POLICY (always follow):
- You CAN see and analyze images the user uploads in this chat — describe them, read text in them, answer questions about them, give feedback on them.
- You CANNOT draw, generate, or edit an image yourself as part of a normal reply. Never output markdown image syntax (e.g. ![alt](url)), base64 image data, or claim you created/attached/edited an image inline in your text.
- EVOSGPT has a separate built-in image tool (the 🎨 button to generate, and an "Edit" option on an attached image) that actually creates/edits images, available on Pro tier and above.
- If a user asks you to generate/create/draw/design/edit an image, logo, photo, letterhead, or picture: if they're eligible for it, tell them to use the 🎨 button (to generate) or attach the image and pick "Edit" (to edit). If they're on Basic tier, tell them this requires upgrading to Pro.
- LETTERHEAD POLICY: creating or editing an official letterhead / letterheaded document / branded institutional document (for a company, school, bank, government office, church, NGO, etc.) is restricted to Founder tier only, to prevent impersonation or document fraud. This restriction does NOT apply to a user editing their own personal photo (brightness, color, cropping, background, retouching, restoration, etc.) — that is allowed at whatever tier already has image-edit access. If a non-Founder user asks for an institutional letterhead, explain this policy plainly rather than attempting it.

DOCUMENT POLICY (always follow):
- EVOSGPT has a separate built-in document tool (the 📄 button next to the message box) that generates a real downloadable PDF or Word (.docx) file, laid out on a proper page (A4 by default, or Letter/Legal/A5), available on Pro tier and above.
- You CANNOT produce a real PDF/Word file yourself inline in a normal chat reply — never claim you've attached or generated a downloadable document in plain text. If a user wants a CV, report, letter, contract, invoice, or other document as an actual file, tell them to use the 📄 button. If they just want the wording/content to copy-paste, write it directly in chat as usual.
- The same LETTERHEAD POLICY above applies to the 📄 tool: institutional letterheads/branded official documents are Founder-tier only; personal documents (CV, personal letter, notes, a report the user is writing themselves) are unaffected."""

TIER_PERSONA = {
    "Basic":   "\n\nYou are in Basic mode. Be helpful and concise. For advanced tasks, mention that Pro or Core tier unlocks more power.",
    "Pro":     "\n\nYou are in Pro mode. The user is a professional (developer, designer, writer, entrepreneur). Deliver expert-quality answers. Code must be clean, commented, production-ready. Design briefs detailed. Writing polished.",
    "Core":    "\n\nYou are in Core mode, the most powerful tier. Think like a senior engineer, creative director, and strategist combined. Give thorough, insightful, structured responses.",
    "Founder": "\n\nYou are in Founder mode, exclusive access, unlimited intelligence and context. Be brilliant.",
}

EVOS_NUDGE = "\n\nIf the user mentions running low on data or internet, remind them they can buy affordable Ghana data bundles instantly at https://evosdata.xyz, part of the EVOS ecosystem."

class RegisterRequest(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str
    referred_by: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    user_id: int
    message: str
    image_base64: Optional[str] = None   # raw base64, no data-URI prefix
    image_mime: Optional[str] = "image/jpeg"

class ImageGenRequest(BaseModel):
    user_id: int
    prompt: str

class ImageEditRequest(BaseModel):
    user_id: int
    prompt: str
    image_base64: str            # raw base64, no data-URI prefix
    image_mime: Optional[str] = "image/png"

class DocumentGenRequest(BaseModel):
    user_id: int
    prompt: str
    doc_format: str = "pdf"           # "pdf" or "docx"
    paper_size: str = DEFAULT_PAPER_SIZE   # "A4" (default), "A5", "LETTER", "LEGAL"
    title: Optional[str] = None

class UpgradeRequest(BaseModel):
    user_id: int
    tier: str
    email: str

class CouponRequest(BaseModel):
    user_id: int
    code: str


def get_user_by_id(user_id: int) -> Optional[dict]:
    res = db_client.table("users").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None

def get_user_tier(user_id: int) -> str:
    u = get_user_by_id(user_id)
    return u.get("evosgpt_tier", "Basic") if u else "Basic"

def generate_referral_code(username: str) -> str:
    return f"EVOS-{username[:4].upper()}-{uuid.uuid4().hex[:4].upper()}"


def get_short_memory(user_id: int, limit: int = 20) -> list:
    res = db_client.table("evosgpt_memory").select("role,content").eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
    return list(reversed(res.data or []))

def get_long_memory(user_id: int) -> Optional[str]:
    res = db_client.table("evosgpt_long_memory").select("summary").eq("user_id", user_id).limit(1).execute()
    return res.data[0]["summary"] if res.data else None

def save_message(user_id: int, role: str, content: str):
    db_client.table("evosgpt_memory").insert({
        "user_id": user_id, "role": role, "content": content,
        "created_at": datetime.now(timezone.utc).isoformat()
    }).execute()

def trim_memory(user_id: int, limit: int):
    res = db_client.table("evosgpt_memory").select("id").eq("user_id", user_id).order("created_at", desc=False).execute()
    rows = res.data or []
    if len(rows) > limit:
        for r in rows[:len(rows) - limit]:
            db_client.table("evosgpt_memory").delete().eq("id", r["id"]).execute()

def update_long_memory(user_id: int, new_summary: str):
    existing = get_long_memory(user_id)
    if existing:
        merged = call_openai("gpt-4o-mini", "You are a memory summarizer. Be concise and factual.",
            f"Merge these two user summaries into one paragraph:\nOld: {existing}\nNew: {new_summary}")
        summary = merged or new_summary
        db_client.table("evosgpt_long_memory").update({"summary": summary, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("user_id", user_id).execute()
    else:
        db_client.table("evosgpt_long_memory").insert({"user_id": user_id, "summary": new_summary, "updated_at": datetime.now(timezone.utc).isoformat()}).execute()


def get_today_count(user_id: int) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    res = db_client.table("evosgpt_daily_chats").select("count").eq("user_id", user_id).eq("date", today).limit(1).execute()
    return res.data[0]["count"] if res.data else 0

def increment_today_count(user_id: int):
    today = datetime.now(timezone.utc).date().isoformat()
    res = db_client.table("evosgpt_daily_chats").select("id,count").eq("user_id", user_id).eq("date", today).limit(1).execute()
    if res.data:
        db_client.table("evosgpt_daily_chats").update({"count": res.data[0]["count"] + 1}).eq("id", res.data[0]["id"]).execute()
    else:
        db_client.table("evosgpt_daily_chats").insert({"user_id": user_id, "date": today, "count": 1}).execute()


# =========================
# GEOLOCATION + LOCAL TIME
# =========================
def get_client_ip(request: Request) -> str:
    # Render/Railway/most proxies set X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "8.8.8.8"

_GEO_CACHE: dict = {}
_GEO_TTL = 3600

def get_geo_context(request: Request) -> dict:
    """
    Looks up the caller's approximate location + local time from their IP.
    Uses ip-api.com (free, no key required, ~45 req/min limit).
    Falls back to UTC if the lookup fails (e.g. localhost, rate limit, no network).
    """
    ip = get_client_ip(request)
    import time as _t
    hit = _GEO_CACHE.get(ip)
    if hit and _t.time() - hit[0] < _GEO_TTL:
        geo = dict(hit[1])
        try:  # local time must stay current even when the lookup is cached
            geo["local_time"] = datetime.now(ZoneInfo(geo["timezone"])).strftime("%A, %d %B %Y, %I:%M %p")
        except Exception:
            pass
        return geo
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}", timeout=3)
        data = res.json()
        if data.get("status") != "success":
            raise ValueError(data.get("message", "geo lookup failed"))

        tz_name = data.get("timezone", "UTC")
        try:
            local_dt = datetime.now(ZoneInfo(tz_name))
            local_time = local_dt.strftime("%A, %d %B %Y, %I:%M %p")
        except Exception:
            tz_name = "UTC"
            local_time = datetime.now(timezone.utc).strftime("%A, %d %B %Y, %I:%M %p UTC")

        geo = {
            "ip": ip,
            "city": data.get("city", ""),
            "region": data.get("regionName", ""),
            "country": data.get("country", ""),
            "country_code": data.get("countryCode", ""),
            "timezone": tz_name,
            "local_time": local_time,
        }
        if len(_GEO_CACHE) > 5000:
            _GEO_CACHE.clear()
        _GEO_CACHE[ip] = (_t.time(), geo)
        return geo
    except Exception as e:
        print("GEO LOOKUP ERROR:", e)
        return {
            "ip": ip,
            "city": "", "region": "", "country": "", "country_code": "",
            "timezone": "UTC",
            "local_time": datetime.now(timezone.utc).strftime("%A, %d %B %Y, %I:%M %p UTC"),
        }


# =========================
# STRAY-IMAGE-SYNTAX SAFETY NET
# =========================
# The model is told never to fabricate inline image markdown in a normal
# reply (real generated images come back from /image/generate as their own
# field, not inline markdown). This just catches any stray markdown image
# syntax that slips into a *text* reply so we never show a broken/fake image.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

def strip_stray_image_markdown(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    return _MD_IMAGE_RE.sub("", text).strip()


def call_openai(model: str, system: str, user_msg, history: list = []) -> Optional[str]:
    """user_msg can be a plain string, or a list of content blocks (for vision)."""
    try:
        messages = [{"role": "system", "content": system}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_msg})
        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": 0.7},
            timeout=60
        )
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("OPENAI ERROR:", e)
        return None


def generate_image(prompt: str, size: str = "1024x1024") -> Optional[str]:
    """Calls OpenAI's image generation API and returns base64 PNG data (no data-URI prefix)."""
    try:
        res = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": prompt, "size": size, "n": 1},
            timeout=90
        )
        data = res.json()
        return data["data"][0]["b64_json"]
    except Exception as e:
        print("IMAGE GEN ERROR:", e)
        return None


def edit_image(prompt: str, b64_image: str, mime: str = "image/png", size: str = "1024x1024") -> Optional[str]:
    """Calls OpenAI's image EDIT API (gpt-image-1) with the user's uploaded
    image + an edit instruction. Returns base64 PNG data (no data-URI prefix)."""
    try:
        import base64 as _b64
        raw = _b64.b64decode(b64_image)
        ext = "png" if "png" in (mime or "") else ("webp" if "webp" in (mime or "") else "jpg")
        res = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"image": (f"upload.{ext}", raw, mime or "image/png")},
            data={"model": "gpt-image-1", "prompt": prompt, "size": size, "n": "1"},
            timeout=90
        )
        data = res.json()
        return data["data"][0]["b64_json"]
    except Exception as e:
        print("IMAGE EDIT ERROR:", e)
        return None


_LETTERHEAD_CLASSIFIER_SYSTEM = """You are a strict content classifier for an AI image-editing tool.
Decide whether the user's edit request is asking to CREATE or EDIT an official
letterhead, letterheaded document, branded institutional document, certificate,
ID card, official seal/stamp, or any document/image meant to look like it was
issued by or represents a company, government office, bank, school, church,
NGO, or other institution/organization.

Answer "YES" if the request involves any of that, even loosely or partially
(e.g. "add our company logo and address to the top of this letter", "make this
look like an official bank document", "put a school stamp on this").

Answer "NO" only if it is clearly a personal photo edit with no institutional
document element — e.g. brightness/color/contrast adjustment, cropping,
background removal or change, retouching a face or object, resizing, adding a
filter, removing blemishes, restoring an old photo, whitening teeth, etc.

If genuinely unsure, answer "YES" (fail toward caution).
Reply with exactly one word: YES or NO. Nothing else."""

def classify_letterhead_request(prompt: str) -> bool:
    """Returns True if the edit request looks like it's asking for an
    institutional letterhead / official document rather than a personal
    photo touch-up. Fails safe (True = restricted) if the classifier errors."""
    result = call_openai("gpt-4o-mini", _LETTERHEAD_CLASSIFIER_SYSTEM, prompt)
    if not result:
        return True
    return result.strip().upper().startswith("Y")


IMAGE_BUCKET = "evosgpt-images"

def ensure_image_bucket():
    try:
        buckets = db_client.storage.list_buckets()
        if not any(b.name == IMAGE_BUCKET for b in buckets):
            db_client.storage.create_bucket(IMAGE_BUCKET, options={"public": True})
    except Exception as e:
        print("BUCKET SETUP WARNING:", e)

def upload_generated_image(user_id: int, b64_png: str) -> Optional[str]:
    try:
        import base64 as _b64
        raw = _b64.b64decode(b64_png)
        path = f"{user_id}/{uuid.uuid4().hex}.png"
        db_client.storage.from_(IMAGE_BUCKET).upload(
            path, raw, file_options={"content-type": "image/png"}
        )
        return db_client.storage.from_(IMAGE_BUCKET).get_public_url(path)
    except Exception as e:
        print("IMAGE UPLOAD ERROR:", e)
        return None


# =========================
# PDF / WORD DOCUMENT GENERATION
# =========================
DOCUMENT_BUCKET = "evosgpt-documents"

def ensure_document_bucket():
    try:
        buckets = db_client.storage.list_buckets()
        if not any(b.name == DOCUMENT_BUCKET for b in buckets):
            db_client.storage.create_bucket(DOCUMENT_BUCKET, options={"public": True})
    except Exception as e:
        print("DOCUMENT BUCKET SETUP WARNING:", e)

def upload_document(user_id: int, raw_bytes: bytes, ext: str, content_type: str) -> Optional[str]:
    try:
        path = f"{user_id}/{uuid.uuid4().hex}.{ext}"
        db_client.storage.from_(DOCUMENT_BUCKET).upload(
            path, raw_bytes, file_options={"content-type": content_type}
        )
        return db_client.storage.from_(DOCUMENT_BUCKET).get_public_url(path)
    except Exception as e:
        print("DOCUMENT UPLOAD ERROR:", e)
        return None


_DOCUMENT_CONTENT_SYSTEM = """You write clean, well-structured content for EVOSGPT's PDF/Word export tool.
Output ONLY the document content — no commentary, no markdown code fences, no asterisks for bold/italic.

Use this exact minimal markup so it lays out correctly on the page:
- A line starting with "# " = the document title (use exactly once, at the very top)
- A line starting with "## " = a section heading
- A line starting with "- " = a bullet list item
- A blank line = paragraph break
- Any other line = normal paragraph text (it will be justified on the page)

Keep it well-organized, concise, and professional. Do not include page numbers, headers,
footers, or a "Copy the above" style note — those don't apply here."""

def generate_document_content(prompt: str, title: Optional[str], username: str) -> Optional[str]:
    user_msg = prompt if not title else f"Title: {title}\n\n{prompt}"
    return call_openai("gpt-4o", _DOCUMENT_CONTENT_SYSTEM, f"Write this for {username}:\n\n{user_msg}")

def parse_doc_markup(text: str) -> list:
    """Turns the minimal markup above into [(kind, text), ...] blocks,
    kind in {'h1','h2','li','p'}."""
    blocks = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
        elif line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
        elif line.startswith("- "):
            blocks.append(("li", line[2:].strip()))
        else:
            blocks.append(("p", line))
    return blocks

def render_pdf_document(blocks: list, paper_size: str = DEFAULT_PAPER_SIZE) -> bytes:
    """Renders blocks to a PDF using reportlab, with even margins and
    justified body text so the layout sits centered/aligned on the page."""
    size_cfg = PAPER_SIZES.get(paper_size.upper(), PAPER_SIZES[DEFAULT_PAPER_SIZE])
    buf = BytesIO()
    margin = 2.2 * cm
    doc = SimpleDocTemplate(
        buf, pagesize=size_cfg["pdf"],
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin,
    )

    styles = getSampleStyleSheet()
    h1_style = ParagraphStyle("DocH1", parent=styles["Heading1"], alignment=TA_CENTER, fontSize=19, spaceAfter=16)
    h2_style = ParagraphStyle("DocH2", parent=styles["Heading2"], alignment=TA_LEFT, fontSize=14, spaceBefore=10, spaceAfter=8)
    body_style = ParagraphStyle("DocBody", parent=styles["Normal"], alignment=TA_JUSTIFY, fontSize=11, leading=16, spaceAfter=10)
    li_style = ParagraphStyle("DocLi", parent=body_style, leftIndent=6, spaceAfter=4)

    story = []
    list_buffer = []

    def flush_list():
        if list_buffer:
            story.append(ListFlowable(
                [ListItem(Paragraph(item, li_style)) for item in list_buffer],
                bulletType="bullet", start="•", leftIndent=18,
            ))
            story.append(Spacer(1, 8))
            list_buffer.clear()

    for kind, text in blocks:
        if kind == "li":
            list_buffer.append(text)
            continue
        flush_list()
        if kind == "h1":
            story.append(Paragraph(text, h1_style))
        elif kind == "h2":
            story.append(Paragraph(text, h2_style))
        else:
            story.append(Paragraph(text, body_style))
    flush_list()

    doc.build(story)
    return buf.getvalue()

def render_docx_document(blocks: list, paper_size: str = DEFAULT_PAPER_SIZE) -> bytes:
    """Renders blocks to a .docx using python-docx, with the page size,
    even margins, and paragraph justification set explicitly so it lines
    up the same way regardless of the reader's default Word template."""
    size_cfg = PAPER_SIZES.get(paper_size.upper(), PAPER_SIZES[DEFAULT_PAPER_SIZE])
    width_cm, height_cm = size_cfg["docx_cm"]

    doc = DocxDocument()
    section = doc.sections[0]
    section.page_width  = Cm(width_cm)
    section.page_height = Cm(height_cm)
    margin = Cm(2.2)
    section.left_margin = section.right_margin = margin
    section.top_margin = section.bottom_margin = margin

    for kind, text in blocks:
        if kind == "h1":
            p = doc.add_heading(text, level=1)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif kind == "h2":
            doc.add_heading(text, level=2)
        elif kind == "li":
            doc.add_paragraph(text, style="List Bullet")
        else:
            p = doc.add_paragraph(text)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            for run in p.runs:
                run.font.size = Pt(11)

    out = BytesIO()
    doc.save(out)
    return out.getvalue()

def build_system_prompt(tier: str, long_memory: Optional[str], username: str, geo: Optional[dict] = None) -> str:
    prompt = BASE_PROMPT + TIER_PERSONA.get(tier, TIER_PERSONA["Basic"]) + EVOS_NUDGE
    prompt += f"\n\nThe user's name is {username}."
    if tier in IMAGE_GEN_TIERS:
        prompt += " This user's tier includes access to the 🎨 image-generation button."
    else:
        prompt += " This user is on Basic tier: image generation is NOT available to them until they upgrade to Pro."

    if geo and geo.get("local_time"):
        location_str = ", ".join(filter(None, [geo.get("city"), geo.get("country")]))
        prompt += f"\n\nThe user's current local time is {geo['local_time']}"
        if location_str:
            prompt += f", and they appear to be located in {location_str}."
        else:
            prompt += "."
        prompt += " Use this naturally when it's relevant (greetings, deadlines, scheduling, local context, time-sensitive answers). Don't mention that you're using IP-based geolocation unless the user asks how you know."

    cur = _currency.currency_for_country((geo or {}).get("country_code"))
    prompt += (f"\n\nThe user's local currency is {cur['currency']}. When you mention prices or money, "
               f"use {cur['currency']} unless the user asks for another currency. Do not invent exchange rates.")

    if long_memory:
        prompt += f"\n\nWhat you know about this user from past conversations:\n{long_memory}"
    return prompt

def summarize_memory(history: list) -> Optional[str]:
    if len(history) < 4:
        return None
    convo = "\n".join([f"{h['role'].capitalize()}: {h['content']}" for h in history[-10:]])
    return call_openai("gpt-4o-mini", "You are a memory summarizer for an AI assistant. Be concise.",
        f"Summarize this conversation in 2-3 sentences. Focus on the user's goals, skills, and key topics:\n\n{convo}")


@router.post("/auth/register")
@limiter.limit("10/minute")
def register(request: Request, data: RegisterRequest):
    try:
        username  = data.username.strip().lower()
        email     = data.email.strip().lower()
        full_name = data.full_name.strip()
        phone     = (data.phone or "").strip()

        if len(username) < 3:
            raise HTTPException(400, "Username must be at least 3 characters")
        if len(data.password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")

        if db_client.table("users").select("id").eq("username", username).limit(1).execute().data:
            return {"status": "username_taken"}
        if db_client.table("users").select("id").eq("email", email).limit(1).execute().data:
            return {"status": "email_taken"}

        try:
            hashed_password = hash_password(data.password)
        except Exception as e:
            print("HASH ERROR:", e)
            raise HTTPException(500, "Password hashing failed")

        referral_code = generate_referral_code(username)

        res = db_client.table("users").insert({
            "username":      username,
            "full_name":     full_name,
            "email":         email,
            "phone":         phone,
            "password":      hashed_password,
            "referral_code": referral_code,
            "referred_by":   data.referred_by or None,
            "evosgpt_tier":  "Basic",
            "role":          "customer",
            "created_at":    datetime.now(timezone.utc).isoformat(),
        }).execute()

        if not res.data:
            raise HTTPException(500, "Registration failed")

        user = res.data[0]

        if data.referred_by:
            try:
                ref = db_client.table("users").select("id,order_count").eq("referral_code", data.referred_by).limit(1).execute()
                if ref.data:
                    db_client.table("users").update({
                        "order_count": (ref.data[0].get("order_count") or 0) + 1
                    }).eq("id", ref.data[0]["id"]).execute()
            except Exception as e:
                print("REFERRAL ERROR:", e)

        return {
            "status": "created",
            "user": {
                "id":            user["id"],
                "username":      user["username"],
                "full_name":     user["full_name"],
                "email":         user["email"],
                "evosgpt_tier":  "Basic",
                "referral_code": referral_code,
                "user_token":    _issue_token(user["id"]),
            }
        }
    except HTTPException: raise
    except Exception as e:
        print("REGISTER ERROR:", e)
        raise HTTPException(500, "Server error")


@router.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest):
    try:
        identifier = (data.username or "").strip().lower()
        if not identifier:
            raise HTTPException(400, "Username required")
        # The identifier goes into a PostgREST filter string: only plain username/email characters.
        if not _IDENTIFIER_RE.match(identifier):
            return {"status": "invalid_credentials"}

        res = db_client.table("users").select("*").or_(
            f"username.eq.{identifier},email.eq.{identifier}"
        ).limit(1).execute()

        # Timing-safe: always run verify even if user not found
        dummy_hash = "$2b$12$KIXzCq3C3T6tFkUd9nj6aO.WwSIFqh4fQieFzpxKx5Mj5.z1rklHC"
        stored_password = res.data[0].get("password") if res.data else dummy_hash

        try:
            password_ok = verify_password(data.password, stored_password)
        except Exception:
            password_ok = False

        if not res.data or not password_ok:
            return {"status": "invalid_credentials"}

        user = res.data[0]

        return {
            "status": "ok",
            "user": {
                "id":            user["id"],
                "username":      user["username"],
                "full_name":     user.get("full_name", ""),
                "email":         user["email"],
                "evosgpt_tier":  user.get("evosgpt_tier", "Basic"),
                "referral_code": user.get("referral_code", ""),
                "role":          user.get("role", "user"),
                "user_token":    _issue_token(user["id"]),
            }
        }
    except HTTPException: raise
    except Exception as e:
        print("LOGIN ERROR:", e)
        raise HTTPException(500, "Server error")

@router.post("/chat")
def chat(data: ChatRequest, request: Request):
    try:
        require_user(request, data.user_id)
        user_id = data.user_id
        message = data.message.strip()
        if not message:
            raise HTTPException(400, "Message cannot be empty")

        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")

        tier     = user.get("evosgpt_tier", "Basic")
        username = user.get("username", "friend")
        tier_cfg = TIERS.get(tier, TIERS["Basic"])
        model     = tier_cfg["model"]
        mem_limit = tier_cfg["memory_limit"]
        day_limit = tier_cfg["day_limit"]

        today_count        = get_today_count(user_id)
        show_upgrade_nudge = False

        if day_limit is not None and today_count >= day_limit:
            return {
                "status": "limit_reached",
                "reply": f"You've used all {day_limit} free chats for today. Come back tomorrow or upgrade to Pro for unlimited chats!",
                "tier": tier, "limit_reached": True,
                "today_count": today_count, "day_limit": day_limit,
            }

        if day_limit is not None and today_count in [4, 7]:
            show_upgrade_nudge = True

        geo           = get_geo_context(request)
        short_memory  = get_short_memory(user_id, limit=mem_limit)
        long_memory   = get_long_memory(user_id)
        system_prompt = build_system_prompt(tier, long_memory, username, geo)

        if data.image_base64:
            user_content = [
                {"type": "text", "text": message or "What's in this image?"},
                {"type": "image_url", "image_url": {"url": f"data:{data.image_mime or 'image/jpeg'};base64,{data.image_base64}"}},
            ]
            # Vision models need gpt-4o (or mini); both tiers already map to a vision-capable model.
            reply = call_openai(model, system_prompt, user_content, short_memory)
        else:
            reply = call_openai(model, system_prompt, message, short_memory)

        if not reply:
            raise HTTPException(500, "AI service unavailable. Try again.")
        reply = strip_stray_image_markdown(reply)

        # Store a text-only record in memory (images aren't persisted into long-term history).
        stored_user_msg = message if not data.image_base64 else f"[Image uploaded] {message}".strip()
        save_message(user_id, "user", stored_user_msg)
        save_message(user_id, "assistant", reply)
        trim_memory(user_id, mem_limit)
        increment_today_count(user_id)

        total = len(short_memory) + 1
        if total % 10 == 0:
            summary = summarize_memory(short_memory)
            if summary:
                update_long_memory(user_id, summary)

        return {
            "status": "ok", "reply": reply, "tier": tier, "model": model,
            "today_count": today_count + 1, "day_limit": day_limit,
            "show_upgrade_nudge": show_upgrade_nudge,
            "location": {
                "city": geo.get("city", ""),
                "country": geo.get("country", ""),
                "timezone": geo.get("timezone", "UTC"),
                "local_time": geo.get("local_time", ""),
            },
        }
    except HTTPException: raise
    except Exception as e:
        print("CHAT ERROR:", e)
        raise HTTPException(500, "Chat failed")


@router.post("/image/generate")
def image_generate(data: ImageGenRequest, request: Request):
    try:
        require_user(request, data.user_id)
        user_id = data.user_id
        prompt  = data.prompt.strip()
        if not prompt:
            raise HTTPException(400, "Prompt cannot be empty")

        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")

        tier = user.get("evosgpt_tier", "Basic")
        if tier not in IMAGE_GEN_TIERS:
            return {
                "status": "tier_restricted",
                "reply": "Image generation is a Pro-tier feature. Upgrade to unlock it!",
                "tier": tier,
            }

        tier_cfg  = TIERS.get(tier, TIERS["Basic"])
        day_limit = tier_cfg["day_limit"]
        today_count = get_today_count(user_id)
        if day_limit is not None and today_count >= day_limit:
            return {
                "status": "limit_reached",
                "reply": f"You've used all {day_limit} free chats for today. Come back tomorrow or upgrade for unlimited chats!",
                "tier": tier, "limit_reached": True,
                "today_count": today_count, "day_limit": day_limit,
            }

        b64_png = generate_image(prompt)
        if not b64_png:
            raise HTTPException(500, "Image generation failed. Try again.")

        image_url = upload_generated_image(user_id, b64_png)
        if not image_url:
            raise HTTPException(500, "Image was generated but could not be saved. Try again.")

        reply = f"![Generated image]({image_url})\n\n*Prompt: {prompt}*"

        save_message(user_id, "user", f"[Image generation request] {prompt}")
        save_message(user_id, "assistant", reply)
        increment_today_count(user_id)

        return {
            "status": "ok", "reply": reply, "image_url": image_url,
            "tier": tier, "today_count": today_count + 1, "day_limit": day_limit,
        }
    except HTTPException: raise
    except Exception as e:
        print("IMAGE ENDPOINT ERROR:", e)
        raise HTTPException(500, "Image generation failed")


@router.post("/image/edit")
def image_edit(data: ImageEditRequest, request: Request):
    try:
        require_user(request, data.user_id)
        user_id = data.user_id
        prompt  = data.prompt.strip()
        if not prompt:
            raise HTTPException(400, "Describe the edit you want")
        if not data.image_base64:
            raise HTTPException(400, "No image provided to edit")

        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")

        tier = user.get("evosgpt_tier", "Basic")
        if tier not in IMAGE_GEN_TIERS:
            return {
                "status": "tier_restricted",
                "reply": "Image editing is a Pro-tier feature. Upgrade to unlock it!",
                "tier": tier,
            }

        # Institutional-letterhead safety gate: only Founder tier may create
        # or edit letterheaded / official institutional documents, to guard
        # against impersonation or document fraud. A user editing their own
        # personal photo (brightness, crop, retouch, background, etc.) is
        # unaffected by this and stays gated only by IMAGE_GEN_TIERS above.
        if tier != LETTERHEAD_ALLOWED_TIER and classify_letterhead_request(prompt):
            return {
                "status": "letterhead_restricted",
                "reply": (
                    "I can't create or edit official letterheads or institutional documents "
                    "(company, school, bank, government, church, NGO, etc.) outside Founder tier — "
                    "that's to prevent impersonation and document fraud. If you're actually editing "
                    "your own personal photo (brightness, cropping, background, retouching, and so on), "
                    "just rephrase it that way and I'll go ahead."
                ),
                "tier": tier,
            }

        tier_cfg  = TIERS.get(tier, TIERS["Basic"])
        day_limit = tier_cfg["day_limit"]
        today_count = get_today_count(user_id)
        if day_limit is not None and today_count >= day_limit:
            return {
                "status": "limit_reached",
                "reply": f"You've used all {day_limit} free chats for today. Come back tomorrow or upgrade for unlimited chats!",
                "tier": tier, "limit_reached": True,
                "today_count": today_count, "day_limit": day_limit,
            }

        b64_png = edit_image(prompt, data.image_base64, data.image_mime or "image/png")
        if not b64_png:
            raise HTTPException(500, "Image edit failed. Try again.")

        image_url = upload_generated_image(user_id, b64_png)
        if not image_url:
            raise HTTPException(500, "Image was edited but could not be saved. Try again.")

        reply = f"![Edited image]({image_url})\n\n*Edit: {prompt}*"

        save_message(user_id, "user", f"[Image edit request] {prompt}")
        save_message(user_id, "assistant", reply)
        increment_today_count(user_id)

        return {
            "status": "ok", "reply": reply, "image_url": image_url,
            "tier": tier, "today_count": today_count + 1, "day_limit": day_limit,
        }
    except HTTPException: raise
    except Exception as e:
        print("IMAGE EDIT ENDPOINT ERROR:", e)
        raise HTTPException(500, "Image edit failed")


@router.post("/document/generate")
def document_generate(data: DocumentGenRequest, request: Request):
    try:
        require_user(request, data.user_id)
        user_id = data.user_id
        prompt  = data.prompt.strip()
        if not prompt:
            raise HTTPException(400, "Describe the document you want")

        doc_format = (data.doc_format or "pdf").lower()
        if doc_format not in ("pdf", "docx"):
            raise HTTPException(400, "doc_format must be 'pdf' or 'docx'")

        paper_size = (data.paper_size or DEFAULT_PAPER_SIZE).upper()
        if paper_size not in PAPER_SIZES:
            paper_size = DEFAULT_PAPER_SIZE

        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")

        tier = user.get("evosgpt_tier", "Basic")
        if tier not in DOCUMENT_GEN_TIERS:
            return {
                "status": "tier_restricted",
                "reply": "PDF/Word document generation is a Pro-tier feature. Upgrade to unlock it!",
                "tier": tier,
            }

        # Same institutional-letterhead safety gate as image editing — a
        # letterhead is most often literally a PDF/Word document, so it's
        # gated here too. A personal document (CV, personal letter, notes,
        # a report the user is writing themselves) is unaffected.
        if tier != LETTERHEAD_ALLOWED_TIER and classify_letterhead_request(prompt):
            return {
                "status": "letterhead_restricted",
                "reply": (
                    "I can't generate an official letterhead or institutional document "
                    "(company, school, bank, government, church, NGO, etc.) outside Founder "
                    "tier — that's to prevent impersonation and document fraud. Personal "
                    "documents (a CV, a personal letter, notes, a report you're writing "
                    "yourself) are fine — just rephrase it that way and I'll go ahead."
                ),
                "tier": tier,
            }

        tier_cfg  = TIERS.get(tier, TIERS["Basic"])
        day_limit = tier_cfg["day_limit"]
        today_count = get_today_count(user_id)
        if day_limit is not None and today_count >= day_limit:
            return {
                "status": "limit_reached",
                "reply": f"You've used all {day_limit} free chats for today. Come back tomorrow or upgrade for unlimited chats!",
                "tier": tier, "limit_reached": True,
                "today_count": today_count, "day_limit": day_limit,
            }

        username = user.get("username", "there")
        content = generate_document_content(prompt, data.title, username)
        if not content:
            raise HTTPException(500, "Document generation failed. Try again.")

        blocks = parse_doc_markup(content)
        if not blocks:
            raise HTTPException(500, "Document generation failed. Try again.")

        title_text = data.title or next((t for k, t in blocks if k == "h1"), "Document")

        try:
            if doc_format == "pdf":
                raw = render_pdf_document(blocks, paper_size)
                ext, content_type = "pdf", "application/pdf"
            else:
                raw = render_docx_document(blocks, paper_size)
                ext, content_type = "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except Exception as e:
            print("DOCUMENT RENDER ERROR:", e)
            raise HTTPException(500, "Document formatting failed. Try again.")

        doc_url = upload_document(user_id, raw, ext, content_type)
        if not doc_url:
            raise HTTPException(500, "Document was generated but could not be saved. Try again.")

        reply = f"📄 **{title_text}** — [Download {doc_format.upper()} ({paper_size})]({doc_url})"

        save_message(user_id, "user", f"[Document generation request: {doc_format.upper()}/{paper_size}] {prompt}")
        save_message(user_id, "assistant", reply)
        increment_today_count(user_id)

        return {
            "status": "ok", "reply": reply, "document_url": doc_url,
            "doc_format": doc_format, "paper_size": paper_size,
            "tier": tier, "today_count": today_count + 1, "day_limit": day_limit,
        }
    except HTTPException: raise
    except Exception as e:
        print("DOCUMENT ENDPOINT ERROR:", e)
        raise HTTPException(500, "Document generation failed")


@router.get("/memory/{user_id}")
def get_memory(user_id: int, request: Request):
    require_user(request, user_id)
    try:
        return {"status": "ok", "short_memory": get_short_memory(user_id, 50), "long_memory": get_long_memory(user_id)}
    except Exception:
        raise HTTPException(500, "Failed to fetch memory")

@router.delete("/memory/{user_id}")
def clear_memory(user_id: int, request: Request):
    require_user(request, user_id)
    try:
        db_client.table("evosgpt_memory").delete().eq("user_id", user_id).execute()
        db_client.table("evosgpt_long_memory").delete().eq("user_id", user_id).execute()
        return {"status": "ok", "message": "Memory cleared. EVOSGPT starts fresh."}
    except Exception:
        raise HTTPException(500, "Failed to clear memory")


@router.get("/user/{user_id}")
def get_user(user_id: int, request: Request):
    require_user(request, user_id)
    try:
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")

        tier_cfg    = TIERS.get(user.get("evosgpt_tier", "Basic"), TIERS["Basic"])
        today_count = get_today_count(user_id)
        mem_count   = db_client.table("evosgpt_memory").select("id", count="exact").eq("user_id", user_id).execute()
        long_mem    = get_long_memory(user_id)

        return {
            "status": "ok",
            "user": {
                "id": user["id"], "username": user["username"], "full_name": user.get("full_name", ""),
                "email": user["email"], "evosgpt_tier": user.get("evosgpt_tier", "Basic"),
                "referral_code": user.get("referral_code", ""),
                "today_count": today_count, "day_limit": tier_cfg["day_limit"],
                "mem_count": mem_count.count or 0,
                "has_long_mem": long_mem is not None, "long_memory": long_mem,
            }
        }
    except HTTPException: raise
    except Exception:
        raise HTTPException(500, "Failed to fetch user")


@router.get("/geo")
def geo_check(request: Request):
    """Quick utility endpoint to test/debug geolocation + local time detection."""
    try:
        return {"status": "ok", "geo": get_geo_context(request)}
    except Exception as e:
        print("GEO CHECK ERROR:", e)
        raise HTTPException(500, "Failed to detect location")


def _apply_paid(reference: str, user_id: int, tier: str) -> str:
    """Idempotent: mark the purchase paid and set the tier. Returns 'success' or 'already_processed'."""
    existing = db_client.table("evosgpt_purchases").select("status").eq("reference", reference).limit(1).execute()
    if existing.data and existing.data[0]["status"] == "paid":
        return "already_processed"
    db_client.table("users").update({"evosgpt_tier": tier}).eq("id", user_id).execute()
    db_client.table("evosgpt_purchases").update({"status": "paid"}).eq("reference", reference).execute()
    logger.info("EVOSGPT: user %s upgraded to %s (ref %s)", user_id, tier, reference)
    return "success"


@router.post("/upgrade/init")
def init_upgrade(data: UpgradeRequest, request: Request):
    try:
        require_user(request, data.user_id)
        if data.tier not in PURCHASABLE_TIERS:
            raise HTTPException(400, "Invalid tier")
        if not PAYSTACK_SECRET:
            raise HTTPException(503, "Payments are not configured")

        user = get_user_by_id(data.user_id)
        if not user:
            raise HTTPException(404, "User not found")
        email = user.get("email") or data.email   # the account's own email, not whatever the browser sent

        tier_cfg   = TIERS[data.tier]
        reference  = f"EVOS-GPT-{data.user_id}-{uuid.uuid4().hex[:8].upper()}"
        amount_ghs = tier_cfg["price_ghs"]

        # Billing is always in GHS (the Paystack account currency). The app only DISPLAYS
        # the visitor's local currency; see services/evosgpt/currency.py.
        paystack_res = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
            json={
                "email": email, "amount": int(amount_ghs * 100), "currency": "GHS",
                "reference": reference, "callback_url": f"{EVOSGPT_APP_URL}?upgrade=success&reference={reference}",
                "metadata": {"user_id": data.user_id, "tier": data.tier, "product": "evosgpt"},
            }, timeout=15
        )
        paystack = paystack_res.json()

        if not paystack.get("status"):
            raise HTTPException(400, paystack.get("message", "Payment initialization failed"))

        db_client.table("evosgpt_purchases").insert({
            "user_id": data.user_id, "tier": data.tier, "reference": reference,
            "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        return {"status": "ok", "payment_url": paystack["data"]["authorization_url"], "reference": reference,
                "billing_currency": "GHS", "billing_amount": amount_ghs}
    except HTTPException: raise
    except Exception as e:
        print("UPGRADE ERROR:", e)
        raise HTTPException(500, "Upgrade failed")


@router.get("/upgrade/verify/{reference}")
def verify_upgrade(reference: str, request: Request):
    """
    Called by the app when Paystack sends the customer back. Confirms the payment with
    Paystack directly and upgrades the account, so the upgrade does not depend on which
    webhook URL the (shared) Paystack account points at.
    """
    try:
        if not re.match(r"^EVOS-GPT-\d+-[A-F0-9]{8}$", reference):
            raise HTTPException(400, "Invalid reference")
        row = db_client.table("evosgpt_purchases").select("*").eq("reference", reference).limit(1).execute()
        if not row.data:
            raise HTTPException(404, "Purchase not found")
        purchase = row.data[0]
        require_user(request, purchase["user_id"])
        if purchase["status"] == "paid":
            return {"status": "ok", "paid": True, "tier": purchase["tier"]}
        if not PAYSTACK_SECRET:
            raise HTTPException(503, "Payments are not configured")

        res = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}, timeout=15,
        ).json()
        d = res.get("data") or {}
        expected_pesewas = int(TIERS[purchase["tier"]]["price_ghs"] * 100)
        if (res.get("status") and d.get("status") == "success"
                and d.get("currency") == "GHS" and int(d.get("amount", 0)) >= expected_pesewas):
            _apply_paid(reference, purchase["user_id"], purchase["tier"])
            return {"status": "ok", "paid": True, "tier": purchase["tier"]}
        return {"status": "ok", "paid": False}
    except HTTPException: raise
    except Exception as e:
        print("UPGRADE VERIFY ERROR:", e)
        raise HTTPException(500, "Could not verify payment")


# Own name, so it can never be confused with EVOS Data's /webhook/paystack. The old path stays as an alias.
@router.post("/webhook/evosgpt-paystack")
@router.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    try:
        if not PAYSTACK_SECRET:
            return {"status": "not_configured"}
        body      = await request.body()
        signature = request.headers.get("x-paystack-signature", "")
        computed  = hmac.new(PAYSTACK_SECRET.encode(), body, hashlib.sha512).hexdigest()

        if not hmac.compare_digest(computed, signature):
            return {"status": "invalid_signature"}

        payload = await request.json()
        if payload.get("event") != "charge.success":
            return {"status": "ignored"}

        data      = payload["data"]
        reference = data["reference"]
        meta      = data.get("metadata", {})
        user_id   = meta.get("user_id")
        tier      = meta.get("tier")

        if not user_id or not tier:
            return {"status": "missing_metadata"}
        if tier not in PURCHASABLE_TIERS:
            return {"status": "invalid_tier"}

        return {"status": _apply_paid(reference, user_id, tier)}
    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return {"status": "error"}


# =========================
# CURRENCY (default GHS; follows the visitor's country)
# =========================
@router.get("/currency")
def visitor_currency(request: Request, country: Optional[str] = None):
    """
    Display currency for the visitor. `country` (ISO code) may be passed by the frontend when
    the hosting edge already detected it; otherwise the visitor's IP is looked up here.
    A VPN exit country counts, because both paths are IP-based.
    Returns the GHS price multiplier ("rate") for that currency; billing stays in GHS.
    """
    code = (country or "").strip().upper()
    if not re.match(r"^[A-Z]{2}$", code):
        code = (get_geo_context(request).get("country_code") or "").upper()
    info = _currency.currency_for_country(code)
    return {"status": "ok", **info, "tiers_ghs": {k: v["price_ghs"] for k, v in TIERS.items() if k in PURCHASABLE_TIERS}}


# =========================
# HUB SESSION -> EVOSGPT ACCOUNT (central login)
# =========================
@router.post("/auth/hub-session")
@limiter.limit("30/minute")
def hub_session(request: Request, authorization: str = Header(default="")):
    """Exchange a valid Hub session token for the EVOSGPT user object (no second login)."""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        uid = int(verify_user_token(token))
    except (XeraTokenInvalid, RuntimeError, ValueError):
        raise HTTPException(401, "Session expired. Please sign in again.")
    user = get_user_by_id(uid)
    if not user:
        raise HTTPException(401, "Session expired. Please sign in again.")
    return {"status": "ok", "user": {
        "id": user["id"], "username": user["username"], "full_name": user.get("full_name", ""),
        "email": user["email"], "evosgpt_tier": user.get("evosgpt_tier", "Basic"),
        "referral_code": user.get("referral_code", ""), "role": user.get("role", "user"),
        "user_token": token,
    }}


@router.post("/coupon/redeem")
def redeem_coupon(data: CouponRequest, request: Request):
    require_user(request, data.user_id)
    try:
        code = data.code.strip().upper()
        res  = db_client.table("evosgpt_coupons").select("*").eq("code", code).limit(1).execute()

        if not res.data:
            return {"status": "invalid", "message": "Invalid coupon code."}

        coupon = res.data[0]
        if coupon["used"]:
            return {"status": "used", "message": "This coupon has already been used."}

        db_client.table("users").update({"evosgpt_tier": coupon["tier"]}).eq("id", data.user_id).execute()
        db_client.table("evosgpt_coupons").update({"used": True, "used_by": data.user_id}).eq("code", code).execute()

        return {"status": "ok", "message": f"Welcome to {coupon['tier']} tier!", "tier": coupon["tier"]}
    except Exception as e:
        print("COUPON ERROR:", e)
        raise HTTPException(500, "Coupon redemption failed")


@router.get("/referral/{user_id}")
def get_referral(user_id: int, request: Request):
    require_user(request, user_id)
    try:
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")
        return {
            "status": "ok", "referral_code": user["referral_code"],
            "referral_count": user.get("order_count", 0),
            "referral_link": f"{EVOSGPT_APP_URL}?ref={user['referral_code']}",
        }
    except HTTPException: raise
    except Exception:
        raise HTTPException(500, "Failed")


@router.api_route("/", methods=["GET", "HEAD"])
def health(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    return {"status": "ok", "service": "EVOSGPT API", "version": "2.0", "ecosystem": "EVOS Business Hub", "powered_by": "Evoxera Technology"}
