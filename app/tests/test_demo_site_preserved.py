"""Guards on the public static demo (AI_BUILD_PLAN.md §7 Phase 0 / Phase 1).

Phase 1 adds a backend without changing the demo. These tests fail loudly if a
later change moves the published files or starts publishing the backend, the
database or uploads to GitHub Pages.
"""

from __future__ import annotations

import re
import subprocess

from app.config import REPO_ROOT

# Committed files the public build serves. `demo-data.js` is generated at
# deploy time and is deliberately not here.
PUBLIC_FILES = ("index.html", "profile.css", "profile.js", "data-source.js",
                "import-ui.js", "phase4-ui.js", "month-close-ui.js", "mobile.html", "mobile.css", "mobile-period.css", "mobile-full.css",
                "mobile.js", ".nojekyll")
STAGED_FILES = PUBLIC_FILES + ("demo-data.js",)
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pages.yml"
NEVER_PUBLISHED = ("app", "data", "uploads", "backups", "requirements.txt")


def test_demo_files_stay_at_repository_root():
    """GitHub Pages serves from the repository root; moving these changes the
    live demo URL."""
    for name in PUBLIC_FILES:
        assert (REPO_ROOT / name).exists(), f"public demo file went missing: {name}"


def test_index_no_longer_carries_its_own_dataset():
    """Phase 2 replaced the inline mock data with a single backend source."""
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    assert "<!doctype html>" in html.lower()
    assert 'lang="ko"' in html
    assert "const employees=[{" not in html
    assert "let employees=[];" in html
    assert "let days=[];" in html
    assert "let monthStats={};" in html


def test_index_references_its_assets_statically():
    """The local app and the deployed demo must be the same page: the workflow
    adds cache-busting to these references, it does not create them."""
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    for asset in ("profile.css", "profile.js", "data-source.js", "import-ui.js"):
        assert f'"./{asset}"' in html, f"{asset} is not referenced statically"
    assert "<!--OPS_DEMO_INJECT-->" in html


def test_operational_build_carries_no_demo_marker():
    """Demo mode is injected only into the deployed artifact."""
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    assert 'OPS_MODE="demo"' not in html
    assert "demo-data.js" not in html


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
    assert set(staged) == set(STAGED_FILES)
    for forbidden in NEVER_PUBLISHED:
        assert forbidden not in staged


def test_gitignore_keeps_operational_data_out_of_git():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("data/*", "uploads/*", "backups/*", "*.db", ".env"):
        assert pattern in gitignore, f"missing .gitignore entry: {pattern}"


def test_no_operational_file_is_tracked_by_git():
    """Ask git what is actually committed. Walking the working tree proves
    nothing about the repository."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")

    forbidden = re.compile(
        r"(\.db|\.db-wal|\.db-shm|\.sqlite3?|\.env|\.xls|\.xlsx|\.pem|\.key|\.p12)$",
        re.IGNORECASE,
    )
    offenders = [p for p in tracked if p and forbidden.search(p)]
    assert offenders == [], f"operational/secret files are committed: {offenders}"

    # the runtime directories are tracked only as empty placeholders
    for directory in ("data", "uploads", "backups"):
        contents = [p for p in tracked if p.startswith(f"{directory}/")]
        assert contents == [f"{directory}/.gitkeep"], (
            f"{directory}/ must contain only .gitkeep in git, found: {contents}"
        )


def test_operational_paths_are_actually_ignored_by_git():
    """.gitignore entries are only worth as much as git's own answer."""
    probes = {
        "data/ops_console.db": True,
        "uploads/employee-photo.jpg": True,
        "backups/snapshot.db": True,
        "app/main.py": False,
        "index.html": False,
    }
    for path, should_be_ignored in probes.items():
        result = subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True
        )
        ignored = result.returncode == 0
        assert ignored is should_be_ignored, (
            f"{path}: expected ignored={should_be_ignored}, got {ignored}"
        )


# ---------------------------------------------------------------------------
# Phase 2 cross-check found several views still carrying their own copy of the
# demo people, or figures invented from row indexes. These pin the fixes.
# ---------------------------------------------------------------------------
FICTIONAL_NAMES = (
    "김가람", "박나래", "이도연", "최라온", "정마루", "한보람", "윤새봄",
    "임서윤", "강하늘", "오예린", "송지우", "문채원", "백하린", "권유진",
    "서지안", "홍다은", "노수빈", "배예나",
)

# The AI assistant is an explicit mock (labelled MOCK in the UI) and belongs to
# a later phase; its scripted replies may name people.
AI_MOCK_MARKERS = ("sendAI", "aiChat", "ai-fab", "askQuick")


def test_no_view_carries_its_own_copy_of_the_people():
    """Every tab must render the one dataset the backend supplies."""
    offenders = []
    for number, line in enumerate((REPO_ROOT / "index.html").read_text(encoding="utf-8").splitlines(), 1):
        if any(marker in line for marker in AI_MOCK_MARKERS):
            continue
        found = sorted({name for name in FICTIONAL_NAMES if name in line})
        if found:
            offenders.append(f"line {number}: {found}")
    assert offenders == [], (
        "index.html hard-codes employee names outside the AI mock: " + "; ".join(offenders)
    )


def test_attendance_marks_are_not_invented_from_row_indexes():
    """The 근태 tab used to paint 병/휴 by row index for only the first ten
    people, independent of the real attendance rows."""
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    assert "slice(0,10)" not in html
    assert "idx===0" not in html
    assert "function renderAttendance(){renderAttendanceGrid()}" in html


def test_every_render_hook_index_calls_actually_exists():
    """index.html delegates to these; a missing one silently breaks a view.

    The monthly view was lost this way once: `renderMonthly` shared a line with
    the mock `monthStats` literal and went with it.
    """
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    script = (REPO_ROOT / "data-source.js").read_text(encoding="utf-8")

    for name in ("renderOps", "renderDaily", "renderWeekly", "renderMonthly",
                 "renderAttendance", "renderEmployees"):
        assert f"function {name}(" in html, f"index.html lost {name}()"

    for name in ("periodTitleFor", "dailyAside", "renderAttendanceGrid",
                 "renderLeave", "renderEmployeeBrief", "renderAttendanceSummary"):
        assert f"window.{name} =" in script, f"data-source.js does not define {name}()"

    # these three are called from index.html itself
    for name in ("periodTitleFor", "dailyAside", "renderAttendanceGrid"):
        assert name in html, f"index.html never calls {name}()"


def test_dynamic_containers_exist_for_every_derived_view():
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    for element_id in ("leaveTable", "leaveSummary", "empBrief", "attendanceSummary",
                       "attendanceIssueCount", "attendanceMonth", "leaveMonth"):
        assert f'id="{element_id}"' in html, f"missing container #{element_id}"


def test_no_template_placeholder_survives_in_a_quoted_string():
    """`${dailyAside()}` was once inserted into a single-quoted string, so it
    rendered literally instead of calling the function."""
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    for hook in ("dailyAside", "renderAttendanceGrid"):
        assert "${" + hook not in html, f"${{{hook}()}} is not interpolated in a quoted string"

