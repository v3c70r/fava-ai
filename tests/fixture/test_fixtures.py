"""Layer 2: Ledger fixture integration tests."""
import pytest
from pathlib import Path
from beancount import loader

from tests.conftest import load_fixture, FIXTURES_DIR, MockLedger


@pytest.mark.fixture
def test_parse_beancount_example():
    entries, errors, _ = load_fixture("beancount-example")
    assert len(errors) == 0
    assert len(entries) > 1000


@pytest.mark.fixture
def test_parse_finzytrack():
    from pathlib import Path
    p = FIXTURES_DIR / "finzytrack"
    files = list(p.rglob("*.beancount"))
    if not files:
        pytest.skip("finzytrack files not found")
    entries, errors, _ = loader.load_file(str(files[0]))
    # Might have include errors if includes aren't resolved; just verify it parses
    assert len(entries) > 0


@pytest.mark.fixture
def test_account_extraction():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.knowledge.extractors.accounts import AccountExtractor

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        extractor = AccountExtractor(wiki)
        stats = extractor.extract(entries, options)
        assert stats["accounts_generated"] > 50


@pytest.mark.fixture
def test_merchant_extraction():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.knowledge.extractors.merchants import MerchantExtractor

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        extractor = MerchantExtractor(wiki)
        stats = extractor.extract(entries, options)
        assert stats["merchants_generated"] > 20


@pytest.mark.fixture
def test_recurring_detection():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.knowledge.extractors.recurring import RecurringExtractor

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        extractor = RecurringExtractor(wiki)
        stats = extractor.extract(entries, options)
        assert stats["recurring_generated"] >= 3


@pytest.mark.fixture
def test_full_extraction_pipeline():
    entries, errors, options = load_fixture("beancount-example")
    assert len(errors) == 0

    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.knowledge.engine import KnowledgeEngine

    import tempfile
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

    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.knowledge.engine import KnowledgeEngine

    import tempfile
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
