#!/usr/bin/env python3
"""Deep analysis of selected fixtures for quality assessment."""

import os, sys
from pathlib import Path
from collections import Counter, defaultdict
from beancount import loader
from beancount.core import data, getters
from beancount.core.data import Transaction, Open, Custom, Commodity

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ledgers"

TARGETS = {
    "beancount-example": FIXTURES_DIR / "beancount-example.beancount",
    "boilerplate-cn": FIXTURES_DIR / "beancount-boilerplate-cn" / "ledger" / "main.beancount",
    "financeiro": FIXTURES_DIR / "financeiro" / "financeiro" / "main.beancount",
    "comptabilite": FIXTURES_DIR / "comptabilite" / "ledger" / "main.beancount",
    "beancounters": FIXTURES_DIR / "beancounters" / "main.beancount",
    "finzytrack-fake": FIXTURES_DIR / "finzytrack" / "backend" / "resources" / "seed_data" / "ledgers" / "fake.beancount",
    "finzytrack-multi": FIXTURES_DIR / "finzytrack" / "backend" / "resources" / "seed_data" / "ledgers" / "fake-multi" / "main.beancount",
    "cfo-usa-company": FIXTURES_DIR / "cfo-stack" / "examples" / "usa-company" / "main.beancount",
    "cfo-canadian-company": FIXTURES_DIR / "cfo-stack" / "examples" / "canadian-company" / "main.beancount",
}


def analyze_deep(label, path):
    print(f"\n{'='*70}")
    print(f"  DEEP ANALYSIS: {label}")
    print(f"{'='*70}")

    if not path.exists():
        print(f"  NOT FOUND: {path}")
        return

    try:
        entries, errors, options = loader.load_file(str(path))
    except Exception as e:
        print(f"  LOAD ERROR: {e}")
        return

    txns = [e for e in entries if isinstance(e, Transaction)]
    opens = [e for e in entries if isinstance(e, Open)]
    customs = [e for e in entries if isinstance(e, Custom)]

    # Account tree
    accounts = getters.get_accounts(entries)
    print(f"\n  ACCOUNTS ({len(accounts)} total)")
    # Show hierarchy
    tree = defaultdict(list)
    for acct in sorted(accounts):
        parts = acct.split(":")
        depth = len(parts)
        tree[depth].append(acct)

    max_depth = max(tree.keys()) if tree else 0
    print(f"  Max depth: {max_depth}")
    print(f"  By depth: {dict((d, len(v)) for d, v in sorted(tree.items()))}")
    print(f"  Root accounts (depth 1): {len(tree.get(1, []))}")
    for i in range(1, min(max_depth + 1, 4)):
        print(f"  Depth {i} samples: {tree.get(i, [])[:5]}")

    # Account metadata (name:, open, close dates)
    opens_with_meta = [o for o in opens if o.meta and any(k not in ('filename', 'lineno') for k in o.meta)]
    if opens_with_meta:
        print(f"\n  ACCOUNT METADATA: {len(opens_with_meta)} accounts have metadata")
        meta_keys = Counter()
        meta_samples = []
        for o in opens_with_meta:
            for k in o.meta:
                if k not in ('filename', 'lineno'):
                    meta_keys[k] += 1
                    if len(meta_samples) < 3 and o.meta.get(k):
                        meta_samples.append((o.account, k, o.meta[k]))
        print(f"  Keys: {dict(meta_keys)}")
        print(f"  Samples: {meta_samples[:5]}")

    # Language detection
    lang_indicators = {
        "pt": ["alimentação", "patrocínio", "reembolso", "ingressos", "evento", "anuidade", "contadora", "jurídico", "impostos"],
        "fr": ["actifs", "passifs", "capital", "revenus", "depenses", "banque", "cheques", "epargne", "assurances", "comptes", "clients", "fournisseurs", "paie", "taxes", "pret", "echeances"],
        "zh": ["食品", "酒水", "交通", "通讯", "医疗", "房租", "工资", "话费", "旅行", "购物", "休闲"],
        "no": ["kafé", "reise", "lønn", "husleie", "dagligvarer", "abonnement", "forsikring"],
    }

    payee_text = " ".join(t.payee.lower() if t.payee else "" for t in txns)
    narration_text = " ".join(t.narration.lower() for t in txns)
    all_text = payee_text + " " + narration_text
    # Also check account names
    account_text = " ".join(a.lower() for a in accounts)

    print(f"\n  LANGUAGE INDICATORS:")
    for lang, words in lang_indicators.items():
        matches = sum(1 for w in words if w in all_text or w in account_text)
        if matches > 0:
            print(f"  {lang}: {matches} keyword matches (e.g. {[w for w in words if w in all_text or w in account_text][:5]})")

    # Custom entries (Fava extensions, etc.)
    if customs:
        custom_types = Counter(c.type for c in customs)
        print(f"\n  CUSTOM ENTRIES ({len(customs)}): {dict(custom_types)}")
        fava_exts = [c for c in customs if c.type == "fava-extension"]
        if fava_exts:
            print(f"  Fava extensions: {[c.values[0].value for c in fava_exts[:10]]}")

    # Commodities detail
    commodities = [e for e in entries if isinstance(e, Commodity)]
    if commodities:
        print(f"\n  COMMODITIES ({len(commodities)}):")
        for c in commodities[:15]:
            meta_str = ", ".join(f"{k}={v}" for k, v in c.meta.items() if k not in ('filename', 'lineno'))
            print(f"    {str(c.date)} {c.currency}" + (f"  ({meta_str})" if meta_str else ""))

    # Metadata schema (all unique keys across all transaction types)
    all_meta_keys = Counter()
    for e in entries:
        if e.meta:
            for k in e.meta:
                if k not in ('filename', 'lineno', '__tolerances__'):
                    all_meta_keys[k] += 1

    if all_meta_keys:
        print(f"\n  METADATA SCHEMA (non-standard keys across all entries):")
        for k, v in all_meta_keys.most_common(20):
            print(f"    {k}: {v} occurrences")

    # Payee analysis
    payees = Counter(t.payee for t in txns if t.payee)
    if payees:
        print(f"\n  PAYEE ANALYSIS:")
        print(f"    Unique payees: {len(payees)}")
        # Distribution
        freq_dist = Counter()
        for count in payees.values():
            if count == 1:
                freq_dist["1 (one-time)"] += 1
            elif count <= 5:
                freq_dist["2-5"] += 1
            elif count <= 20:
                freq_dist["6-20"] += 1
            elif count <= 100:
                freq_dist["21-100"] += 1
            else:
                freq_dist["100+"] += 1
        print(f"    Frequency distribution: {dict(freq_dist)}")
        print(f"    Top 10 payees: {payees.most_common(10)}")
        # Payee name complexity
        lengths = [len(p) for p in payees]
        print(f"    Payee name length: min={min(lengths)}, max={max(lengths)}, avg={sum(lengths)/len(lengths):.1f}")

    # Balance assertion analysis
    balances = [e for e in entries if isinstance(e, data.Balance)]
    if balances:
        print(f"\n  BALANCE ASSERTIONS: {len(balances)}")
        print(f"    Accounts with assertions: {len(set(b.account for b in balances))}")

    # Price analysis
    prices = [e for e in entries if isinstance(e, data.Price)]
    if prices:
        print(f"\n  PRICE ENTRIES: {len(prices)}")
        price_currencies = Counter(p.currency for p in prices)
        print(f"    Currencies: {dict(price_currencies.most_common(5))}")

    # Transaction tag analysis
    tags = Counter()
    for t in txns:
        if t.tags:
            for tag in t.tags:
                tags[tag] += 1
    if tags:
        print(f"\n  TAGS: {dict(tags.most_common(10))}")

    # Transaction link analysis
    links = Counter()
    for t in txns:
        if t.links:
            for link in t.links:
                links[link] += 1
    if links:
        print(f"\n  LINKS: {dict(links.most_common(5))} (total unique: {len(links)})")

    # Note entries
    notes = [e for e in entries if isinstance(e, data.Note)]
    if notes:
        print(f"\n  NOTES: {len(notes)} entries")
        for n in notes[:5]:
            print(f"    {n.date} {n.account}: {n.comment[:80]}")

    # File includes - check the main file for include directives
    main_content = path.read_text(errors='replace')
    include_lines = [l.strip() for l in main_content.split('\n') if l.strip().startswith('include ')]
    if include_lines:
        print(f"\n  INCLUDES in main file: {len(include_lines)}")
        for line in include_lines[:10]:
            print(f"    {line}")


def main():
    for label, path in TARGETS.items():
        analyze_deep(label, path)

    print("\n\n" + "="*70)
    print("QUALITY SUMMARY")
    print("="*70)
    print("""
FIXTURE TIERS:

TIER 1 — Production-grade test fixtures (large, diverse, clean)
  1. finzytrack/fake.beancount    — 5,389 txns, 81 accts, 404 payees, INR+USD, 8yr range, 0 errors
  2. beancount-example.beancount  — 1,146 txns, 60 accts, investments, tags, prices, 0 errors
  3. financeiro                   — 1,741 txns, 137 accts, 197 payees, BRL, Portuguese, 0 errors
  4. beancount-boilerplate-cn     — 34 txns, 58 accts (!!!), 17 commodities, ZH, multi-currency

TIER 2 — Specialized test fixtures (specific features)
  5. comptabilite                 — 77 accts, FR-CA, Fava extensions, rich metadata, 5 doc errors
  6. beancounters                 — 33 txns, 24 accts, NOK, bank+CC structure, 1 glob error
  7. cfo-usa-company              — 34 txns, 24 accts, USD, business, recurring patterns
  8. cfo-canadian-company         — 29 txns, 37 accts, CAD, business, balance assertions

TIER 3 — Smoke-test fixtures (small, quick validation)
  9. cfo-stack/* 4 scenarios      — 9-10 txns each, personal/family, USD/CAD
  10. finzytrack/fake-multi       — 23 txns, 10 accts, multi-file structure

BROKEN (skip):
  - finzytrack/one.beancount      — 68 parse errors (template/syntax issues)
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
