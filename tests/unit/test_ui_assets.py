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
    dynamic = ("cfg-", "docs-")  # built at runtime in the panel HTML
    missing = [
        i for i in ids
        if not i.startswith(dynamic) and f'id="{i}"' not in HTML
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


# ── documents (#20, #21) ──────────────────────────────────────────


def test_document_upload_ui_is_wired():
    for element in ("attach-btn", "file-input", "attachment-chips", "panel-documents"):
        assert f'id="{element}"' in HTML, element
    for fn in ("uploadFiles", "renderAttachments", "loadDocuments", "embedDocuments"):
        assert fn in JS, fn
    assert "documents_upload" in JS
    assert "documents?conversation_id=" not in JS  # no hardcoded URL string
    assert "file_ids" in JS


def test_attach_button_is_a_real_paperclip():
    """A Python `\\U0001f4ce` escape was pasted into HTML and rendered literally."""
    assert r"\U0001f4ce" not in HTML
    assert "&#x1F4CE;" in HTML


def test_no_python_unicode_escapes_in_ui_assets():
    """Jinja2 renders HTML verbatim, so a U+1F4CE escape there is literal text.

    JavaScript does interpret its own uXXXX string escapes, so only the
    8-digit Python form is wrong in the JS file.
    """
    assert re.findall(r"\\[Uu][0-9a-fA-F]{4,8}", HTML) == []
    assert re.findall(r"\\U[0-9a-fA-F]{8}", JS) == []


def test_config_panel_exposes_embedding_fields():
    """The embedding endpoint was config-only; it needs a UI surface (1.1)."""
    for field in ("cfg-embed-base-url", "cfg-embed-model", "cfg-embed-api-key",
                  "cfg-docs-enabled"):
        assert field in JS, field
    assert "documents.embedding" in JS


def test_docs_panel_surfaces_extraction_and_embedding_state():
    assert "docs-retry-btn" in JS
    assert "retryDocuments" in JS
    assert "documents_retry" in JS
    assert "pdf_support" in JS
    assert "doc-hint" in HTML and "doc-warning" in HTML


def test_embedding_test_shows_the_backend_error():
    """The panel read `result.error`, but the endpoint returned `detail` (2.1)."""
    assert "result.error || result.detail" in JS


def test_config_labels_are_associated_with_their_inputs():
    """`<label>` without `for=` is invisible to screen readers (round 2, N5)."""
    # Fields are rendered through a helper that emits <label for="${id}">.
    assert '<label for="${id}">' in JS
    for id_, label in (
        ("cfg-base-url", "base_url"),
        ("cfg-api-key", "api_key"),
        ("cfg-embed-base-url", "embedding.base_url"),
        ("cfg-embed-model", "embedding.model"),
        ("cfg-embed-api-key", "embedding.api_key"),
        ("cfg-max-iterations", "max_iterations"),
    ):
        assert f"field('{id_}', '{label}'" in JS, id_
    # The select and the checkbox are written directly.
    assert 'for="cfg-provider"' in JS
    assert 'for="cfg-docs-enabled"' in JS


def test_index_button_reflects_the_enabled_flag():
    """`documents.enabled` gates folder indexing (round 2, N3)."""
    hint = JS.index("Folder indexing is off")
    button = JS.index("buttons.push('<button id=")
    # The hint and the conditional button are emitted together, and the wiring
    # must not assume the button exists.
    assert hint < button
    assert "if (indexBtn)" in JS
