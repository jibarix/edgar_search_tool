"""Reconcile the CapIQ CorrelationGrowth + CorrelationOpMargin sheets.

Both sheets are wide-format: one row per company with FY through FY-12
values (13 columns). CorrelationGrowth tracks Total Revenue; the sheet
named CorrelationOpMargin actually carries FY EBIT per column despite
its name.

We pull 13 annual periods per ticker and emit a per-cell diff against
CapIQ's values. Periods are positional (FY = most-recent annual,
FY-1 = one fiscal year earlier, ...); CapIQ does currency conversion
and restatement we don't, so older-year deltas may include translation
noise — focus on recent years for accuracy assessment.
"""
from __future__ import annotations

import sys
import io
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from edgar.company_lookup import format_cik, search_company
from edgar.filing_retrieval import FilingRetrieval
from edgar.xbrl_parser import XBRLParser
from edgar import metrics as edgar_metrics
from edgar.metrics.derived_lines import revenue as revenue_fn, ebit as ebit_fn
from _capiq_profiles import (
    TICKER_RE,
    load_capiq_workbook,
    select_profile,
    to_float as _to_float,
)

NUM_PERIODS = 13


def load_correlation_sheet(profile, sheet: str,
                           base_col_label: str) -> dict[str, list[float | None]]:
    """Load the FY..FY-12 wide series for each ticker on the given sheet.

    `base_col_label` is the column-zero label (e.g. "FY Total Revenue").
    The remaining 12 columns must be sequential FY-N labels.
    """
    wb = load_capiq_workbook(profile.capiq_path)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    header_idx = next(
        i for i, r in enumerate(rows)
        if r and r[0] and str(r[0]).strip() == "Company Name"
    )
    hdr = [str(c).strip() if c else "" for c in rows[header_idx]]
    # Build positional index: FY -> col, FY-1 -> col, ..., FY-12 -> col.
    fy_cols: list[int] = []
    for label_idx in range(13):
        if label_idx == 0:
            target = base_col_label
        else:
            target = base_col_label.replace("FY", f"FY-{label_idx}", 1)
        fy_cols.append(hdr.index(target))

    # The CorrelationGrowth / CorrelationOpMargin sheets store currency
    # values in $millions; rescale to raw dollars so they're comparable
    # to the metric layer's USD output.
    out: dict[str, list[float | None]] = {}
    for r in rows[header_idx + 1:]:
        cell = r[0]
        if not cell:
            continue
        m = TICKER_RE.search(str(cell))
        if not m:
            continue
        ticker = m.group(2).strip()
        out[ticker] = [
            (_to_float(r[c]) * 1e6 if _to_float(r[c]) is not None else None)
            for c in fy_cols
        ]
    return out


def pull_series(ticker: str, filings: FilingRetrieval,
                parser: XBRLParser, profile):
    """Return (revenue, ebit, periods) as 13-element positional lists.

    Pulls two annual statements: a 4-period one to preserve sparse items
    (impairments, dealer floor-plan tags) that drive the CapIQ EBIT
    add-back, plus a 13-period one for the longer history. Per-position
    EBIT prefers the 4-period statement when it covers that period —
    that way the FY column carries the same add-back-adjusted value the
    Operating Statistics reconcile reports.
    """
    matches = search_company(ticker)
    if not matches:
        return None, None, None
    cik = format_cik(matches[0]["cik"])
    facts = filings.get_company_facts(cik)
    if not facts:
        return None, None, None
    if profile.extension_rules:
        recent_10k = filings.get_filing_metadata(cik, filing_type="10-K", limit=1)
        recent_10q = filings.get_filing_metadata(cik, filing_type="10-Q", limit=4)
        parser.augment_with_extensions(
            facts, filings, cik, recent_10k + recent_10q,
            profile.extension_rules,
        )
    overrides = profile.chain_overrides
    annual_short = parser.parse_company_facts(
        facts, statement_type="ALL", period_type="annual", num_periods=4
    )
    annual_long = parser.parse_company_facts(
        facts, statement_type="ALL", period_type="annual", num_periods=NUM_PERIODS
    )
    stmt_short = edgar_metrics.NormalizedStatement(annual_short, overrides)
    stmt_long = edgar_metrics.NormalizedStatement(annual_long, overrides)
    if not stmt_long.periods:
        return None, None, None

    periods = stmt_long.periods[:NUM_PERIODS]
    rev_long = revenue_fn(stmt_long)
    ebit_long = ebit_fn(stmt_long)
    ebit_short = ebit_fn(stmt_short) if stmt_short.periods else {}
    short_periods = set(stmt_short.periods)

    rev_series = [rev_long.get(p) for p in periods]
    ebit_series = [
        ebit_short.get(p) if p in short_periods else ebit_long.get(p)
        for p in periods
    ]
    while len(rev_series) < NUM_PERIODS:
        rev_series.append(None)
        ebit_series.append(None)
    return rev_series, ebit_series, periods


def fmt_m(v):
    """Format USD value as millions."""
    if v is None:
        return "   -  "
    return f"{v / 1e6:7.0f}"


def fmt_pct_delta(edgar_v, capiq_v):
    if edgar_v is None or capiq_v is None or capiq_v == 0:
        return "  -  "
    pct = (edgar_v - capiq_v) / abs(capiq_v) * 100
    return f"{pct:+5.1f}%"


def emit_section(label: str, edgar_series, capiq_series, periods):
    print(f"\n  {label}")
    print(f"    {'Col':<5}{'Period':<12}{'EDGAR ($M)':>12}"
          f"{'CapIQ ($M)':>12}{'Δ%':>8}")
    for i in range(NUM_PERIODS):
        col = "FY" if i == 0 else f"FY-{i}"
        period = periods[i] if periods and i < len(periods) else "    -    "
        e = edgar_series[i] if i < len(edgar_series) else None
        c = capiq_series[i] if i < len(capiq_series) else None
        print(f"    {col:<5}{period:<12}{fmt_m(e):>12}{fmt_m(c):>12}"
              f"{fmt_pct_delta(e, c):>8}")


def main():
    profile = select_profile(__doc__)
    print(f"[{profile.name}] Loading CapIQ correlation sheets "
          f"({profile.capiq_path.name})...")
    capiq_rev = load_correlation_sheet(
        profile, "CorrelationGrowth", "FY Total Revenue")
    capiq_ebit = load_correlation_sheet(
        profile, "CorrelationOpMargin", "FY EBIT")

    filings = FilingRetrieval()
    parser = XBRLParser()

    for ticker, label in profile.tickers:
        rev, ebt, periods = pull_series(ticker, filings, parser, profile)
        if rev is None:
            print(f"\n=== {ticker}  no EDGAR data ===")
            continue
        c_rev = capiq_rev.get(ticker)
        c_ebit = capiq_ebit.get(ticker)
        if c_rev is None and c_ebit is None:
            print(f"\n=== {ticker} ({label})  no CapIQ correlation rows ===")
            continue

        print(f"\n=== {ticker} ({label})  latest FY = {periods[0]} ===")
        if c_rev is not None:
            emit_section("Revenue", rev, c_rev, periods)
        if c_ebit is not None:
            emit_section("EBIT", ebt, c_ebit, periods)


if __name__ == "__main__":
    main()
