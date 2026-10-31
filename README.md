# Gatherly

Gatherly is a local-first, privacy-conscious event photo sharing app. People join
private events, optionally enroll their face, and receive photos in which they
are confidently matched.

## Included in the first milestone

- Local email/password accounts
- Private events with shareable invite codes
- Event-specific consent and face enrollment
- Private photo storage (files are never exposed as a public directory)
- Local face detection and matching with OpenCV YuNet + SFace
- Personal galleries, uncertain-match review, and deletion controls
- SQLite database and local filesystem storage

## Run locally

```bash
UV_CACHE_DIR=.uv-cache uv sync
.venv/bin/python scripts/download_models.py
./scripts/run_local.sh
```

Open <http://127.0.0.1:8000>.

For this checked-out workspace, setup and model download have already been
completed. You only need `./scripts/run_local.sh` after a restart.

The first model download is approximately 40 MB. All recognition then happens
on your computer. Uploaded data is written under `data/`, which is ignored by
Git.

## Resetting local development data

Stop the server, move the `data/` directory somewhere safe, and start the app
again. Avoid deleting it unless you are certain you no longer need the photos.

## Recognition policy

Recognition searches only face profiles enrolled in the same event. Strong
matches appear in a participant's gallery. Borderline matches require that
participant to confirm them. Weak matches are discarded. Reference photos and
derived embeddings can be deleted from the event page at any time.

This is an early local prototype, not a production biometric system. Before a
public deployment, add independent security/privacy review, background jobs,
backups, rate limiting, and jurisdiction-specific consent policies.

