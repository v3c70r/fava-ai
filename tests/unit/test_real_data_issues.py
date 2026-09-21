"""Regression tests for the issues reported from a real-world ledger run.

Each test maps to a GitHub issue; the shared fixture mimics the reported
conditions: narration-only descriptions, two operating currencies, hierarchical
accounts, a fully-sold investment, and price data.
"""

from pathlib import Path, PureWindowsPath

import pytest
from beancount import loader
from fava_ai.knowledge.engine import KnowledgeEngine
from fava_ai.knowledge.wiki import WikiManager, _rel_posix
from fava_ai.tools.builtin.ledger import ListAccountsTool

from tests.conftest import REPO_ROOT, MockLedger

FIXTURE = "narration-multi-currency"


@pytest.fixture
def ledger():
    entries, errors, options = loader.load_file(
        REPO_ROOT / "tests" / "data" / "ledgers" / f"{FIXTURE}.beancount"
    )
    assert errors == []
    return MockLedger(entries, options)


@pytest.fixture
def wiki(tmp_path, ledger):
    w = WikiManager(tmp_path / "wiki")
    KnowledgeEngine(w).extract_all(ledger.all_entries, ledger.options)
    return w


# ── #3 narration-only ledgers must still produce merchants & recurring ──


def test_narration_only_merchants_generated(wiki):
    names = {p.stem for p in (wiki.wiki_dir / "merchants").glob("*.md")}
    assert "coffee-shop" in names
    assert "grocery-store" in names
    assert "rent-payment" in names


def test_narration_only_recurring_detected(wiki):
    names = {p.stem for p in (wiki.wiki_dir / "recurring").glob("*.md")}
    assert "coffee-shop" in names
    assert "rent-payment" in names
    assert "grocery-store" in names


def test_merchant_page_keeps_per_currency_totals(wiki):
    page = wiki.read("merchants/us-employer.md")
    assert "USD" in page.content


# ── #4 account pages must not list themselves as sub-accounts ──


def test_leaf_account_has_no_self_subaccount(wiki):
    leaf = (wiki.wiki_dir / "accounts" / "Expenses-Grocery.md").read_text()
    assert "## Sub-accounts" not in leaf

    parent = (wiki.wiki_dir / "accounts" / "Assets-Bank.md").read_text()
    assert "[[accounts/Assets-Bank-Checking.md|Assets:Bank:Checking]]" in parent
    # Not itself, and not grandchildren.
    assert "|Assets:Bank]]" not in parent
    assert "Assets:Bank:Checking:Sub" not in parent


def test_account_page_has_own_and_aggregate_balance(wiki):
    parent = wiki.read("accounts/Assets.md")
    assert "Balance (own)" in parent.content
    assert "Balance (including sub-accounts)" in parent.content


# ── #5 wiki paths must use forward slashes on every OS ──


def test_rel_posix_uses_forward_slashes_on_windows():
    base = PureWindowsPath("wiki")
    path = base / "accounts" / "Assets-Bank-Checking.md"
    assert _rel_posix(path, base) == "accounts/Assets-Bank-Checking.md"


def test_wiki_paths_are_posix(wiki):
    for page in wiki.list_pages():
        assert "\\" not in page["path"]
    index = (wiki.wiki_dir / "index.md").read_text()
    assert "[[accounts/" in index
    assert "accounts\\" not in index


# ── #6 overview links must resolve ──


def test_overview_section_links_exist(wiki):
    overview = (wiki.wiki_dir / "overview.md").read_text()
    for rel in ("accounts/_index.md", "merchants/_index.md", "recurring/_index.md"):
        assert rel in overview
        assert (wiki.wiki_dir / rel).exists()
        assert wiki.exists(rel)


def test_section_index_lists_its_pages(wiki):
    index = wiki.read("merchants/_index.md")
    assert "[[merchants/" in index.content


# ── #7 list_accounts: aggregate balances, substring filter, capping ──


def test_list_accounts_reports_aggregate_balances(ledger):
    result = ListAccountsTool(ledger).execute(prefix="Assets")
    import json

    data = json.loads(result.content)
    assets = next(a for a in data["accounts"] if a["account"] == "Assets")
    # Own balance is zero, aggregate is not (the classic bug).
    assert assets["balance"] == "0"
    assert assets["aggregate_balance"] != "0"


def test_list_accounts_contains_filter(ledger):
    import json

    data = json.loads(ListAccountsTool(ledger).execute(contains="grocery").content)
    assert [a["account"] for a in data["accounts"]] == ["Expenses:Grocery"]


def test_list_accounts_caps_and_reports_totals(ledger):
    import json

    data = json.loads(ListAccountsTool(ledger).execute(limit=2).content)
    assert data["count"] == 2
    assert data["total_matching"] > 2
    assert data["truncated"] is True


# ── #8 spending/cashflow must not drop non-first operating currencies ──


def test_spending_includes_all_currencies(wiki):
    content = (wiki.wiki_dir / "patterns" / "spending.md").read_text()
    assert "## CAD" in content
    assert "## USD" in content
    # Travel is a USD-only expense account and must appear.
    assert "Expenses:Travel" in content
    assert "USD" in content.split("## USD", 1)[1]


def test_cashflow_includes_all_currencies(wiki):
    content = (wiki.wiki_dir / "patterns" / "cashflow.md").read_text()
    assert "## CAD" in content
    assert "## USD" in content


# ── #9 wiki_search: stemming + word boundaries ──


def test_search_matches_singular_plural(wiki):
    paths = [r["path"] for r in wiki.search("groceries")]
    assert any(p.startswith("merchants/grocery-store") for p in paths)
    assert any(p.startswith("accounts/Expenses-Grocery") for p in paths)


def test_search_matches_frontmatter_type(wiki):
    """Frontmatter `type` must stay searchable (it names the page's kind)."""
    for query in ("merchant", "merchants", "recurring", "patterns"):
        paths = [r["path"] for r in wiki.search(query)]
        assert paths, f"no results for {query!r}"


def test_account_pages_are_compact(ledger):
    """Aggregate balances must not inline per-lot detail (found in review)."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        w = WikiManager(Path(d) / "wiki")
        KnowledgeEngine(w).extract_all(ledger.all_entries, ledger.options)
        sizes = [
            p.stat().st_size
            for p in (Path(d) / "wiki" / "accounts").glob("*.md")
            if p.name != "_index.md"
        ]
        # Per-lot inventories made some pages >9KB on a real ledger.
        assert max(sizes) < 3000, f"account page too large: {max(sizes)}"


def test_search_does_not_match_substring_of_longer_word(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write(
        "patterns/cashflow.md",
        "# Cash Flow\nNet worth summary",
        {"title": "Cash Flow", "type": "patterns"},
    )
    wiki.write(
        "merchants/internet.md",
        "# Internet Provider\nMonthly internet bill",
        {"title": "Internet Provider", "type": "merchant"},
    )

    paths = [r["path"] for r in wiki.search("net worth")]
    assert "patterns/cashflow.md" in paths
    assert "merchants/internet.md" not in paths


# ── #10 portfolio: drop closed positions, add valuation ──


def test_portfolio_excludes_closed_positions(wiki):
    content = (wiki.wiki_dir / "portfolio" / "holdings.md").read_text()
    assert "| VTI |" in content
    assert "| BOND |" not in content
    assert "Closed positions" in content
    assert "BOND" in content


def test_portfolio_includes_cost_basis_and_market_value(wiki):
    content = (wiki.wiki_dir / "portfolio" / "holdings.md").read_text()
    assert "Cost basis" in content
    assert "Market value" in content
    assert "1000.00 CAD" in content   # 10 VTI @ 100 cost
    assert "1200.00 CAD" in content   # 10 VTI @ 120 market price


# ── #11 / #12 UI: no native dialogs, config is editable ──


def test_ui_has_no_blocking_native_dialogs():
    js = (REPO_ROOT / "FavaAI.js").read_text()
    assert "!confirm(" not in js
    assert "prompt('" not in js
    assert 'prompt("' not in js


def test_ui_has_inline_rename_delete_and_config_form():
    js = (REPO_ROOT / "FavaAI.js").read_text()
    assert "beginRename" in js
    assert "requestDelete" in js
    assert "saveConfig" in js
