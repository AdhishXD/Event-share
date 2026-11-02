import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import (
    ALLOWED_IMAGE_TYPES,
    AUTO_MATCH_THRESHOLD,
    EVENT_COVER_DIR,
    MAX_IMAGE_BYTES,
    REFERENCE_DIR,
    REVIEW_MATCH_THRESHOLD,
    ROOT,
    UPLOAD_DIR,
    DATA_DIR,
)
from .db import db, init_db, now_iso
from .recognition import (
    ModelsUnavailable,
    deserialize_embedding,
    recognition,
    serialize_embedding,
)
from .security import hash_password, new_csrf_token, new_invite_code, verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Gatherly", lifespan=lifespan)


def session_secret() -> str:
    configured = os.getenv("GATHERLY_SECRET")
    if configured:
        return configured
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = DATA_DIR / ".session_secret"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32))
        secret_file.chmod(0o600)
    return secret_file.read_text().strip()


app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def template(request: Request, name: str, **context):
    token = request.session.setdefault("csrf", new_csrf_token())
    user = None
    if request.session.get("user_id"):
        with db() as connection:
            user = connection.execute(
                "SELECT id, name, email FROM users WHERE id = ?", (request.session["user_id"],)
            ).fetchone()
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "user": user,
            "csrf_token": token,
            "flash": request.session.pop("flash", None),
            **context,
        },
    )


def require_user(request: Request) -> int:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Please sign in first.")
    return int(user_id)


def verify_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid form token. Refresh and try again.")


def require_member(connection, event_id: int, user_id: int):
    member = connection.execute(
        "SELECT * FROM memberships WHERE event_id = ? AND user_id = ?",
        (event_id, user_id),
    ).fetchone()
    if not member:
        raise HTTPException(status_code=403, detail="You are not a member of this event.")
    return member


def require_organizer(connection, event_id: int, user_id: int):
    member = require_member(connection, event_id, user_id)
    if member["role"] != "organizer":
        raise HTTPException(status_code=403, detail="Only the event organizer can change its appearance.")
    return member


def match_existing_photos(event_id: int, user_id: int, embedding) -> int:
    """Backfill a new enrollment against photos uploaded before it existed."""
    with db() as connection:
        photos = connection.execute(
            "SELECT id, stored_path FROM media WHERE event_id=? AND status='ready'",
            (event_id,),
        ).fetchall()
    matched = 0
    for photo in photos:
        try:
            faces = recognition.embeddings(Path(photo["stored_path"]))
        except (ValueError, ModelsUnavailable):
            continue
        score = max((recognition.similarity(face, embedding) for face in faces), default=-1.0)
        status = (
            "accepted"
            if score >= AUTO_MATCH_THRESHOLD
            else "pending"
            if score >= REVIEW_MATCH_THRESHOLD
            else None
        )
        if status:
            with db() as connection:
                connection.execute(
                    """INSERT INTO matches(media_id,user_id,confidence,status,created_at)
                       VALUES(?,?,?,?,?) ON CONFLICT(media_id,user_id) DO UPDATE SET
                       confidence=excluded.confidence, status=excluded.status""",
                    (photo["id"], user_id, score, status, now_iso()),
                )
            matched += 1
    return matched


def group_gallery_matches(rows) -> list[dict]:
    """Group ordered match rows by event, then by the photo's calendar date."""
    events: dict[int, dict] = {}
    for row in rows:
        photo = dict(row)
        event_id = photo["event_id"]
        event_group = events.setdefault(
            event_id,
            {
                "id": event_id,
                "name": photo["event_name"],
                "event_date": photo["event_date"],
                "count": 0,
                "dates": {},
            },
        )
        photo_date = (photo["created_at"] or "")[:10] or "Date unavailable"
        event_group["dates"].setdefault(photo_date, []).append(photo)
        event_group["count"] += 1
    return [
        {**event_group, "dates": [{"date": date, "photos": photos} for date, photos in event_group["dates"].items()]}
        for event_group in events.values()
    ]


async def save_upload(upload: UploadFile, destination: Path) -> None:
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Only JPEG, PNG, and WebP images are supported.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                output.close()
                destination.unlink(missing_ok=True)
                raise ValueError("Each image must be 20 MB or smaller.")
            output.write(chunk)


def safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "image.jpg").suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


@app.exception_handler(401)
async def unauthorized(_: Request, __):
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return template(request, "home.html")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return template(request, "auth.html", mode="register")


@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    name, email = name.strip(), email.strip().lower()
    if len(name) < 2 or "@" not in email or len(password) < 8:
        flash(request, "Use a name, valid email, and password of at least 8 characters.", "error")
        return RedirectResponse("/register", status_code=303)
    try:
        with db() as connection:
            cursor = connection.execute(
                "INSERT INTO users(name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (name, email, hash_password(password), now_iso()),
            )
            request.session["user_id"] = cursor.lastrowid
    except Exception as exc:
        if "UNIQUE" in str(exc):
            flash(request, "An account with that email already exists.", "error")
            return RedirectResponse("/register", status_code=303)
        raise
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return template(request, "auth.html", mode="login")


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    with db() as connection:
        user = connection.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),)
        ).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        flash(request, "Email or password is incorrect.", "error")
        return RedirectResponse("/login", status_code=303)
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["csrf"] = new_csrf_token()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = require_user(request)
    with db() as connection:
        events = connection.execute(
            """
            SELECT e.*, m.role,
                   (SELECT COUNT(*) FROM media WHERE event_id=e.id) AS photo_count,
                   (SELECT COUNT(*) FROM memberships WHERE event_id=e.id) AS member_count
            FROM events e JOIN memberships m ON m.event_id=e.id
            WHERE m.user_id=? ORDER BY e.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return template(request, "dashboard.html", events=events)


@app.post("/events")
def create_event(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    event_date: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    if len(name.strip()) < 3:
        flash(request, "Give the event a name of at least 3 characters.", "error")
        return RedirectResponse("/dashboard", status_code=303)
    with db() as connection:
        cursor = connection.execute(
            "INSERT INTO events(name, description, event_date, invite_code, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name.strip(), description.strip(), event_date or None, new_invite_code(), user_id, now_iso()),
        )
        event_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO memberships(event_id, user_id, role, consented_at) VALUES (?, ?, 'organizer', ?)",
            (event_id, user_id, now_iso()),
        )
        connection.execute(
            "INSERT INTO audit_events(user_id, event_id, action, created_at) VALUES (?, ?, 'event_created', ?)",
            (user_id, event_id, now_iso()),
        )
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@app.post("/events/join")
def join_event(request: Request, invite_code: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    with db() as connection:
        event = connection.execute(
            "SELECT * FROM events WHERE invite_code = ?", (invite_code.strip().upper(),)
        ).fetchone()
        if not event:
            flash(request, "That invite code was not found.", "error")
            return RedirectResponse("/dashboard", status_code=303)
        connection.execute(
            "INSERT OR IGNORE INTO memberships(event_id, user_id, role) VALUES (?, ?, 'participant')",
            (event["id"], user_id),
        )
    return RedirectResponse(f"/events/{event['id']}", status_code=303)


@app.get("/events/{event_id}", response_class=HTMLResponse)
def event_page(request: Request, event_id: int):
    user_id = require_user(request)
    with db() as connection:
        member = require_member(connection, event_id, user_id)
        event = connection.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        photos = connection.execute(
            "SELECT media.*, users.name AS uploader_name FROM media JOIN users ON users.id=media.uploader_id WHERE event_id=? ORDER BY created_at DESC",
            (event_id,),
        ).fetchall()
    return template(
        request, "event.html", event=event, member=member, photos=photos
    )


@app.get("/events/{event_id}/manage", response_class=HTMLResponse)
def manage_event_page(request: Request, event_id: int):
    user_id = require_user(request)
    with db() as connection:
        member = require_member(connection, event_id, user_id)
        event = connection.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        profile = connection.execute(
            "SELECT * FROM face_profiles WHERE event_id=? AND user_id=?", (event_id, user_id)
        ).fetchone()
        members = connection.execute(
            """SELECT u.name, m.role, fp.reference_count
               FROM memberships m JOIN users u ON u.id=m.user_id
               LEFT JOIN face_profiles fp ON fp.event_id=m.event_id AND fp.user_id=m.user_id
               WHERE m.event_id=? ORDER BY m.role, u.name""",
            (event_id,),
        ).fetchall()
        photo_count = connection.execute(
            "SELECT COUNT(*) FROM media WHERE event_id=?", (event_id,)
        ).fetchone()[0]
    return template(
        request,
        "event_manage.html",
        event=event,
        member=member,
        profile=profile,
        members=members,
        photo_count=photo_count,
    )


@app.get("/events/{event_id}/my-photos", response_class=HTMLResponse)
def event_my_photos(request: Request, event_id: int):
    user_id = require_user(request)
    with db() as connection:
        member = require_member(connection, event_id, user_id)
        event = connection.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        profile = connection.execute(
            "SELECT * FROM face_profiles WHERE event_id=? AND user_id=?", (event_id, user_id)
        ).fetchone()
        matches = connection.execute(
            """SELECT media.*, events.id AS event_id, events.name AS event_name,
                      events.event_date, matches.confidence, matches.id AS match_id,
                      matches.status AS match_status
               FROM matches
               JOIN media ON media.id=matches.media_id
               JOIN events ON events.id=media.event_id
               WHERE matches.user_id=? AND media.event_id=? AND matches.status IN ('accepted','pending')
               ORDER BY media.created_at DESC""",
            (user_id, event_id),
        ).fetchall()
    accepted = [dict(match) for match in matches if match["match_status"] == "accepted"]
    pending = [dict(match) for match in matches if match["match_status"] == "pending"]
    return template(
        request,
        "event_my_photos.html",
        event=event,
        member=member,
        profile=profile,
        accepted=accepted,
        pending=pending,
    )


@app.post("/events/{event_id}/appearance")
async def update_event_appearance(
    request: Request,
    event_id: int,
    theme: str = Form(...),
    csrf_token: str = Form(...),
    cover: UploadFile | None = File(None),
):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    allowed_themes = {"system", "ocean", "sunset", "garden", "celebration"}
    if theme not in allowed_themes:
        raise HTTPException(400, "Unknown event theme.")
    with db() as connection:
        require_organizer(connection, event_id, user_id)
        event = connection.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    new_cover = None
    if cover and cover.filename:
        new_cover = EVENT_COVER_DIR / str(event_id) / f"cover-{secrets.token_hex(10)}{safe_suffix(cover.filename)}"
        try:
            await save_upload(cover, new_cover)
            recognition.decode_image(new_cover)
        except ValueError as exc:
            new_cover.unlink(missing_ok=True)
            flash(request, str(exc), "error")
            return RedirectResponse(f"/events/{event_id}/manage", status_code=303)
    with db() as connection:
        connection.execute(
            "UPDATE events SET theme=?, cover_path=COALESCE(?, cover_path) WHERE id=?",
            (theme, str(new_cover) if new_cover else None, event_id),
        )
        connection.execute(
            "INSERT INTO audit_events(user_id,event_id,action,details,created_at) VALUES(?,?, 'appearance_updated', ?, ?)",
            (user_id, event_id, theme, now_iso()),
        )
    if new_cover and event["cover_path"]:
        Path(event["cover_path"]).unlink(missing_ok=True)
    flash(request, "Event appearance updated.", "success")
    return RedirectResponse(f"/events/{event_id}/manage", status_code=303)


@app.get("/events/{event_id}/cover")
def event_cover(request: Request, event_id: int):
    user_id = require_user(request)
    with db() as connection:
        require_member(connection, event_id, user_id)
        event = connection.execute("SELECT cover_path FROM events WHERE id=?", (event_id,)).fetchone()
    if not event or not event["cover_path"] or not Path(event["cover_path"]).exists():
        raise HTTPException(404, "Event cover not found.")
    return FileResponse(event["cover_path"])


@app.post("/events/{event_id}/enroll")
async def enroll_face(
    request: Request,
    event_id: int,
    consent: str = Form(...),
    csrf_token: str = Form(...),
    references: list[UploadFile] = File(...),
):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    if consent != "yes":
        raise HTTPException(400, "Explicit consent is required.")
    if not 2 <= len(references) <= 5:
        flash(request, "Upload between 2 and 5 clear reference photos.", "error")
        return RedirectResponse(f"/events/{event_id}/manage", status_code=303)
    with db() as connection:
        require_member(connection, event_id, user_id)
    saved: list[Path] = []
    features = []
    try:
        for upload in references:
            path = REFERENCE_DIR / str(event_id) / str(user_id) / f"{secrets.token_hex(12)}{safe_suffix(upload.filename)}"
            await save_upload(upload, path)
            faces = recognition.embeddings(path)
            if len(faces) != 1:
                raise ValueError(f"Each reference must contain exactly one clear face; {upload.filename} did not.")
            saved.append(path)
            features.append(faces[0])
    except (ValueError, ModelsUnavailable) as exc:
        for path in saved:
            path.unlink(missing_ok=True)
        flash(request, str(exc), "error")
        return RedirectResponse(f"/events/{event_id}/manage", status_code=303)
    averaged = recognition.average(features)
    with db() as connection:
        old_refs = connection.execute(
            "SELECT stored_path FROM reference_images WHERE event_id=? AND user_id=?", (event_id, user_id)
        ).fetchall()
        connection.execute("DELETE FROM reference_images WHERE event_id=? AND user_id=?", (event_id, user_id))
        connection.execute(
            """INSERT INTO face_profiles(event_id,user_id,embedding,reference_count,created_at)
               VALUES(?,?,?,?,?) ON CONFLICT(event_id,user_id) DO UPDATE SET
               embedding=excluded.embedding, reference_count=excluded.reference_count, created_at=excluded.created_at""",
            (event_id, user_id, serialize_embedding(averaged), len(saved), now_iso()),
        )
        connection.execute(
            "UPDATE memberships SET consented_at=? WHERE event_id=? AND user_id=?",
            (now_iso(), event_id, user_id),
        )
        connection.executemany(
            "INSERT INTO reference_images(event_id,user_id,stored_path,created_at) VALUES(?,?,?,?)",
            [(event_id, user_id, str(path), now_iso()) for path in saved],
        )
        connection.execute(
            "INSERT INTO audit_events(user_id,event_id,action,details,created_at) VALUES(?,?, 'face_enrolled', ?, ?)",
            (user_id, event_id, f"{len(saved)} references", now_iso()),
        )
    for row in old_refs:
        Path(row["stored_path"]).unlink(missing_ok=True)
    existing_matches = match_existing_photos(event_id, user_id, averaged)
    message = "Your event-specific face profile is ready."
    if existing_matches:
        message += f" We also found {existing_matches} possible match(es) in existing photos."
    flash(request, message, "success")
    return RedirectResponse(f"/events/{event_id}/manage", status_code=303)


@app.post("/events/{event_id}/enrollment/delete")
def delete_enrollment(request: Request, event_id: int, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    with db() as connection:
        require_member(connection, event_id, user_id)
        refs = connection.execute(
            "SELECT stored_path FROM reference_images WHERE event_id=? AND user_id=?", (event_id, user_id)
        ).fetchall()
        connection.execute("DELETE FROM face_profiles WHERE event_id=? AND user_id=?", (event_id, user_id))
        connection.execute("DELETE FROM reference_images WHERE event_id=? AND user_id=?", (event_id, user_id))
        connection.execute("DELETE FROM matches WHERE user_id=? AND media_id IN (SELECT id FROM media WHERE event_id=?)", (user_id, event_id))
        connection.execute("UPDATE memberships SET consented_at=NULL WHERE event_id=? AND user_id=?", (event_id, user_id))
    for row in refs:
        Path(row["stored_path"]).unlink(missing_ok=True)
    flash(request, "Your face profile and matches for this event were deleted.", "success")
    return RedirectResponse(f"/events/{event_id}/manage", status_code=303)


@app.post("/events/{event_id}/photos")
async def upload_photos(
    request: Request,
    event_id: int,
    csrf_token: str = Form(...),
    photos: list[UploadFile] = File(...),
):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    with db() as connection:
        require_member(connection, event_id, user_id)
        profiles = connection.execute(
            "SELECT user_id, embedding FROM face_profiles WHERE event_id=?", (event_id,)
        ).fetchall()
    if not photos:
        flash(request, "Choose at least one event photo.", "error")
        return RedirectResponse(f"/events/{event_id}/manage", status_code=303)
    completed = 0
    try:
        for upload in photos:
            path = UPLOAD_DIR / str(event_id) / f"{secrets.token_hex(16)}{safe_suffix(upload.filename)}"
            await save_upload(upload, path)
            faces = recognition.embeddings(path)
            with db() as connection:
                cursor = connection.execute(
                    "INSERT INTO media(event_id,uploader_id,original_name,stored_path,mime_type,status,created_at) VALUES(?,?,?,?,?,'processing',?)",
                    (event_id, user_id, Path(upload.filename or "photo").name, str(path), upload.content_type, now_iso()),
                )
                media_id = cursor.lastrowid
            best_by_user: dict[int, float] = {}
            for face in faces:
                for profile in profiles:
                    score = recognition.similarity(face, deserialize_embedding(profile["embedding"]))
                    best_by_user[profile["user_id"]] = max(score, best_by_user.get(profile["user_id"], -1.0))
            with db() as connection:
                for matched_user, score in best_by_user.items():
                    status = "accepted" if score >= AUTO_MATCH_THRESHOLD else "pending" if score >= REVIEW_MATCH_THRESHOLD else None
                    if status:
                        connection.execute(
                            "INSERT OR IGNORE INTO matches(media_id,user_id,confidence,status,created_at) VALUES(?,?,?,?,?)",
                            (media_id, matched_user, score, status, now_iso()),
                        )
                connection.execute(
                    "UPDATE media SET status='ready', face_count=? WHERE id=?", (len(faces), media_id)
                )
            completed += 1
    except (ValueError, ModelsUnavailable) as exc:
        if "path" in locals() and path.exists() and completed < len(photos):
            path.unlink(missing_ok=True)
        flash(request, f"Processed {completed} photo(s). Stopped because: {exc}", "error")
        return RedirectResponse(f"/events/{event_id}/manage", status_code=303)
    flash(request, f"Processed {completed} photo(s) privately on this computer.", "success")
    return RedirectResponse(f"/events/{event_id}/manage", status_code=303)


@app.get("/gallery", response_class=HTMLResponse)
def gallery(request: Request):
    user_id = require_user(request)
    with db() as connection:
        accepted = connection.execute(
            """SELECT media.*, events.id AS event_id, events.name AS event_name,
                      events.event_date, matches.confidence, matches.id AS match_id
               FROM matches JOIN media ON media.id=matches.media_id JOIN events ON events.id=media.event_id
               WHERE matches.user_id=? AND matches.status='accepted'
               ORDER BY COALESCE(events.event_date, substr(media.created_at,1,10)) DESC,
                        events.name COLLATE NOCASE, media.created_at DESC""",
            (user_id,),
        ).fetchall()
        pending = connection.execute(
            """SELECT media.*, events.id AS event_id, events.name AS event_name,
                      events.event_date, matches.confidence, matches.id AS match_id
               FROM matches JOIN media ON media.id=matches.media_id JOIN events ON events.id=media.event_id
               WHERE matches.user_id=? AND matches.status='pending'
               ORDER BY COALESCE(events.event_date, substr(media.created_at,1,10)) DESC,
                        events.name COLLATE NOCASE, media.created_at DESC""",
            (user_id,),
        ).fetchall()
    return template(
        request,
        "gallery.html",
        accepted=accepted,
        pending=pending,
        accepted_groups=group_gallery_matches(accepted),
        pending_groups=group_gallery_matches(pending),
    )


@app.post("/matches/{match_id}")
def review_match(
    request: Request,
    match_id: int,
    decision: str = Form(...),
    gallery_scope: str = Form("global"),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    if decision not in {"accepted", "rejected"}:
        raise HTTPException(400, "Invalid decision.")
    with db() as connection:
        match = connection.execute(
            """SELECT media.event_id FROM matches
               JOIN media ON media.id=matches.media_id
               WHERE matches.id=? AND matches.user_id=?""",
            (match_id, user_id),
        ).fetchone()
        if not match:
            raise HTTPException(404, "Match not found.")
        result = connection.execute(
            "UPDATE matches SET status=? WHERE id=? AND user_id=?", (decision, match_id, user_id)
        )
        if not result.rowcount:
            raise HTTPException(404, "Match not found.")
    if gallery_scope == "event":
        return RedirectResponse(f"/events/{match['event_id']}/my-photos", status_code=303)
    return RedirectResponse("/gallery", status_code=303)


@app.get("/media/{media_id}")
def view_media(request: Request, media_id: int):
    user_id = require_user(request)
    with db() as connection:
        item = connection.execute(
            "SELECT * FROM media WHERE id=?", (media_id,)
        ).fetchone()
        if not item:
            raise HTTPException(404, "Photo not found.")
        require_member(connection, item["event_id"], user_id)
    return FileResponse(item["stored_path"], media_type=item["mime_type"], filename=None)


@app.post("/media/{media_id}/delete")
def delete_media(request: Request, media_id: int, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    user_id = require_user(request)
    with db() as connection:
        item = connection.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Photo not found.")
        event = connection.execute("SELECT * FROM events WHERE id=?", (item["event_id"],)).fetchone()
        if item["uploader_id"] != user_id and event["owner_id"] != user_id:
            raise HTTPException(403, "Only the uploader or organizer can delete this photo.")
        connection.execute("DELETE FROM media WHERE id=?", (media_id,))
    Path(item["stored_path"]).unlink(missing_ok=True)
    flash(request, "The photo and all of its matches were deleted.", "success")
    return RedirectResponse(f"/events/{item['event_id']}", status_code=303)

