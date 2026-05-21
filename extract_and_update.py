#!/usr/bin/env python3
"""
Run this from Stock_Signals/ root:
  python3 extract_and_update.py

Reads backend/upstox/NSE_instruments.csv
Extracts all NSE equity symbols
Updates NIFTY_500_SYMBOLS in instruments.py with ALL_NSE_SYMBOLS
"""

import csv
import re
import os

CSV_PATH = "backend/upstox/NSE_instruments.csv"
INSTRUMENTS_PY = "backend/upstox/instruments.py"

EQUITY_RE = re.compile(r'^[A-Z][A-Z&-]{1,19}$')

def extract_symbols(csv_path):
    symbols = set()
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items() if k}
            instrument_key = row.get("instrument_key", "")
            symbol = row.get("tradingsymbol", "").upper().strip()
            lot_size = row.get("lot_size", "1")

            if not instrument_key.startswith("NSE_EQ"):
                continue
            try:
                if int(lot_size) != 1:
                    continue
            except:
                pass
            if not symbol or not EQUITY_RE.match(symbol):
                continue

            symbols.add(symbol)
    return sorted(symbols)

def update_instruments_py(symbols, instruments_path):
    with open(instruments_path, "r") as f:
        content = f.read()

    # Build new ALL_NSE_SYMBOLS set string
    lines = ["ALL_NSE_SYMBOLS: set = {"]
    row = []
    for i, sym in enumerate(symbols):
        row.append(f'"{sym}"')
        if len(row) == 8:
            lines.append("    " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("    " + ", ".join(row) + ",")
    lines.append("}")
    all_nse_block = "\n".join(lines)

    # Replace NIFTY_500_SYMBOLS usage in get_nifty500
    # Add ALL_NSE_SYMBOLS before NIFTY_200_SYMBOLS
    insert_marker = "NIFTY_200_SYMBOLS: set = {"

    if "ALL_NSE_SYMBOLS" not in content:
        content = content.replace(
            insert_marker,
            all_nse_block + "\n\n" + insert_marker
        )

    # Update get_nifty500_instrument_keys to use ALL_NSE_SYMBOLS
    content = content.replace(
        "result = await get_instrument_keys_bulk(list(NIFTY_500_SYMBOLS))",
        "result = await get_instrument_keys_bulk(list(ALL_NSE_SYMBOLS))"
    )

    # Update scanner to use all symbols
    content = content.replace(
        'NIFTY_500_SYMBOLS',
        'ALL_NSE_SYMBOLS'
    ).replace(
        'NIFTY_200_SYMBOLS',
        'ALL_NSE_SYMBOLS'
    )

    with open(instruments_path, "w") as f:
        f.write(content)

    return len(symbols)

if __name__ == "__main__":
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: {CSV_PATH} not found!")
        print("Run from Stock_Signals/ root directory")
        exit(1)

    print(f"Reading {CSV_PATH}...")
    symbols = extract_symbols(CSV_PATH)
    print(f"Found {len(symbols)} NSE equity symbols")

    print(f"Updating {INSTRUMENTS_PY}...")
    count = update_instruments_py(symbols, INSTRUMENTS_PY)
    print(f"Done! {count} symbols added to ALL_NSE_SYMBOLS")
    print("\nNext steps:")
    print("  git add backend/upstox/instruments.py")
    print("  git commit -m 'add all NSE equity symbols to scanner'")
    print("  git push")
    print("\nAfter deploy, Scan Now will scan ALL NSE equities!")