"""Unit tests for built-in ledger tools."""
import json
import pytest
from pathlib import Path
from decimal import Decimal
from beancount.core.data import Transaction, Posting
from beancount.core.amount import Amount

from fava_ai.tools.builtin.ledger import (
    RunBQLTool,
    ListAccountsTool,
    LedgerInfoTool,
    SearchTransactionsTool,
    AccountDetailsTool,
)


@pytest.fixture
def mock_ledger(sample_entries):
    from tests.conftest import MockLedger

    return MockLedger(sample_entries, {"operating_currency": ["USD"]})


def test_ledger_info(mock_ledger):
    tool = LedgerInfoTool(mock_ledger)
    result = tool.execute()
    data = json.loads(result.content)
    assert "USD" in data["operating_currencies"]
    assert data["transaction_count"] == 5
    assert data["account_count"] == 3
    assert "2025-01-01" in data["date_range"]
    assert "2025-03-01" in data["date_range"]


def test_list_accounts_all(mock_ledger):
    tool = ListAccountsTool(mock_ledger)
    result = tool.execute()
    data = json.loads(result.content)
    assert data["count"] > 0


def test_list_accounts_with_prefix(mock_ledger):
    tool = ListAccountsTool(mock_ledger)
    result = tool.execute(prefix="Expenses")
    data = json.loads(result.content)
    for acct in data["accounts"]:
        assert acct["account"].startswith("Expenses")


def test_search_transactions(mock_ledger):
    tool = SearchTransactionsTool(mock_ledger)
    result = tool.execute(q="Amazon")
    data = json.loads(result.content)
    assert data["count"] == 3
    for r in data["results"]:
        assert "Amazon" in r["payee"]


def test_search_transactions_no_match(mock_ledger):
    tool = SearchTransactionsTool(mock_ledger)
    result = tool.execute(q="nonexistent_xyz")
    data = json.loads(result.content)
    assert data["count"] == 0


def test_search_transactions_case_insensitive(mock_ledger):
    tool = SearchTransactionsTool(mock_ledger)
    result = tool.execute(q="amazon")
    data = json.loads(result.content)
    assert data["count"] == 3


def test_account_details(mock_ledger):
    tool = AccountDetailsTool(mock_ledger)
    result = tool.execute(account="Expenses:Shopping")
    data = json.loads(result.content)
    assert data["account"] == "Expenses:Shopping"
    assert data["total_postings"] == 3


def test_account_details_not_found(mock_ledger):
    tool = AccountDetailsTool(mock_ledger)
    result = tool.execute(account="Expenses:Nonexistent")
    data = json.loads(result.content)
    assert data["total_postings"] == 0


def test_run_bql_basic():
    from tests.conftest import load_fixture, MockLedger
    entries, _, options = load_fixture("beancount-example")
    ledger = MockLedger(entries, options)
    tool = RunBQLTool(ledger)
    result = tool.execute(
        query="SELECT account, sum(position) GROUP BY account"
    )
    data = json.loads(result.content)
    assert data["row_count"] >= 3


def test_run_bql_filtered():
    from tests.conftest import load_fixture, MockLedger
    entries, _, options = load_fixture("beancount-example")
    ledger = MockLedger(entries, options)
    tool = RunBQLTool(ledger)
    result = tool.execute(
        query="SELECT account, sum(position) WHERE account ~ 'Expenses' GROUP BY account"
    )
    data = json.loads(result.content)
    for r in data["rows"]:
        assert r["account"].startswith("Expenses")


def test_run_bql_invalid_syntax(mock_ledger):
    tool = RunBQLTool(mock_ledger)
    result = tool.execute(query="INVALID BQL SYNTAX !!!")
    assert "BQL Error" in result.content


def test_ledger_tools_registration():
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools

    reg = ToolRegistry()
    from tests.conftest import MockLedger
    ledger = MockLedger([], {"operating_currency": ["USD"]})
    register_ledger_tools(reg, ledger)

    tools = reg.list_tools()
    names = {t.name for t in tools}
    assert "run_bql" in names
    assert "list_accounts" in names
    assert "ledger_info" in names
    assert "search_transactions" in names
    assert "account_details" in names
