"""Shared test fixtures."""
import tempfile
from pathlib import Path
from decimal import Decimal

import pytest

from beancount import loader
from beancount.core.data import Transaction, Posting
from beancount.core.amount import Amount
from beancount.core.inventory import Inventory


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ledgers"


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_entries():
    """Synthetic beancount entries for deterministic tests."""
    from datetime import date
    return [
        Transaction(
            meta={},
            date=date(2025, 1, 1),
            flag="*",
            payee="Amazon",
            narration="Books",
            tags=set(),
            links=set(),
            postings=[
                Posting(
                    account="Expenses:Shopping",
                    units=Amount(Decimal("42.97"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
                Posting(
                    account="Assets:Checking",
                    units=Amount(Decimal("-42.97"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
            ],
        ),
        Transaction(
            meta={},
            date=date(2025, 1, 15),
            flag="*",
            payee="Netflix",
            narration="Monthly subscription",
            tags=set(),
            links=set(),
            postings=[
                Posting(
                    account="Expenses:Entertainment",
                    units=Amount(Decimal("15.99"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
                Posting(
                    account="Assets:Checking",
                    units=Amount(Decimal("-15.99"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
            ],
        ),
        Transaction(
            meta={},
            date=date(2025, 2, 1),
            flag="*",
            payee="Amazon",
            narration="Electronics",
            tags=set(),
            links=set(),
            postings=[
                Posting(
                    account="Expenses:Shopping",
                    units=Amount(Decimal("89.99"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
                Posting(
                    account="Assets:Checking",
                    units=Amount(Decimal("-89.99"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
            ],
        ),
        Transaction(
            meta={},
            date=date(2025, 2, 15),
            flag="*",
            payee="Netflix",
            narration="Monthly subscription",
            tags=set(),
            links=set(),
            postings=[
                Posting(
                    account="Expenses:Entertainment",
                    units=Amount(Decimal("15.99"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
                Posting(
                    account="Assets:Checking",
                    units=Amount(Decimal("-15.99"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
            ],
        ),
        Transaction(
            meta={},
            date=date(2025, 3, 1),
            flag="*",
            payee="Amazon",
            narration="Household",
            tags=set(),
            links=set(),
            postings=[
                Posting(
                    account="Expenses:Shopping",
                    units=Amount(Decimal("120.00"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
                Posting(
                    account="Assets:Checking",
                    units=Amount(Decimal("-120.00"), "USD"),
                    cost=None, price=None, flag=None, meta={},
                ),
            ],
        ),
    ]


def load_fixture(name: str):
    """Load a beancount fixture file by name (e.g. 'beancount-example')."""
    paths = list(FIXTURES_DIR.rglob(f"{name}*.beancount"))
    if not paths:
        paths = [FIXTURES_DIR / f"{name}.beancount"]
    path = paths[0]
    entries, errors, options = loader.load_file(str(path))
    return entries, errors, options


class MockLedger:
    """Mock Fava ledger for testing without Fava."""
    def __init__(self, entries, options, file_path="/tmp/test.beancount"):
        self.all_entries = entries
        self.options = options
        self.beancount_file_path = file_path
