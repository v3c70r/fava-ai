"""Static checks for the UI assets (templates/FavaAI.html, FavaAI.js).

The UI is plain JS/CSS, so these assert the structural intent that would
otherwise only be caught by eye: it must consume Fava's theme variables
(dark-mode aware, issue #16) and keep tool calls collapsed (issue #15).
"""

import re

from tests.conftest import REPO_ROOT

HTML = (REPO_ROOT / "templates" / "FavaAI.html").read_text()
JS = (REPO_ROOT / "FavaAI.js").read_text()


# ── #16 theme awareness ───────────────────────────────────────────


def test_uses_fava_theme_variables():
    for var in (
        "--background",
        "--background-darker",
        "--background-darkest",
        "--border",
        "--border-lighter",
        "--text-color",
        "--text-color-lighter",
        "--text-color-lightest",
        "--link-color",
        "--button-background",
        "--code-background",
        "--table-border",
        "--font-family",
    ):
        assert f"var({var}" in HTML, f"missing Fava theme variable: {var}"


def test_no_hardcoded_palette_values():
    """Hex colours are only allowed as `var(--x, #hex)` fallbacks."""
    bad = re.compile(r":\s*#[0-9a-fA-F]{3,6}\b")
    offenders = [ln.strip() for ln in HTML.splitlines() if bad.search(ln)]
    assert offenders == [], offenders


def test_no_light_only_backgrounds():
    for literal in ("#fafafa", "#e3f0ff", "#2266cc", "#f5f5f5", "#fdecec"):
        assert literal not in HTML, literal


def test_inherits_fava_typography():
    assert "font-family: inherit" in HTML


# ── #15 tool calls are collapsed ──────────────────────────────────


def test_tool_calls_render_in_one_collapsed_block():
    # A single <details> holds every tool call instead of N visible rows.
    assert "tool-activity" in JS
    assert "upsertToolActivity" in JS
    assert "renderToolSteps" in JS
    # The old per-call footer must be gone.
    assert "renderToolCards" not in JS
    assert "provenance-footer" not in JS


def test_tool_activity_is_collapsed_by_default():
    # Created without `open`, and explicitly folded away on completion.
    assert "block.className = 'tool-activity'" in JS
    assert "removeAttribute('open')" in JS
    # The visible summary is a single count, not per-call rows.
    assert "Tool activity (" in JS


def test_tool_activity_styles_exist():
    assert ".tool-activity" in HTML
    assert ".tool-activity > summary" in HTML


# ── wiring sanity ─────────────────────────────────────────────────


def test_js_element_ids_exist_in_template():
    """Every element the JS looks up (except dynamically built ones) exists."""
    ids = set(re.findall(r"getElementById\('([^']+)'\)", JS))
    missing = [
        i for i in ids
        if not i.startswith("cfg-") and f'id="{i}"' not in HTML
    ]
    assert missing == [], missing


# ── #18 scrolling & <details> marker ──────────────────────────────


def test_scroll_follows_only_when_pinned():
    """Auto-scroll must not fight the user scrolling up (issue #18)."""
    assert "scrollToBottom(force = false)" in JS
    # Pinned state is tracked by a scroll listener (not measured after append).
    assert "_atBottom" in JS
    assert "el.scrollHeight - el.scrollTop - el.clientHeight < 80" in JS
    # New turns and conversation loads still jump to the latest.
    assert JS.count("scrollToBottom(true)") >= 2


def test_fava_details_styles_are_reset():
    """Fava styles every <details>; our inline blocks must override it (#18)."""
    # Leave room for Fava's absolutely-positioned summary::before arrow,
    # otherwise it overlaps the label (the reported bug).
    assert "padding: .25em .5em .25em 30px" in HTML
    # Drop Fava's `details { min-width: 400px }` so the block fits the panel.
    assert "min-width: 0" in HTML
