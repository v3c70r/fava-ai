"""Layer 2: Ledger fixture integration tests."""
from pathlib import Path

import pytest
from beancount import loader

from tests.conftest import MockLedger, load_fixture


@pytest.mark.fixture
def test_parse_beancount_example():
    entries, errors, _ = load_fixture("beancount-example")
    assert len(errors) == 0
    assert len(entries) > 1000


@pytest.mark.fixture
def test_parse_optional_sample_ledger():
    """Parse an external sample ledger if scripts/fetch_sample_ledgers.sh was run.

    These repos are intentionally not vendored (see scripts/fetch_sample_ledgers.sh).
    """
    from tests.conftest import REPO_ROOT
    sample_dir = REPO_ROOT / ".sample-ledgers"
    files = sorted(sample_dir.rglob("*.beancount")) if sample_dir.exists() else []
    if not files:
        pytest.skip("external sample ledgers not fetched; run scripts/fetch_sample_ledgers.sh")
    entries, errors, _ = loader.load_file(str(files[0]))
    # Includes may not resolve standalone; just verify the loader does not crash.
    assert isinstance(entries, list)


@pytest.mark.fixture
def test_account_extraction():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    import tempfile

    from fava_ai.knowledge.extractors.accounts import AccountExtractor
    from fava_ai.knowledge.wiki import WikiManager
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        extractor = AccountExtractor(wiki)
        stats = extractor.extract(entries, options)
        assert stats["accounts_generated"] > 50


@pytest.mark.fixture
def test_merchant_extraction():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    import tempfile

    from fava_ai.knowledge.extractors.merchants import MerchantExtractor
    from fava_ai.knowledge.wiki import WikiManager
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        extractor = MerchantExtractor(wiki)
        stats = extractor.extract(entries, options)
        assert stats["merchants_generated"] > 20


@pytest.mark.fixture
def test_recurring_detection():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    import tempfile

    from fava_ai.knowledge.extractors.recurring import RecurringExtractor
    from fava_ai.knowledge.wiki import WikiManager
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        extractor = RecurringExtractor(wiki)
        stats = extractor.extract(entries, options)
        assert stats["recurring_generated"] >= 3


@pytest.mark.fixture
def test_full_extraction_pipeline():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    import tempfile

    from fava_ai.knowledge.engine import KnowledgeEngine
    from fava_ai.knowledge.wiki import WikiManager
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        engine = KnowledgeEngine(wiki)
        stats = engine.extract_all(entries, options)

        assert "accounts" in stats
        assert "merchants" in stats
        assert "recurring" in stats
        assert "portfolio" in stats
        assert "spending" in stats
        assert "cashflow" in stats
        assert wiki.exists("overview.md")


@pytest.mark.fixture
def test_extraction_idempotent():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    import tempfile

    from fava_ai.knowledge.engine import KnowledgeEngine
    from fava_ai.knowledge.wiki import WikiManager
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        engine = KnowledgeEngine(wiki)
        engine.extract_all(entries, options)
        assert not engine.needs_rebuild(entries)


@pytest.mark.fixture
def test_ledger_tools_on_fixture():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    ledger = MockLedger(entries, options)
    from fava_ai.tools.builtin.ledger import LedgerInfoTool, ListAccountsTool

    info = LedgerInfoTool(ledger).execute()
    import json
    data = json.loads(info.content)
    assert data["transaction_count"] > 1000
    assert "USD" in data["operating_currencies"]

    accounts = ListAccountsTool(ledger).execute()
    data = json.loads(accounts.content)
    assert data["count"] >= 50


# ── rich feature fixture ──────────────────────────────────────────


@pytest.mark.fixture
def test_rich_fixture_parses():
    entries, errors, options = load_fixture("rich-features")
    assert errors == []
    assert any(str(o) == "USD" for o in options.get("operating_currency", []))


@pytest.mark.fixture
def test_portfolio_holdings_from_rich_fixture(tmp_path):
    from fava_ai.knowledge.extractors.portfolio import PortfolioExtractor
    from fava_ai.knowledge.wiki import WikiManager

    entries, errors, options = load_fixture("rich-features")
    assert errors == []

    wiki = WikiManager(tmp_path / "wiki")
    stats = PortfolioExtractor(wiki).extract(entries, options)

    assert stats["holdings"] >= 1
    holdings = wiki.read("portfolio/holdings.md")
    assert "VTI" in holdings.content


@pytest.mark.fixture
def test_full_extraction_on_rich_fixture(tmp_path):
    from fava_ai.knowledge.engine import KnowledgeEngine
    from fava_ai.knowledge.wiki import WikiManager

    entries, errors, options = load_fixture("rich-features")
    assert errors == []

    wiki = WikiManager(tmp_path / "wiki")
    engine = KnowledgeEngine(wiki)
    engine.extract_all(entries, options)

    assert wiki.exists("overview.md")
    assert not engine.needs_rebuild(entries)


@pytest.mark.slow
@pytest.mark.fixture
def test_large_ledger_extraction_performance(tmp_path):
    """Smoke-test extraction on a 5k-transaction ledger."""
    import time
    from datetime import date, timedelta

    from beancount import loader as bc_loader
    from fava_ai.knowledge.engine import KnowledgeEngine
    from fava_ai.knowledge.wiki import WikiManager

    lines = ['option "operating_currency" "USD"', ""]
    lines += [
        "2010-01-01 open Assets:Checking",
        "2010-01-01 open Expenses:Food",
        "2010-01-01 open Income:Salary",
    ]
    start = date(2015, 1, 1)
    for i in range(5000):
        day = start + timedelta(days=i % 3000)
        lines.append(f'{day} * "Merchant{i % 50}" "Purchase {i}"')
        lines.append(f"  Expenses:Food  {10 + i % 200}.00 USD")
        lines.append("  Assets:Checking")

    entries, errors, options = bc_loader.load_string("\n".join(lines))
    assert errors == []

    wiki = WikiManager(tmp_path / "wiki")
    engine = KnowledgeEngine(wiki)

    started = time.time()
    engine.extract_all(entries, options)
    elapsed = time.time() - started

    assert elapsed < 30, f"extraction took {elapsed:.1f}s"
    # Second run is a no-op.
    assert not engine.needs_rebuild(entries)
