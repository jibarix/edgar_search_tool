"""Reconcile EDGAR-derived metrics against the Capital IQ comparables file
for the 8 US-domiciled dealer groups.

For each US dealer in the Capital IQ comp set, pull annual XBRL data, compute
the metrics shown on Capital IQ's "Operating Statistics" tab, and print a
side-by-side delta. Capital IQ uses "LTM" labels but the values reconcile to
the latest filed 10-K for calendar-year filers as of 2025-12-31.

Metrics compared:
    Gross Margin           ->  gross_profit_margin
    EBITDA Margin          ->  ebitda_margin
    EBIT Margin            ->  ebit_margin
    Net Income Margin      ->  ni_margin
    Revenue Growth (1Y)    ->  revenue_growth
    EBITDA Growth (1Y)     ->  ebitda_growth
    EBIT Growth (1Y)       ->  ebit_growth
    Net Income Growth (1Y) ->  ni_growth
    Revenue 5Y CAGR        ->  revenue_cagr_5y  (from Financial Data sheet)
    Debt/Capital           ->  debt_to_capital
    Debt/EBITDA            ->  (computed inline: total_debt / ebitda)
"""
from __future__ import annotations

import re

from edgar.company_lookup import format_cik, search_company
from edgar.filing_retrieval import FilingRetrieval
from edgar.xbrl_parser import XBRLParser
from edgar import metrics as edgar_metrics
from edgar.metrics.ltm import build_ltm_statement
from _capiq_profiles import (
    load_capiq_workbook,
    select_profile,
    to_float as _to_float,
)


def load_capiq_rows(profile) -> dict[str, dict]:
    """Load Capital IQ values keyed by ticker for the comp set."""
    wb = load_capiq_workbook(profile.capiq_path)

    # Operating Statistics: company in col A, metrics start col B (row 13 header)
    os_ws = wb["Operating Statistics"]
    os_rows = list(os_ws.iter_rows(values_only=True))
    # Header row varies — find the row that starts with "Company Name"
    header_idx = next(
        i for i, r in enumerate(os_rows)
        if r and r[0] and str(r[0]).strip() == "Company Name"
    )
    os_header = [str(c).strip() if c else "" for c in os_rows[header_idx]]

    def col(name: str) -> int:
        for i, h in enumerate(os_header):
            if h == name:
                return i
        raise KeyError(f"{name!r} not in {os_header}")

    name_re = re.compile(r"\(([^():]+):([^()]+)\)\s*$")
    out: dict[str, dict] = {}
    for r in os_rows[header_idx + 1:]:
        cell = r[0]
        if not cell:
            continue
        m = name_re.search(str(cell))
        if not m:
            continue
        ticker = m.group(2).strip()
        out[ticker] = {
            "name": str(cell).strip(),
            "gross_margin": _to_float(r[col("LTM Gross Margin %")]),
            "ebitda_margin": _to_float(r[col("LTM EBITDA Margin %")]),
            "ebit_margin": _to_float(r[col("LTM EBIT Margin %")]),
            "ni_margin": _to_float(r[col("LTM Net Income Margin %")]),
            "revenue_growth": _to_float(r[col("LTM Total Revenues, 1 Yr Growth %")]),
            "ebitda_growth": _to_float(r[col("LTM EBITDA, 1 Yr Growth %")]),
            "ebit_growth": _to_float(r[col("LTM EBIT, 1 Yr Growth %")]),
            "ni_growth": _to_float(r[col("LTM Net Income, 1 Yr Growth %")]),
            "debt_to_capital": _to_float(r[col("LTM Total Debt/Capital %")]),
            "debt_to_ebitda": _to_float(r[col("LTM Total Debt/EBITDA")]),
        }

    # Merge 5Y CAGR from the Financial Data sheet (same workbook).
    fd_ws = wb["Financial Data"]
    fd_rows = list(fd_ws.iter_rows(values_only=True))
    fd_header_idx = next(
        i for i, r in enumerate(fd_rows)
        if r and r[0] and str(r[0]).strip() == "Company Name"
    )
    fd_header = [str(c).strip() if c else "" for c in fd_rows[fd_header_idx]]
    cagr_col = fd_header.index("LTM Total Revenues, 5 Yr CAGR %")
    etr_col = fd_header.index("LTM Effective Tax Rate")
    for r in fd_rows[fd_header_idx + 1:]:
        cell = r[0]
        if not cell:
            continue
        m = name_re.search(str(cell))
        if not m:
            continue
        ticker = m.group(2).strip()
        if ticker in out:
            out[ticker]["revenue_cagr_5y"] = _to_float(r[cagr_col])
            # CapIQ stores ETR as a ratio (0.257 = 25.7%), same
            # convention as the metric layer — no rescale needed.
            out[ticker]["effective_tax_rate"] = _to_float(r[etr_col])
    return out


def compute_edgar(ticker: str, filings: FilingRetrieval,
                  parser: XBRLParser, profile) -> dict | None:
    matches = search_company(ticker)
    if not matches:
        return None
    cik = format_cik(matches[0]["cik"])
    facts = filings.get_company_facts(cik)
    if not facts:
        return None

    as_of = profile.as_of
    overrides = profile.chain_overrides

    # Augment Company Facts API output with the profile's industry
    # extension XBRL (dealer floor plan / non-recourse debt / custom D&A
    # parsed from the latest 10-K + 10-Qs; empty for REITs). Idempotent
    # if filings are already cached.
    if profile.extension_rules:
        recent_10k = filings.get_filing_metadata(cik, filing_type="10-K", limit=1)
        recent_10q = filings.get_filing_metadata(cik, filing_type="10-Q", limit=4)
        parser.augment_with_extensions(
            facts, filings, cik, recent_10k + recent_10q,
            profile.extension_rules,
        )

    annual = parser.parse_company_facts(
        facts, statement_type="ALL", period_type="annual", num_periods=4
    )
    a_periods = annual.get("periods", [])
    # Separate deep pull for 5Y CAGR. We can't simply bump num_periods on
    # `annual` because xbrl_parser drops concepts present in fewer than
    # half the requested periods, which culls one-off items like
    # AssetImpairmentCharges and dealer floor-plan extensions that the
    # CapIQ-aligned EBIT add-back depends on. Revenue is dense across
    # 7+ years for every dealer, so a parallel deep pull is safe.
    annual_deep = parser.parse_company_facts(
        facts, statement_type="ALL", period_type="annual", num_periods=7
    )
    annual_stmt = edgar_metrics.NormalizedStatement(annual_deep, overrides)

    # If the latest annual period is NOT close to as_of (non-Dec filer
    # whose most-recent FY end falls inside the LTM window), roll up LTM.
    period_type = "annual"
    if a_periods and a_periods[0] != as_of and a_periods[0][5:] != "12-31":
        qtr = parser.parse_company_facts(
            facts, statement_type="ALL", period_type="quarterly", num_periods=12
        )
        ltm_result = build_ltm_statement(annual, qtr, as_of, overrides)
        if ltm_result is not None:
            stmt, latest = ltm_result
            period_type = "ltm"
        else:
            stmt = edgar_metrics.NormalizedStatement(annual, overrides)
            latest = stmt.periods[0] if stmt.periods else None
    else:
        stmt = edgar_metrics.NormalizedStatement(annual, overrides)
        latest = stmt.periods[0] if stmt.periods else None

    if latest is None:
        return None

    def m(slug: str) -> float | None:
        spec = edgar_metrics.REGISTRY.get(slug)
        if not spec:
            return None
        return spec.fn(stmt).get(latest)

    total_debt = edgar_metrics.REGISTRY["total_debt"].fn(stmt).get(latest)
    ebitda = edgar_metrics.REGISTRY["ebitda"].fn(stmt).get(latest)
    d2e = total_debt / ebitda if total_debt and ebitda else None

    # 5Y CAGR is always evaluated on the annual statement, anchored at its
    # most recent FY end (which differs from `latest` when LTM rollup is used).
    cagr_5y = None
    if annual_stmt.periods:
        cagr_spec = edgar_metrics.REGISTRY.get("revenue_cagr_5y")
        if cagr_spec:
            cagr_5y = cagr_spec.fn(annual_stmt).get(annual_stmt.periods[0])

    return {
        "cik": cik,
        "period": latest,
        "period_type": period_type,
        "gross_margin": m("gross_profit_margin"),
        "ebitda_margin": m("ebitda_margin"),
        "ebit_margin": m("ebit_margin"),
        "ni_margin": m("ni_margin"),
        "revenue_growth": m("revenue_growth"),
        "ebitda_growth": m("ebitda_growth"),
        "ebit_growth": m("ebit_growth"),
        "ni_growth": m("ni_growth"),
        "revenue_cagr_5y": cagr_5y,
        "debt_to_capital": m("debt_to_capital"),
        "effective_tax_rate": m("tax_rate_effective"),
        "debt_to_ebitda": d2e,
    }


def fmt_pct(v):
    return "  -  " if v is None else f"{v * 100:6.2f}%"


def fmt_x(v):
    return "  -  " if v is None else f"{v:5.2f}x"


def fmt_pp_diff(a, b):
    if a is None or b is None:
        return "  -  "
    return f"{(a - b) * 100:+6.2f}pp"


def fmt_x_diff(a, b):
    if a is None or b is None:
        return "  -  "
    return f"{a - b:+5.2f}x"


def main():
    profile = select_profile(__doc__)
    capiq = load_capiq_rows(profile)

    filings = FilingRetrieval()
    parser = XBRLParser()

    print(f"[{profile.name}] {profile.capiq_path.name} "
          f"(anchor {profile.as_of})")
    print(f"{'Ticker':<8}{'Period':<14}{'Metric':<18}"
          f"{'EDGAR':>10}{'CapIQ':>10}{'Delta':>10}")
    print("-" * 70)

    pct_metrics = [
        ("gross_margin", "Gross Margin"),
        ("ebitda_margin", "EBITDA Margin"),
        ("ebit_margin", "EBIT Margin"),
        ("ni_margin", "NI Margin"),
        ("revenue_growth", "Rev Growth 1Y"),
        ("ebitda_growth", "EBITDA Growth 1Y"),
        ("ebit_growth", "EBIT Growth 1Y"),
        ("ni_growth", "NI Growth 1Y"),
        ("revenue_cagr_5y", "Rev 5Y CAGR"),
        ("debt_to_capital", "Debt/Capital"),
        ("effective_tax_rate", "Eff Tax Rate"),
    ]

    for ticker, label in profile.tickers:
        edgar_row = compute_edgar(ticker, filings, parser, profile)
        capiq_row = capiq.get(ticker)
        if not edgar_row:
            print(f"{ticker}  no EDGAR data")
            continue
        if not capiq_row:
            print(f"{ticker}  no CapIQ row")
            continue
        period = edgar_row["period"]
        ptype = edgar_row["period_type"]
        print(f"\n{ticker} ({label}) — period {period} [{ptype}]")
        for slug, lbl in pct_metrics:
            e = edgar_row[slug]
            c = capiq_row[slug]
            print(f"  {lbl:<22}{fmt_pct(e):>10}{fmt_pct(c):>10}{fmt_pp_diff(e, c):>10}")
        e = edgar_row["debt_to_ebitda"]
        c = capiq_row["debt_to_ebitda"]
        print(f"  {'Debt/EBITDA':<22}{fmt_x(e):>10}{fmt_x(c):>10}{fmt_x_diff(e, c):>10}")


if __name__ == "__main__":
    main()
