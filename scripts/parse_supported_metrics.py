"""One-off parser for the Google Sheets HTML export in data/Supported Metrics.zip.

Reads each sheet, extracts header + row data, prints a structured summary.
"""

import json
import sys
from pathlib import Path
from bs4 import BeautifulSoup

EXTRACT_DIR = Path(__file__).resolve().parent.parent / "data" / "_supported_metrics_extract"
OUT_DIR = EXTRACT_DIR
SHEETS = ["Metrics.html", "Sheet1.html", "Metrics - OLD.html"]


def parse_sheet(path: Path) -> dict:
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return {"path": str(path), "error": "no <table> found"}

    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells:
            rows.append(cells)

    if not rows:
        return {"path": str(path), "error": "no data rows"}

    header = rows[0]
    body = rows[1:]
    return {
        "path": path.name,
        "columns": header,
        "row_count": len(body),
        "first_5_rows": body[:5],
        "last_5_rows": body[-5:] if len(body) > 5 else [],
        "all_rows": body,
    }


def main():
    results = []
    for name in SHEETS:
        p = EXTRACT_DIR / name
        if not p.exists():
            print(f"missing: {p}", file=sys.stderr)
            continue
        res = parse_sheet(p)
        results.append(res)

        print(f"\n=== {res['path']} ===")
        if "error" in res:
            print(f"ERROR: {res['error']}")
            continue
        print(f"columns: {res['columns']}")
        print(f"rows: {res['row_count']}")
        print("first 5:")
        for r in res["first_5_rows"]:
            print(f"  {r}")

    # Dump full parse to JSON for downstream comparison
    out_json = OUT_DIR / "parsed_metrics.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote full parse to {out_json}")


if __name__ == "__main__":
    main()
