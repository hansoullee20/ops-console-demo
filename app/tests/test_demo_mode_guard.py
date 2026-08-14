"""The public demo must never talk to the operational API.

This is the Phase 2 rule — the mode is decided by the build, and the published
demo has no backend — but until now it was only ever checked by hand.

It failed in production. `safety-ui.js` and `month-close-ui.js` each guarded on
`window.OPS_DATA_MODE`, a global nothing has ever assigned, so their guards were
permanently false and the deployed demo called `/api/v1/...` on load. The code
read as if it were protected; only a browser would have told you otherwise.

Two tests, deliberately different in kind:

* `test_only_the_canonical_demo_signal_is_read` is static and runs everywhere.
  It catches the exact failure mode — a guard wired to a name nobody sets.
* `test_the_published_demo_makes_no_api_request` builds the real artifact and
  drives it in a browser, watching fetch, XHR, form submits and navigation.
  It is the only check that can prove the rule rather than approximate it, and
  it skips when no browser is available (CI runs it in a dedicated job).
"""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.tests.test_demo_site_preserved import STAGED_FILES

# Globals the published page is given from outside the scripts themselves:
# the Pages build injects OPS_MODE, and the generated snapshot defines
# OPS_DEMO_SNAPSHOT. Everything else has to be assigned by a staged script.
INJECTED_GLOBALS = {"OPS_MODE", "OPS_DEMO_SNAPSHOT"}

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")

PUBLIC_SCRIPTS = tuple(f for f in STAGED_FILES if f.endswith(".js") and f != "demo-data.js")


def _script_text(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """The script with comments removed, so prose about a bug is not read as one."""
    source = _BLOCK_COMMENT.sub(" ", _script_text(name))
    return _LINE_COMMENT.sub(" ", source)


def test_no_script_reads_a_global_that_nothing_sets():
    """The failure mode, stated generally.

    `safety-ui.js` and `month-close-ui.js` decided demo mode from
    `window.OPS_DATA_MODE` and `window.__OPS_DEMO_DATA__`. Neither is assigned
    anywhere, in any file, by the build or by the snapshot — so both guards were
    permanently false and the published demo called the operational API. The
    code looked guarded; only a browser could tell you it was not.

    Rather than banning those two names, this asserts the property that made
    them dangerous: a global a script *reads* must be one something *sets*.
    """
    assigned = set(INJECTED_GLOBALS)
    for name in PUBLIC_SCRIPTS:
        assigned |= set(re.findall(r"window\.(OPS_[A-Za-z_]+|__OPS[A-Za-z_]*)\s*=", _code(name)))

    offenders: dict[str, list[str]] = {}
    for name in PUBLIC_SCRIPTS:
        read = set(re.findall(r"window\.(OPS_[A-Za-z_]+|__OPS[A-Za-z_]*)", _code(name)))
        stray = sorted(read - assigned)
        if stray:
            offenders[name] = stray
    assert offenders == {}, (
        "these scripts read globals that nothing assigns: "
        + json.dumps(offenders, ensure_ascii=False)
    )


def test_every_script_that_calls_the_api_has_a_demo_gate():
    ungated = [
        name for name in PUBLIC_SCRIPTS
        if "/api/v1/" in _code(name) and "OPS_IS_DEMO" not in _code(name)
    ]
    assert ungated == [], f"these call the API with no shared demo gate: {ungated}"


def test_data_source_owns_the_decision():
    """One definition, in the file that resolves the mode in the first place."""
    source = _code("data-source.js")
    assert "window.OPS_IS_DEMO = function" in source
    definitions = [n for n in PUBLIC_SCRIPTS if "OPS_IS_DEMO = " in _code(n)]
    assert definitions == ["data-source.js"], f"more than one definition: {definitions}"


# ---------------------------------------------------------------------------
# the browser check
# ---------------------------------------------------------------------------
def build_demo_site(target: Path) -> Path:
    """Assemble the Pages artifact the way the workflow does.

    The file list comes from test_demo_site_preserved.STAGED_FILES, which
    another test already pins to the workflow's own list, so this cannot drift
    from what is actually published.
    """
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "app.exporters.demo_snapshot", str(target / "demo-data.js")],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )
    html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    assert "<!--OPS_DEMO_INJECT-->" in html
    html = html.replace(
        "<!--OPS_DEMO_INJECT-->",
        '<script>window.OPS_MODE="demo";</script>\n<script src="./demo-data.js"></script>',
        1,
    )
    (target / "index.html").write_text(html, encoding="utf-8")
    for name in STAGED_FILES:
        if name in {"index.html", "demo-data.js"}:
            continue
        source = REPO_ROOT / name
        if source.is_file():
            shutil.copy(source, target / name)
    return target


def _serve(directory: Path):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(directory), **k
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _preinstalled_chromium() -> str | None:
    """A browser installed outside Playwright's own cache, if there is one.

    Honours PLAYWRIGHT_BROWSERS_PATH, which is how a host says where it put
    them; falling through to None lets Playwright resolve its own download.
    """
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "/opt/pw-browsers")
    for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome")):
        return str(candidate)
    return None


def _unavailable(reason: str):
    """Skip locally, fail in the job that exists to run this.

    A smoke test that quietly skips because the browser did not install is a
    green tick for a check that never ran.
    """
    if os.environ.get("OPS_REQUIRE_BROWSER") == "1":
        pytest.fail(f"the demo smoke test could not run: {reason}")
    pytest.skip(reason)


@pytest.mark.browser
def test_the_published_demo_makes_no_api_request(tmp_path: Path):
    """Open every tab, run the main actions, and watch for anything /api/.

    fetch and XHR are the obvious channels. Navigation is not: month-close-ui's
    export button sets `location.href` to an API path, so a test that only
    hooked fetch would have called this clean while the browser walked to
    /api/v1/month-close/....
    """
    try:
        from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        return _unavailable("playwright is not installed")

    site = build_demo_site(tmp_path / "_site")
    server, port = _serve(site)
    attempts: list[str] = []
    errors: list[str] = []

    try:
        with sync_playwright() as api:
            executable = _preinstalled_chromium()
            try:
                browser = api.chromium.launch(
                    **({"executable_path": executable} if executable else {})
                )
            except PlaywrightError as exc:
                return _unavailable(f"no chromium available ({str(exc)[:80]})")
            page = browser.new_context(viewport={"width": 1400, "height": 950}).new_page()

            # every outbound request, whatever started it
            page.on("request", lambda r: attempts.append(f"{r.method} {r.url}")
                    if "/api/" in r.url else None)
            # and every attempt to leave the page for one
            page.on("framenavigated", lambda f: attempts.append(f"navigate {f.url}")
                    if "/api/" in f.url else None)
            page.on("pageerror", lambda e: errors.append(str(e)[:160]))

            # A prompt() that is dismissed makes the handler return before it ever
            # reaches the API, which would pass this test for the wrong reason.
            page.on("dialog", lambda d: d.accept("테스트 사유"))

            page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="networkidle")
            page.wait_for_timeout(800)

            # every tab, including the ones the newer UI files add themselves
            tabs = page.query_selector_all("#topNav button")
            assert len(tabs) >= 6, f"expected the full tab set, found {len(tabs)}"
            for tab in tabs:
                tab.click()
                page.wait_for_timeout(400)
                page.evaluate("() => window.closeDrawer && window.closeDrawer()")

            # and the operator actions that reach for the API. Dispatched
            # directly rather than clicked, so a button hidden by CSS is still
            # exercised: the guard is what is under test, not the layout.
            for selector in (
                "header .topbtn.primary",                    # 지문 XLS 가져오기
                "header .topbtn:not(.primary)",              # 원본기록
                "#closeReload", "#closeMonthButton",
                "#exportMonth", "#reopenMonth",
            ):
                page.evaluate(
                    "(s) => { const el = document.querySelector(s); if (el) el.click(); }",
                    selector,
                )
                page.wait_for_timeout(350)
                page.evaluate("() => window.closeDrawer && window.closeDrawer()")

            page.wait_for_timeout(600)
            browser.close()
    finally:
        server.shutdown()

    assert attempts == [], "the public demo reached for the operational API: " + "; ".join(attempts)
    assert errors == [], "the public demo raised: " + "; ".join(errors)
