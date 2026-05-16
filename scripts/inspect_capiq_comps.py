"""Inspect the Capital IQ comparables_dealerships_20251231.xls file.

Capital IQ exports "xls" as HTML internally — parse with BeautifulSoup.
"""
from pathlib import Path
from bs4 import BeautifulSoup

p = Path(__file__).resolve().parent.parent / "data" / "comparables_dealerships_20251231.xls"
print(f"File: {p}  size: {p.stat().st_size}")

# Detect encoding — Capital IQ uses windows-1252 or utf-8 typically
raw = p.read_bytes()
sniff = raw[:200]
print(f"First bytes: {sniff[:100]!r}")
print()

# Try multiple encodings
for enc in ("utf-8", "windows-1252", "latin-1"):
    try:
        text = raw.decode(enc)
        print(f"Decoded as {enc}")
        break
    except UnicodeDecodeError:
        continue

soup = BeautifulSoup(text, "html.parser")
tables = soup.find_all("table")
print(f"Found {len(tables)} tables")

for ti, table in enumerate(tables[:3]):
    rows = table.find_all("tr")
    print(f"\n=== Table {ti}: {len(rows)} rows ===")
    for ri, tr in enumerate(rows[:30]):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            preview = [c[:60] for c in cells]
            print(f"  row {ri}: {preview}")
