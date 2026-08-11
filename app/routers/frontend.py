"""Serve the operations console UI from the work-PC host.

The frontend deliberately stays at the repository root (see frontend/README.md),
so this router serves those files by an explicit allowlist. Mounting the
repository directory would expose app/, data/, uploads/ and backups/ — the same
mistake the GitHub Pages workflow used to make.

Note what is NOT in the allowlist: `demo-data.js`. The fictional snapshot is
only ever built into the Pages artifact. It does not exist on the work PC, so
the operational app cannot show demo data even by accident.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import REPO_ROOT

router = APIRouter(tags=["frontend"])

PUBLIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "profile.css": "text/css; charset=utf-8",
    "profile.js": "application/javascript; charset=utf-8",
    "data-source.js": "application/javascript; charset=utf-8",
}


def _serve(name: str) -> FileResponse:
    path = REPO_ROOT / name
    if name not in PUBLIC_FILES or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path,
        media_type=PUBLIC_FILES[name],
        headers={"Cache-Control": "no-store"},
    )


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    return _serve("index.html")


@router.get("/{filename}", include_in_schema=False)
def asset(filename: str) -> FileResponse:
    return _serve(filename)
