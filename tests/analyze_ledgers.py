#!/usr/bin/env python3
"""Analyze all test fixture ledgers using beancount's loader."""

import os
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import date

from beancount import loader
from beancount.core import data, getters
from beancount.core.data import Transaction, Open, Close, Commodity, Note, Document
from beancount.core.number import D

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ledgers"

# Maps cloned dirs to their main entrypoint
KNOWN_ENTRIES = {
    "beancount-example.beancount": Path("beancount-example.beancount"),  # single file
    "beancount-boilerplate-cn": Path("ledger/main.beancount"),
    "financeiro": Path("financeiro/main.beancount"),
    "comptabilite": Path("ledger/main.beancount"),
    "beancounters": Path("main.beancount"),
    "cfo-stack": None,  # has 6 sub-scenarios
    "finzytrack": Path("backend/resources/seed_data/ledgers/fake-multi/main.beancount"),
}

# CFO stack has multiple entry points
CFO_SCENARIOS = {
    "cfo-stack/usa-individual": "examples/usa-individual/main.beancount",
    "cfo-stack/usa-family": "examples/usa-family/main.beancount",
    "cfo-stack/usa-company": "examples/usa-company/main.beancount",
    "cfo-stack/canadian-individual": "examples/canadian-individual/main.beancount",
    "cfo-stack/canadian-family": "examples/canadian-family/main.beancount",
    "cfo-stack/canadian-company": "examples/canadian-company/main.beancount",
}


def analyze_ledger(path: Path, label: str) -> dict | None:
    """Load and analyze a single beancount file."""
    try:
        entries, errors, options = loader.load_file(str(path))
    except Exception as e:
        return {"label": label, "path": str(path), "error": str(e)}

    txns = [e for e in entries if isinstance(e, Transaction)]
    opens = [e for e in entries if isinstance(e, Open)]
    closes = [e for e in entries if isinstance(e, Close)]
    commodities = [e for e in entries if isinstance(e, Commodity)]
    notes = [e for e in entries if isinstance(e, Note)]
    documents = [e for e in entries if isinstance(e, Document)]

    accounts = getters.get_accounts(entries)
    currencies = set()
    for txn in txns:
        for posting in txn.postings:
            if posting.units:
                currencies.add(posting.units.currency)

    payees = Counter()
    narrations = []
    tags = Counter()
    links = Counter()
    meta_keys = Counter()
    for txn in txns:
        if txn.payee:
            payees[txn.payee] += 1
        if txn.narration:
            narrations.append(txn.narration)
        if txn.tags:
            for tag in txn.tags:
                tags[tag] += 1
        if txn.links:
            for link in txn.links:
                links[link] += 1
        if txn.meta:
            for k in txn.meta:
                if k not in ("filename", "lineno"):
                    meta_keys[k] += 1

    dates = [txn.date for txn in txns]
    date_range = (min(dates), max(dates)) if dates else (None, None)

    # Detect recurring payees (payees appearing with regular intervals)
    recurring_candidates = []
    payee_dates = defaultdict(list)
    for txn in txns:
        if txn.payee:
            payee_dates[txn.payee].append(txn.date)
    for payee, dlist in payee_dates.items():
        if len(dlist) >= 3:
            sorted_dates = sorted(dlist)
            # Check for monthly pattern
            monthly = True
            for i in range(1, min(len(sorted_dates), 6)):
                diff = (sorted_dates[i] - sorted_dates[i-1]).days
                if not (25 <= diff <= 35):
                    monthly = False
                    break
            if monthly:
                recurring_candidates.append(payee)

    return {
        "label": label,
        "path": str(path),
        "errors": len(errors),
        "error_msgs": [str(e) for e in errors[:5]],
        "total_entries": len(entries),
        "transactions": len(txns),
        "accounts": len(accounts),
        "open_accounts": len(opens),
        "closed_accounts": len(closes),
        "commodities": len(commodities),
        "currencies": sorted(currencies),
        "operating_currency": options.get("operating_currency", []),
        "title": options.get("title", ""),
        "date_range": (
            str(date_range[0]) if date_range[0] else None,
            str(date_range[1]) if date_range[1] else None,
        ),
        "unique_payees": len(payees),
        "top_payees": payees.most_common(10),
        "tags_count": len(tags),
        "top_tags": tags.most_common(5),
        "links_count": len(links),
        "meta_keys": dict(meta_keys),
        "recurring_candidates": recurring_candidates[:10],
        "notes": len(notes),
        "documents": len(documents),
        "has_balance_assertions": any(
            isinstance(e, data.Balance) for e in entries
        ),
        "has_prices": any(
            isinstance(e, data.Price) for e in entries
        ),
        "file_size_bytes": os.path.getsize(path) if path.exists() else 0,
    }


def main():
    results = []
    fixtures_base = FIXTURES_DIR.resolve()

    for name, rel_entry in KNOWN_ENTRIES.items():
        if rel_entry is None:
            continue
        path = fixtures_base / name / rel_entry if rel_entry != Path(name) else fixtures_base / name
        if not path.exists():
            print(f"SKIP {name}: file not found at {path}")
            continue
        print(f"ANALYZING {name}...")
        r = analyze_ledger(path, name)
        if r:
            results.append(r)

    # CFO stack scenarios
    for label_suffix, rel_entry in CFO_SCENARIOS.items():
        path = fixtures_base / "cfo-stack" / rel_entry
        if not path.exists():
            print(f"SKIP {label_suffix}: file not found at {path}")
            continue
        print(f"ANALYZING {label_suffix}...")
        r = analyze_ledger(path, label_suffix)
        if r:
            results.append(r)

    # Also check finzytrack one.beancount and fake.beancount
    for seed_file in ["one.beancount", "fake.beancount"]:
        path = fixtures_base / "finzytrack" / "backend" / "resources" / "seed_data" / "ledgers" / seed_file
        if path.exists():
            print(f"ANALYZING finzytrack/{seed_file}...")
            r = analyze_ledger(path, f"finzytrack/{seed_file}")
            if r:
                results.append(r)

    # Print results
    print("\n" + "="*80)
    print("LEDGER ANALYSIS RESULTS")
    print("="*80)

    for r in sorted(results, key=lambda x: x.get("error", "") != ""):
        print(f"\n{'─'*60}")
        print(f"  {r['label']}")
        print(f"  Path: {r['path']}")
        if r.get("error"):
            print(f"  ** LOAD ERROR: {r['error']} **")
            continue

        print(f"  Status: {r['errors']} errors, {r['total_entries']} entries")
        if r["error_msgs"]:
            for em in r["error_msgs"]:
                print(f"    ↳ {em}")

        print(f"  Title: {r['title']}")
        print(f"  Operating currency: {r['operating_currency']}")
        print(f"  Currencies used: {r['currencies']}")
        print(f"  Date range: {r['date_range'][0]} → {r['date_range'][1]}")
        print(f"  File size: {r['file_size_bytes']:,} bytes")

        print(f"  Transactions: {r['transactions']}")
        print(f"  Accounts (total): {r['accounts']}")
        print(f"  Accounts (open): {r['open_accounts']}, (closed): {r['closed_accounts']}")
        print(f"  Commodities: {r['commodities']}")
        print(f"  Unique payees: {r['unique_payees']}")
        if r["top_payees"]:
            print(f"  Top payees: {r['top_payees'][:5]}")
        print(f"  Tags: {r['tags_count']} unique, top: {r['top_tags']}")
        print(f"  Links: {r['links_count']} unique")
        print(f"  Notes: {r['notes']}, Documents: {r['documents']}")
        print(f"  Has balance assertions: {r['has_balance_assertions']}")
        print(f"  Has price entries: {r['has_prices']}")
        print(f"  Recurring candidates (monthly): {r['recurring_candidates'][:5]}")
        if r["meta_keys"]:
            print(f"  Metadata keys on transactions: {dict(r['meta_keys'])}")

    # Summary table
    print("\n" + "="*80)
    print("SUMMARY TABLE")
    print("="*80)
    print(f"{'Ledger':<35} {'Txns':>6} {'Accts':>6} {'Payees':>7} {'Currencies':<25} {'Date Range'}  {'Errors'}")
    print("-"*110)
    for r in sorted(results, key=lambda x: x.get("transactions", 0), reverse=True):
        if r.get("error"):
            print(f"{r['label']:<35} {'ERROR':>6}")
            continue
        dr = f"{r['date_range'][0]} → {r['date_range'][1]}" if r['date_range'][0] else "N/A"
        cur = ",".join(r['currencies'][:5])
        print(f"{r['label']:<35} {r['transactions']:>6} {r['accounts']:>6} {r['unique_payees']:>7} {cur:<25} {dr}  {r['errors']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
