import re
import os
import tempfile
import base64

os.environ["GATHERLY_DATA_DIR"] = tempfile.mkdtemp(prefix="gatherly-tests-")

from fastapi.testclient import TestClient

from app.config import UPLOAD_DIR
from app.db import db, now_iso
from app.main import app


def csrf(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def test_account_event_and_invite_flow():
    with TestClient(app) as owner:
        page = owner.get("/register")
        response = owner.post(
            "/register",
            data={
                "csrf_token": csrf(page),
                "name": "Event Owner",
                "email": "owner@example.test",
                "password": "a-secure-password",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Your events" in response.text

        response = owner.post(
            "/events",
            data={
                "csrf_token": csrf(response),
                "name": "Test Celebration",
                "description": "A private test event",
                "event_date": "2026-12-12",
            },
            follow_redirects=True,
        )
        assert "Test Celebration" in response.text
        invite = re.search(r'<strong>([A-Z0-9]+)</strong>', response.text).group(1)
        event_id = int(response.url.path.rsplit("/", 1)[-1])
        photo_path = UPLOAD_DIR / str(event_id) / "existing-photo.jpg"
        photo_path.parent.mkdir(parents=True, exist_ok=True)
        photo_path.write_bytes(b"existing-event-photo")
        with db() as connection:
            owner_id = connection.execute(
                "SELECT id FROM users WHERE email='owner@example.test'"
            ).fetchone()["id"]
            media_id = connection.execute(
                """INSERT INTO media(event_id,uploader_id,original_name,stored_path,mime_type,status,created_at)
                   VALUES(?,?,?,?,?,'ready',?)""",
                (event_id, owner_id, "existing-photo.jpg", str(photo_path), "image/jpeg", now_iso()),
            ).lastrowid

        manage = owner.get(f"/events/{event_id}/manage")
        cover_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        response = owner.post(
            f"/events/{event_id}/appearance",
            data={"csrf_token": csrf(manage), "theme": "ocean"},
            files={"cover": ("cover.png", cover_bytes, "image/png")},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert response.url.path == f"/events/{event_id}/manage"
        assert "Event appearance updated" in response.text
        with db() as connection:
            event = connection.execute(
                "SELECT theme, cover_path FROM events WHERE id=?", (event_id,)
            ).fetchone()
        assert event["theme"] == "ocean"
        assert event["cover_path"]
        assert owner.get(f"/events/{event_id}/cover").status_code == 200

    with TestClient(app) as guest:
        page = guest.get("/register")
        response = guest.post(
            "/register",
            data={
                "csrf_token": csrf(page),
                "name": "Event Guest",
                "email": "guest@example.test",
                "password": "another-secure-password",
            },
            follow_redirects=True,
        )
        response = guest.post(
            "/events/join",
            data={"csrf_token": csrf(response), "invite_code": invite},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Test Celebration" in response.text
        assert "existing-photo.jpg" in response.text
        assert f'action="/events/{event_id}/photos"' not in response.text
        assert f'href="/events/{event_id}/manage"' in response.text
        assert guest.get(f"/media/{media_id}").status_code == 200
        assert guest.get(f"/events/{event_id}/cover").status_code == 200

        manage = guest.get(f"/events/{event_id}/manage")
        assert manage.status_code == 200
        assert "Event Guest" in manage.text
        assert "Help Photos Find You" in manage.text
        assert "Add Event Photos" in manage.text
        assert 'data-reference-camera' in manage.text
        assert 'data-reference-library' in manage.text
        assert 'data-reference-list' in manage.text
        assert 'data-reference-feedback' in manage.text
        assert 'name="references"' in manage.text
        assert 'capture="user"' in manage.text
        assert 'data-open-camera' in manage.text
        assert 'data-camera-dialog' in manage.text
        assert 'data-capture-photo' in manage.text
        assert 'name="photos"' in manage.text
        assert 'data-event-photo-upload' in manage.text
        assert 'data-event-photo-input' in manage.text
        assert 'data-event-photo-list' in manage.text
        assert 'data-event-photo-feedback' in manage.text
        assert 'name="photos" accept="image/jpeg,image/png,image/webp" multiple required capture' not in manage.text
        assert "Event Appearance" not in manage.text
        forbidden = guest.post(
            f"/events/{event_id}/appearance",
            data={"csrf_token": csrf(manage), "theme": "sunset"},
            follow_redirects=False,
        )
        assert forbidden.status_code == 403
