import os, json, re, base64, asyncio, logging, errno
from pathlib import Path
import shutil
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from datetime import datetime

logger = logging.getLogger("mam_audiofinder")

# ---------------------------- Config ----------------------------
DOWNLOADS_DIR = "/downloads"
LIBRARY_DIR = "/library"
EBOOKS_DIR = "/ebooks"
EBOOKS_NOSEND_DIR = "/ebooks-nosend"
DEFAULT_AUTO_IMPORT_POLL_INTERVAL = 30
DEFAULT_MAM_BASE = "https://www.myanonamouse.net"
DEFAULT_TRANSMISSION_LABEL = "mam-audiofinder"
TRANSMISSION_NOSEND_LABEL = "kindle-nosend"
DEFAULT_UMASK = "0002"
MEDIA_TYPE_AUDIOBOOK = "audiobook"
MEDIA_TYPE_EBOOK = "ebook"
MAM_MAIN_CATEGORIES = {
    MEDIA_TYPE_AUDIOBOOK: "13",
    MEDIA_TYPE_EBOOK: "14",
}

APP_VERSION = os.getenv("APP_VERSION", "unknown")

def is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")

def build_mam_cookie(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    # If user pasted full cookie header, use it as-is
    if "mam_id=" in raw or "mam_session=" in raw:
        return raw
    # If ASN single-token was pasted, wrap it
    if raw and "=" not in raw and ";" not in raw:
        return f"mam_id={raw}"
    return raw

def normalize_media_type(value: str | None) -> str:
    media_type = (value or MEDIA_TYPE_AUDIOBOOK).strip().lower()
    if media_type in ("audiobook", "audiobooks", "audio"):
        return MEDIA_TYPE_AUDIOBOOK
    if media_type in ("ebook", "ebooks", "e-book", "e-books"):
        return MEDIA_TYPE_EBOOK
    raise HTTPException(status_code=400, detail="media_type must be audiobook or ebook")

class Settings:
    def __init__(self) -> None:
        self.MAM_BASE = DEFAULT_MAM_BASE
        self.MAM_COOKIE = build_mam_cookie(os.getenv("MAM_COOKIE", ""))
        if not self.MAM_COOKIE:
            raise RuntimeError("MAM_COOKIE environment variable is required and must be set to a non-empty value")
        self.TRANSMISSION_URL = os.getenv("TRANSMISSION_URL", "http://transmission:9091/transmission/rpc").rstrip("/")
        self.TRANSMISSION_USER = os.getenv("TRANSMISSION_USER", "")
        self.TRANSMISSION_PASS = os.getenv("TRANSMISSION_PASS", "")
        self.TRANSMISSION_LABEL = DEFAULT_TRANSMISSION_LABEL
        self.DOWNLOADS_DIR = DOWNLOADS_DIR
        self.LIBRARY_DIR = LIBRARY_DIR
        self.EBOOKS_DIR = EBOOKS_DIR
        self.EBOOKS_NOSEND_DIR = EBOOKS_NOSEND_DIR

        self.UMASK = DEFAULT_UMASK
        self.AUTO_IMPORT_POLL_INTERVAL = DEFAULT_AUTO_IMPORT_POLL_INTERVAL

settings = Settings()

# apply UMASK for created files/dirs
_um = settings.UMASK
if _um:
    try:
        os.umask(int(_um, 8))
    except Exception:
        pass

# ---------------------------- DB ----------------------------
# /data should be a volume/bind mount. Override with HISTORY_DB_URL for tests.
HISTORY_DB_URL = os.getenv("HISTORY_DB_URL", "sqlite:////data/history.db")
engine = create_engine(HISTORY_DB_URL, future=True)

def utcnow_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def ensure_history_schema() -> None:
    with engine.begin() as cx:
        cx.execute(text("""
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY,
              mam_id   TEXT,
              title    TEXT,
              author   TEXT,
              narrator TEXT,
              media_type TEXT,
              dl       TEXT,
              added_at TEXT DEFAULT (datetime('now')),
              imported_at TEXT,
              torrent_status TEXT,
              torrent_hash   TEXT
            )
        """))
        cols = {row["name"] for row in cx.execute(text("PRAGMA table_info(history)")).mappings()}
        if "status_detail" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN status_detail TEXT"))
        if "status_updated_at" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN status_updated_at TEXT"))
        if "media_type" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN media_type TEXT"))
        if "send_to_kindle" not in cols:
            cx.execute(text("ALTER TABLE history ADD COLUMN send_to_kindle INTEGER DEFAULT 1"))
        cx.execute(text("""
            UPDATE history
            SET media_type = 'audiobook'
            WHERE media_type IS NULL OR trim(media_type) = ''
        """))
        cx.execute(text("""
            UPDATE history
            SET send_to_kindle = 1
            WHERE send_to_kindle IS NULL
        """))
        cx.execute(text("""
            UPDATE history
            SET torrent_status = 'added'
            WHERE torrent_status IS NULL OR trim(torrent_status) = ''
        """))
        cx.execute(text("""
            UPDATE history
            SET status_updated_at = COALESCE(status_updated_at, imported_at, added_at)
            WHERE status_updated_at IS NULL
        """))

ensure_history_schema()

def mam_headers(*, torrent: bool = False) -> dict:
    headers = {
        "Cookie": settings.MAM_COOKIE,
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.myanonamouse.net/",
        "Origin": "https://www.myanonamouse.net",
    }
    if torrent:
        headers["Accept"] = "application/x-bittorrent, */*"
    else:
        headers["Accept"] = "application/json, text/plain, */*"
    return headers

async def fetch_account_summary(client: httpx.AsyncClient) -> dict:
    resp = await client.get(f"{settings.MAM_BASE}/jsonLoad.php", headers=mam_headers())
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"MAM account summary failed: {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="MAM account summary returned non-JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="MAM account summary returned unexpected data")
    return data

async def fetch_freeleech_wedge_count(client: httpx.AsyncClient) -> int | None:
    data = await fetch_account_summary(client)
    wedges = data.get("wedges")
    if wedges is None:
        return None
    try:
        value = int(wedges)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None

def mam_account_is_authenticated(data: dict) -> bool:
    """Return whether the MAM account response represents a logged-in user."""
    uid = data.get("uid")
    return uid is not None and str(uid).strip() != ""

# ---------------------------- App ----------------------------
app = FastAPI(title="MAM Book Finder", version=APP_VERSION)
app.state.auto_import_task = None
app.state.auto_import_stop = None

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/health/mam")
async def mam_health():
    """Perform a bounded, read-only check that the configured MAM cookie works."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            data = await fetch_account_summary(client)
    except HTTPException as exc:
        logger.warning("MAM health check failed: %s", exc.detail)
        return JSONResponse(status_code=503, content={"status": "unhealthy"})
    except httpx.HTTPError as exc:
        logger.warning("MAM health check request failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "unhealthy"})

    if not mam_account_is_authenticated(data):
        logger.warning("MAM health check returned an unauthenticated account response")
        return JSONResponse(status_code=503, content={"status": "unhealthy"})

    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "app_version": APP_VERSION},
    )

# ---------------------------- Search ----------------------------
@app.post("/search")
async def search(payload: dict):
    media_type = normalize_media_type(payload.get("media_type"))
    tor = payload.get("tor", {}) or {}
    tor.setdefault("text", "")
    if media_type == MEDIA_TYPE_EBOOK:
        tor.setdefault("srchIn", ["title", "author"])
    else:
        tor.setdefault("srchIn", ["title", "author", "narrator"])
    tor.setdefault("searchType", "all")
    tor["sortType"] = "seedersDesc"
    tor.setdefault("startNumber", "0")
    tor["main_cat"] = [MAM_MAIN_CATEGORIES[media_type]]

    perpage = payload.get("perpage", 25)
    body = {"tor": tor, "perpage": perpage}

    headers = {
        "Cookie": settings.MAM_COOKIE,
        "Content-Type": "application/json",
        "Accept": "application/json, */*",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.myanonamouse.net",
        "Referer": "https://www.myanonamouse.net/",
    }
    params = {"dlLink": "1"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{settings.MAM_BASE}/tor/js/loadSearchJSONbasic.php",
                                  headers=headers, params=params, json=body)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"MAM request failed: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"MAM HTTP {r.status_code}: {r.text[:300]}")
    try:
        raw = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"MAM returned non-JSON. Body: {r.text[:300]}")

    async with httpx.AsyncClient(timeout=30) as client:
        freeleech_wedges = await fetch_freeleech_wedge_count(client)

    def flatten(v):
        # {"8320":"John Steinbeck"} or JSON-string -> "John Steinbeck"
        if isinstance(v, dict):
            return ", ".join(str(x) for x in v.values())
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("{") or s.startswith("["):
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict):
                        return ", ".join(str(x) for x in obj.values())
                    if isinstance(obj, list):
                        return ", ".join(str(x) for x in obj)
                except Exception:
                    pass
            s = re.sub(r'^\{|\}$', '', s)
            parts = []
            for chunk in s.split(","):
                parts.append(chunk.split(":", 1)[-1])
            parts = [p.strip().strip('"').strip("'") for p in parts if p.strip()]
            return ", ".join(parts)
        return "" if v is None else str(v)

    def detect_format(item: dict) -> str:
        for key in ("format", "filetype", "container", "encoding", "format_name"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        name = (item.get("title") or item.get("name") or "")
        toks = re.findall(r'(?i)\b(mp3|m4b|flac|aac|ogg|opus|wav|alac|ape|epub|pdf|mobi|azw3|cbz|cbr)\b', name)
        if toks:
            uniq = list(dict.fromkeys(t.upper() for t in toks))
            return "/".join(uniq)
        return ""

    out = []
    for item in raw.get("data", []):
        is_freeleech = is_truthy(item.get("free")) or is_truthy(item.get("fl_vip"))
        is_vip = is_truthy(item.get("vip")) or is_truthy(item.get("fl_vip"))
        out.append({
            "id": str(item.get("id") or item.get("tid") or ""),
            "title": item.get("title") or item.get("name"),
            "author_info": flatten(item.get("author_info")),
            "narrator_info": flatten(item.get("narrator_info")),
            "format": detect_format(item),
            "size": item.get("size"),
            "seeders": item.get("seeders"),
            "leechers": item.get("leechers"),
            "catname": item.get("catname"),
            "added": item.get("added"),
            "dl": item.get("dl"),
            "media_type": media_type,
            "is_freeleech": is_freeleech,
            "is_vip": is_vip,
        })

    return JSONResponse({
        "results": out,
        "total": raw.get("total"),
        "total_found": raw.get("total_found"),
        "freeleech_wedges": freeleech_wedges,
    })

# ---------------------------- Transmission RPC helpers ----------------------------
def transmission_auth():
    if settings.TRANSMISSION_USER or settings.TRANSMISSION_PASS:
        return (settings.TRANSMISSION_USER, settings.TRANSMISSION_PASS)
    return None

async def transmission_rpc(client: httpx.AsyncClient, method: str, arguments: dict | None = None) -> dict:
    payload = {"method": method, "arguments": arguments or {}}
    r = await client.post(settings.TRANSMISSION_URL, json=payload, auth=transmission_auth())
    if r.status_code == 409:
        session_id = r.headers.get("X-Transmission-Session-Id")
        if session_id:
            client.headers["X-Transmission-Session-Id"] = session_id
            r = await client.post(settings.TRANSMISSION_URL, json=payload, auth=transmission_auth())
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Transmission RPC failed: {r.status_code} {r.text[:160]}")
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"Transmission returned non-JSON: {r.text[:160]}")
    if data.get("result") != "success":
        raise HTTPException(status_code=502, detail=f"Transmission {method} failed: {data.get('result')}")
    return data.get("arguments") or {}

def transmission_labels(mam_id: str = "", media_type: str = MEDIA_TYPE_AUDIOBOOK, send_to_kindle: bool = True) -> list[str]:
    labels = []
    if settings.TRANSMISSION_LABEL:
        labels.append(settings.TRANSMISSION_LABEL)
    if mam_id:
        labels.append(f"mamid={mam_id}")
    if normalize_media_type(media_type) == MEDIA_TYPE_EBOOK and not send_to_kindle:
        labels.append(TRANSMISSION_NOSEND_LABEL)
    return labels

def torrent_add_arguments(mam_id: str, source_key: str, source_value: str, media_type: str, send_to_kindle: bool) -> dict:
    args = {source_key: source_value}
    labels = transmission_labels(mam_id, media_type, send_to_kindle)
    if labels:
        args["labels"] = labels
    return args

def torrent_hash_from_add_result(args: dict) -> str | None:
    torrent = args.get("torrent-added") or args.get("torrent-duplicate") or {}
    return torrent.get("hashString")

def insert_history(
    mam_id: str,
    title: str,
    author: str,
    narrator: str,
    media_type: str,
    send_to_kindle: bool,
    dl: str,
    torrent_hash: str | None,
):
    added_at = utcnow_str()
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO history (
                mam_id,
                title,
                author,
                narrator,
                media_type,
                send_to_kindle,
                dl,
                torrent_status,
                torrent_hash,
                added_at,
                status_detail,
                status_updated_at
            )
            VALUES (
                :mam_id,
                :title,
                :author,
                :narrator,
                :media_type,
                :send_to_kindle,
                :dl,
                :torrent_status,
                :torrent_hash,
                :added_at,
                :status_detail,
                :status_updated_at
            )
        """), {
            "mam_id": mam_id,
            "title": title,
            "author": author,
            "narrator": narrator,
            "media_type": normalize_media_type(media_type),
            "send_to_kindle": 1 if send_to_kindle else 0,
            "dl": dl,
            "torrent_status": "added",
            "torrent_hash": torrent_hash,
            "added_at": added_at,
            "status_detail": None,
            "status_updated_at": added_at,
        })

# ---------------------------- Add-to-Transmission ----------------------------
class AddBody(BaseModel):
    id: str | int | None = None
    title: str | None = None
    dl: str | None = None
    author: str | None = None
    narrator: str | None = None
    media_type: str | None = None
    send_to_kindle: bool | None = None

@app.post("/add")
async def add_to_transmission(body: AddBody):
    mam_id = ("" if body.id is None else str(body.id)).strip()
    title = (body.title or "").strip()
    author = (body.author or "").strip()
    narrator = (body.narrator or "").strip()
    media_type = normalize_media_type(body.media_type)
    send_to_kindle = True if body.send_to_kindle is None else bool(body.send_to_kindle)
    dl = (body.dl or "").strip()

    if not mam_id:
        raise HTTPException(status_code=400, detail="Missing MAM id")

    freeleech_wedges = None
    use_fl = False
    used_fl = False
    async with httpx.AsyncClient(timeout=30) as status_client:
        freeleech_wedges = await fetch_freeleech_wedge_count(status_client)
        use_fl = media_type == MEDIA_TYPE_AUDIOBOOK and bool(freeleech_wedges and freeleech_wedges > 0)

    async with httpx.AsyncClient(timeout=60) as client:
        candidate_urls = [f"{settings.MAM_BASE}/tor/download.php?tid={mam_id}"]
        if use_fl:
            candidate_urls.insert(0, f"{settings.MAM_BASE}/tor/download.php?tid={mam_id}&fl=1")

        resp = None
        for candidate_url in candidate_urls:
            resp = await client.get(candidate_url, headers=mam_headers(torrent=True))
            if resp.status_code == 200 and resp.content:
                used_fl = candidate_url.endswith("&fl=1")
                break

        if resp is None or resp.status_code != 200 or not resp.content:
            status = "unknown" if resp is None else resp.status_code
            raise HTTPException(status_code=502, detail=f"Could not fetch .torrent from MAM (status: {status}).")

        metainfo = base64.b64encode(resp.content).decode("ascii")
        args = await transmission_rpc(
            client,
            "torrent-add",
            torrent_add_arguments(mam_id, "metainfo", metainfo, media_type, send_to_kindle),
        )
        torrent_hash = torrent_hash_from_add_result(args)
        insert_history(mam_id, title, author, narrator, media_type, send_to_kindle, dl, torrent_hash)

    if used_fl and freeleech_wedges is not None:
        freeleech_wedges = max(freeleech_wedges - 1, 0)

    return {"ok": True, "freeleech_wedges": freeleech_wedges}

@app.get("/account")
async def account_status():
    async with httpx.AsyncClient(timeout=30) as client:
        freeleech_wedges = await fetch_freeleech_wedge_count(client)
    return {"freeleech_wedges": freeleech_wedges}

# ---------------------------- History ----------------------------
@app.get("/history")
def history():
    with engine.begin() as cx:
        rows = cx.execute(text("""
            SELECT
                id,
                mam_id,
                title,
                author,
                narrator,
                media_type,
                send_to_kindle,
                dl,
                torrent_hash,
                added_at,
                imported_at,
                torrent_status,
                status_detail,
                status_updated_at
            FROM history
            ORDER BY id DESC
            LIMIT 200
        """)).mappings().all()
    return {"items": list(rows)}

@app.post("/history/{history_id}/retry")
async def retry_history_import(history_id: int):
    with engine.begin() as cx:
        row = cx.execute(text("""
            SELECT id, title, author, torrent_hash, torrent_status, media_type, send_to_kindle
            FROM history
            WHERE id = :id
        """), {"id": history_id}).mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="History row not found")
    if row.get("torrent_status") != "import_failed":
        raise HTTPException(status_code=400, detail="Only failed imports can be retried")

    torrent_hash = (row.get("torrent_hash") or "").strip()
    author = (row.get("author") or "").strip()
    title = (row.get("title") or "").strip()
    if not torrent_hash:
        mark_history_failed(history_id, "", "History row is missing torrent hash.")
        raise HTTPException(status_code=400, detail="History row is missing torrent hash.")
    if not author or not title:
        mark_history_failed(history_id, torrent_hash, "History row is missing author/title.")
        raise HTTPException(status_code=400, detail="History row is missing author/title.")

    try:
        media_type = normalize_media_type(row.get("media_type"))
    except HTTPException as exc:
        mark_history_failed(history_id, torrent_hash, str(exc.detail))
        raise

    update_history_status(history_id, "importing")

    try:
        await import_torrent_to_library(author, title, torrent_hash, media_type, bool(row.get("send_to_kindle", 1)))
    except HTTPException as exc:
        mark_history_failed(history_id, torrent_hash, str(exc.detail))
        raise
    except Exception as exc:
        logger.exception("Retry import failed for history row %s", history_id)
        detail = f"Import failed: {exc}"
        mark_history_failed(history_id, torrent_hash, detail)
        raise HTTPException(status_code=500, detail=detail)

    mark_history_imported(history_id, torrent_hash)
    return {"ok": True}

# ---------------------------- List Importable ----------------------------
async def list_completed_torrents() -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as c:
        args = await transmission_rpc(c, "torrent-get", {
            "fields": [
                "id",
                "hashString",
                "name",
                "percentDone",
                "downloadDir",
                "totalSize",
                "addedDate",
                "labels",
                "files",
            ],
        })
        infos = args.get("torrents") or []

        out = []
        for t in infos:
            if settings.TRANSMISSION_LABEL and settings.TRANSMISSION_LABEL not in (t.get("labels") or []):
                continue
            if float(t.get("percentDone") or 0) < 1:
                continue

            h = t.get("hashString")
            if not h:
                continue
            files = t.get("files") or []
            # compute top-level root (before first '/')
            roots = set()
            for f in files:
                name = (f.get("name") or "").lstrip("/")
                roots.add(name.split("/", 1)[0])
            root = (list(roots)[0] if roots else t.get("name") or "")
            single_file = len(files) == 1 and "/" not in (files[0].get("name") or "")
            out.append({
                "hash": h,
                "name": t.get("name"),
                "download_dir": t.get("downloadDir"),
                "root": root,
                "single_file": single_file,
                "size": t.get("totalSize"),
                "added_on": t.get("addedDate"),
            })
        return out

# ---------------------------- Perform Import ----------------------------

def sanitize(name: str) -> str:
    s = name.strip().replace(":", " -").replace("\\", "﹨").replace("/", "﹨")
    s = re.sub(r"\s+", " ", s)[:200]
    if s in (".", ".."):
        return "Unknown"
    return s or "Unknown"

def next_available(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.name} ({i})")
        if not cand.exists():
            return cand
        i += 1

def hardlink_one(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail=f"Import source file not found: {src}")
    except FileExistsError:
        raise HTTPException(status_code=400, detail=f"Import destination already exists: {dst}")
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            detail = (
                f"Could not hardlink '{src}' to '{dst}' because they are on different filesystems. "
                "Mount downloads and library paths from one shared parent directory."
            )
        elif exc.errno in (errno.EPERM, errno.EACCES):
            detail = f"Could not hardlink '{src}' to '{dst}': permission denied."
        else:
            detail = f"Could not hardlink '{src}' to '{dst}': {exc.strerror or exc}"
        raise HTTPException(status_code=400, detail=detail)

def copy_one(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dst)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail=f"Import source file not found: {src}")
    except FileExistsError:
        raise HTTPException(status_code=400, detail=f"Import destination already exists: {dst}")
    except OSError as exc:
        detail = f"Could not copy '{src}' to '{dst}': {exc.strerror or exc}"
        raise HTTPException(status_code=400, detail=detail)

def clean_status_detail(detail: str | None) -> str | None:
    text_value = re.sub(r"\s+", " ", (detail or "").strip())
    return text_value[:500] or None

def update_history_status(history_id: int, status: str, detail: str | None = None, imported_at: str | None = None):
    ts = utcnow_str()
    with engine.begin() as cx:
        cx.execute(text("""
            UPDATE history
            SET
                torrent_status = :status,
                status_detail = :detail,
                status_updated_at = :status_updated_at,
                imported_at = COALESCE(:imported_at, imported_at)
            WHERE id = :id
        """), {
            "id": history_id,
            "status": status,
            "detail": clean_status_detail(detail),
            "status_updated_at": ts,
            "imported_at": imported_at,
        })

def mark_history_imported(history_id: int | None, torrent_hash: str):
    ts = utcnow_str()
    with engine.begin() as cx:
        if history_id is not None:
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'imported',
                    status_detail = NULL,
                    status_updated_at = :ts,
                    imported_at = :ts
                WHERE id = :id
            """), {"ts": ts, "id": history_id})
        else:
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'imported',
                    status_detail = NULL,
                    status_updated_at = :ts,
                    imported_at = :ts
                WHERE torrent_hash = :torrent_hash
            """), {"ts": ts, "torrent_hash": torrent_hash})

def mark_history_failed(history_id: int | None, torrent_hash: str, detail: str):
    with engine.begin() as cx:
        params = {"detail": clean_status_detail(detail)}
        if history_id is not None:
            params["id"] = history_id
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'import_failed',
                    status_detail = :detail,
                    status_updated_at = :ts
                WHERE id = :id
            """), {"ts": utcnow_str(), **params})
        else:
            params["torrent_hash"] = torrent_hash
            cx.execute(text("""
                UPDATE history
                SET
                    torrent_status = 'import_failed',
                    status_detail = :detail,
                    status_updated_at = :ts
                WHERE torrent_hash = :torrent_hash
            """), {"ts": utcnow_str(), **params})

def get_auto_import_candidates(completed_hashes: set[str]) -> list[dict]:
    if not completed_hashes:
        return []
    with engine.begin() as cx:
        rows = cx.execute(text("""
            SELECT id, title, author, torrent_hash, torrent_status, media_type, send_to_kindle
            FROM history
            WHERE
                torrent_hash IS NOT NULL
                AND trim(torrent_hash) != ''
                AND (
                    torrent_status IS NULL
                    OR torrent_status NOT IN ('imported', 'import_failed', 'importing')
                )
            ORDER BY id ASC
        """)).mappings().all()
    out = []
    seen_hashes = set()
    for row in rows:
        torrent_hash = (row.get("torrent_hash") or "").strip()
        if not torrent_hash or torrent_hash not in completed_hashes or torrent_hash in seen_hashes:
            continue
        seen_hashes.add(torrent_hash)
        out.append(dict(row))
    return out

def validate_download_path(p: str) -> str:
    p = (p or "").strip()
    if not p:
        return p
    downloads_dir = settings.DOWNLOADS_DIR.rstrip("/") or "/"
    if p == downloads_dir or p.startswith(downloads_dir + "/"):
        return p
    raise HTTPException(
        status_code=400,
        detail=(
            f"Transmission reports downloadDir '{p}', but this app expects completed "
            f"downloads under {settings.DOWNLOADS_DIR}. Mount the same downloads "
            f"directory at {settings.DOWNLOADS_DIR} in both containers."
        ),
    )

def is_transient_auto_import_error(exc: HTTPException) -> bool:
    detail = str(exc.detail)
    return exc.status_code == 502 and detail.startswith("Transmission")

def safe_child_path(root: Path, name: str) -> Path:
    """Join `name` onto `root` and confirm the result stays within `root`.

    Rejects absolute names and any that traverse outside `root` via '..'.
    Raises HTTPException(400) on violation.
    """
    if os.path.isabs(name) or ".." in Path(name).parts:
        raise HTTPException(status_code=400, detail=f"Unsafe path in torrent contents: {name!r}")
    candidate = root / name
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if root_resolved != candidate_resolved and root_resolved not in candidate_resolved.parents:
        raise HTTPException(status_code=400, detail=f"Unsafe path in torrent contents: {name!r}")
    return candidate

async def import_torrent_to_library(author: str, title: str, h: str, media_type: str = MEDIA_TYPE_AUDIOBOOK, send_to_kindle: bool = True) -> str:
    media_type = normalize_media_type(media_type)
    author = sanitize(author)
    title = sanitize(title)
    # Query Transmission for files and download directory.
    async with httpx.AsyncClient(timeout=30) as c:
        args = await transmission_rpc(c, "torrent-get", {
            "ids": [h],
            "fields": ["id", "hashString", "name", "downloadDir", "labels", "files"],
        })
        torrents = args.get("torrents") or []
        info = torrents[0] if torrents else {}
        files = info.get("files") or []
        if not files:
            raise HTTPException(status_code=404, detail="No files found for torrent")

        download_dir = (info.get("downloadDir") or "").rstrip("/")
        if not download_dir:
            raise HTTPException(status_code=404, detail="Torrent download directory not found")

    source_dir = Path(validate_download_path(download_dir))

    # Destination: /library/Author/Title, /ebooks/Author/Title, or /ebooks-nosend/Author/Title.
    if media_type == MEDIA_TYPE_EBOOK:
        lib = Path(settings.EBOOKS_DIR if send_to_kindle else settings.EBOOKS_NOSEND_DIR)
    else:
        lib = Path(settings.LIBRARY_DIR)
    author_dir = safe_child_path(lib, author)
    author_dir.mkdir(parents=True, exist_ok=True)
    dest_dir = next_available(safe_child_path(author_dir, title))

    names = [(f.get("name") or "").lstrip("/") for f in files if f.get("name")]
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    common_root = next(iter(roots)) if len(roots) == 1 and all(name == next(iter(roots)) or name.startswith(next(iter(roots)) + "/") for name in names) else ""

    import_one = hardlink_one if media_type == MEDIA_TYPE_AUDIOBOOK else copy_one

    # Import all files (skip .cue). Audiobooks hardlink; ebooks copy.
    imported = 0
    try:
        if len(names) == 1:
            src = safe_child_path(source_dir, names[0])
            if src.suffix.lower() == ".cue":
                raise HTTPException(status_code=400, detail="Only .cue file found; nothing to import")
            import_one(src, safe_child_path(dest_dir, src.name))
            imported += 1
        else:
            for name in names:
                src = safe_child_path(source_dir, name)
                if src.suffix.lower() == ".cue":
                    continue
                rel_name = name
                if common_root and name.startswith(common_root + "/"):
                    rel_name = name[len(common_root) + 1:]
                if not rel_name:
                    continue
                import_one(src, safe_child_path(dest_dir, rel_name))
                imported += 1
    except Exception:
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    if imported == 0:
        raise HTTPException(status_code=400, detail="No importable files found")

    return str(dest_dir)

async def auto_import_cycle():
    completed = await list_completed_torrents()
    completed_hashes = {item.get("hash") for item in completed if item.get("hash")}
    for row in get_auto_import_candidates(completed_hashes):
        history_id = row["id"]
        torrent_hash = (row.get("torrent_hash") or "").strip()
        author = (row.get("author") or "").strip()
        title = (row.get("title") or "").strip()

        try:
            media_type = normalize_media_type(row.get("media_type"))
        except HTTPException as exc:
            mark_history_failed(history_id, torrent_hash, str(exc.detail))
            continue

        if not author or not title:
            mark_history_failed(history_id, torrent_hash, "History row is missing author/title.")
            continue

        update_history_status(history_id, "importing")

        try:
            await import_torrent_to_library(author, title, torrent_hash, media_type, bool(row.get("send_to_kindle", 1)))
        except HTTPException as exc:
            if is_transient_auto_import_error(exc):
                update_history_status(history_id, "added")
                logger.warning("Auto-import skipped for history row %s: %s", history_id, exc.detail)
            else:
                mark_history_failed(history_id, torrent_hash, str(exc.detail))
                logger.warning("Auto-import failed for history row %s: %s", history_id, exc.detail)
            continue
        except Exception as exc:
            logger.exception("Unexpected auto-import failure for history row %s", history_id)
            mark_history_failed(history_id, torrent_hash, f"Import failed: {exc}")
            continue

        mark_history_imported(history_id, torrent_hash)
        logger.info("Auto-imported history row %s", history_id)

async def auto_import_loop(stop_event: asyncio.Event):
    logger.info("Auto-import poller started with %ss interval", settings.AUTO_IMPORT_POLL_INTERVAL)
    while not stop_event.is_set():
        try:
            await auto_import_cycle()
        except HTTPException as exc:
            logger.warning("Auto-import cycle skipped: %s", exc.detail)
        except Exception:
            logger.exception("Auto-import poller cycle failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.AUTO_IMPORT_POLL_INTERVAL)
        except asyncio.TimeoutError:
            continue
    logger.info("Auto-import poller stopped")

async def stop_auto_import_task():
    task = getattr(app.state, "auto_import_task", None)
    stop_event = getattr(app.state, "auto_import_stop", None)
    if stop_event is not None:
        stop_event.set()
    if task is not None:
        try:
            await task
        except asyncio.CancelledError:
            pass
    app.state.auto_import_task = None
    app.state.auto_import_stop = None

async def reconcile_auto_import_task():
    task = getattr(app.state, "auto_import_task", None)
    if task is None or task.done():
        stop_event = asyncio.Event()
        app.state.auto_import_stop = stop_event
        app.state.auto_import_task = asyncio.create_task(auto_import_loop(stop_event))

@app.on_event("startup")
async def startup_event():
    await reconcile_auto_import_task()

@app.on_event("shutdown")
async def shutdown_event():
    await stop_auto_import_task()
