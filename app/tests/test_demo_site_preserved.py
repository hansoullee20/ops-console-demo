"""Guards on the public static demo (AI_BUILD_PLAN.md §7 Phase 0 / Phase 1).

Phase 1 adds a backend without changing the demo. These tests fail loudly if a
later change moves the published files or starts publishing the backend, the
database or uploads to GitHub Pages.
"""

from __future__ import annotations

import re

from app.config import REPO_ROOT

PUBLIC_FILES = ("index.html", "profile.css", "profile.js", ".nojekyll")
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pages.yml"
NEVER_PUBLISHED = ("app", "data", "uploads", "backups", "requirements.txt")


def test_demo_files_stay_at_repository_root():
    """GitHub Pages serves from the repository root; moving these changes the
    live demo URL."""
    for name in PUBLIC_FILES:
        assert (REPO_ROOT / name).exists(), f"public demo file went missing: {name}"


def test_demo_entrypoint_is_still_the_mock_console():
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    assert "<!doctype html>" in html.lower()
    assert 'lang="ko"' in html
    # the demo still carries its own mock dataset; Phase 2 is what replaces it
    assert "const employees=" in html


def test_pages_workflow_publishes_an_allowlist_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    upload_paths = re.findall(r"^\s*path:\s*(\S+)\s*$", workflow, flags=re.MULTILINE)
    assert upload_paths, "no upload path found in the Pages workflow"
    assert upload_paths == ["_site"], (
        f"Pages must publish the staged allowlist only, found: {upload_paths}"
    )


def test_pages_workflow_never_stages_backend_or_data():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    staging = workflow.split("Stage public demo files", 1)[-1].split("Configure Pages", 1)[0]
    copied = re.search(r"for f in ([^;]+); do", staging)
    assert copied, "staging step no longer copies an explicit file list"
    staged = copied.group(1).split()
    assert set(staged) == set(PUBLIC_FILES)
    for forbidden in NEVER_PUBLISHED:
        assert forbidden not in staged


def test_gitignore_keeps_operational_data_out_of_git():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("data/*", "uploads/*", "backups/*", "*.db", ".env"):
        assert pattern in gitignore, f"missing .gitignore entry: {pattern}"


def test_no_database_file_is_committed():
    tracked_dbs = [
        path
        for path in REPO_ROOT.rglob("*.db")
        if ".git" not in path.parts and "backups" not in path.parts
    ]
    assert tracked_dbs == [] or all(
        path.parent.name == "data" for path in tracked_dbs
    ), f"database files outside data/: {tracked_dbs}"
