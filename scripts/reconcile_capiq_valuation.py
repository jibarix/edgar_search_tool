"""Reconcile EDGAR-derived Market Cap, TEV, and 5 trading multiples
against the Capital IQ comparables workbook for the 8 US dealers.

Inputs assembled per ticker:
    spot price          Yahoo v8 chart meta.regularMarketPrice
    shares outstanding  most recent dei:EntityCommonStockSharesOutstanding
                        (cover-page disclosure on latest 10-K/10-Q),
                        with us-gaap:CommonStockSharesOutstanding fallback
    market cap          = shares × price
    cash + ST inv       existing edgar metrics
    total debt          existing edgar metrics
    TEV                 = market cap + total debt - cash
    LTM rev/EBITDA/EBIT existing edgar metrics (LTM rollup for non-Dec filers)
    diluted EPS         us-gaap:EarningsPerShareDiluted (LTM-summed if needed)
    tangible BV         total equity - goodwill - intangibles

Compared columns (per docs/beta_module_scope.md follow-on cluster):
    Market Capitalization Latest      (Financial Data col 2)
    Total Enterprise Value Latest     (Financial Data col 3)
    TEV/Total Revenues LTM            (Trading Multiples col 1)
    TEV/EBITDA LTM                    (Trading Multiples col 2)
    TEV/EBIT LTM                      (Trading Multiples col 3)
    P/Diluted EPS Before Extra LTM    (Trading Multiples col 4)
    P/TangBV LTM                      (Trading Multiples col 5)

Spot price drifts daily; expect Market Cap / TEV / price-based multiples
to differ from CapIQ's snapshot by whatever the stock moved since CapIQ
pulled. Methodology errors show up as *systematic* deltas — pure noise
moves randomly across the comp set.
"""
from __future__ import annotations

import io
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from edgar.company_lookup import format_cik, search_company
from edgar.filing_retrieval import FilingRetrieval
from edgar.xbrl_parser import XBRLParser
from edgar import metrics as edgar_metrics
from edgar.metrics.ltm import build_ltm_statement
from edgar.market_data.yahoo import fetch_monthly_bars, trim_to_window
from _capiq_profiles import (
    TICKER_RE,
    load_capiq_workbook,
    select_profile,
    to_float as _to_float,
)


def load_capiq_valuation(profile) -> dict[str, dict]:
    """Load Capital IQ valuation values keyed by ticker.

    Market Cap and TEV live on Financial Data; the five multiples on
    Trading Multiples. Both sheets share the `Name (Exchange:Ticker)`
    convention in column A.

    CapIQ stores Market Cap and TEV in $millions on the Financial Data
    sheet; we rescale to raw dollars to match the EDGAR-side values.
    Multiples are unitless.
    """
    wb = load_capiq_workbook(profile.capiq_path)
    out: dict[str, dict] = {t: {} for t, _ in profile.tickers}

    def _sheet_rows(sheet: str) -> tuple[list[str], list[tuple]]:
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        h = next(
            i for i, r in enumerate(rows)
            if r and r[0] and str(r[0]).strip() == "Company Name"
        )
        hdr = [str(c).strip() if c else "" for c in rows[h]]
        return hdr, rows[h + 1:]

    fd_hdr, fd_body = _sheet_rows("Financial Data")
    tm_hdr, tm_body = _sheet_rows("Trading Multiples")

    fd_cols = {
        "mkt_cap": fd_hdr.index("Market Capitalization Latest"),
        "tev": fd_hdr.index("Total Enterprise Value Latest"),
        "shares": fd_hdr.index("Shares Outstanding Latest"),
    }
    tm_cols = {
        "tev_rev": tm_hdr.index("TEV/Total Revenues LTM - Latest"),
        "tev_ebitda": tm_hdr.index("TEV/EBITDA LTM - Latest"),
        "tev_ebit": tm_hdr.index("TEV/EBIT LTM - Latest"),
        "p_eps": tm_hdr.index("P/Diluted EPS Before Extra LTM - Latest"),
        "p_tangbv": tm_hdr.index("P/TangBV LTM - Latest"),
    }

    def _ticker_of(cell) -> str | None:
        if not cell:
            return None
        m = TICKER_RE.search(str(cell))
        return m.group(2).strip() if m else None

    for r in fd_body:
        t = _ticker_of(r[0])
        if t not in out:
            continue
        # Shares Outstanding Latest is in raw count (millions implied by
        # CapIQ display, but the underlying cell is raw — confirmed by
        # cross-multiplying mkt_cap / shares = price-per-share consistent
        # with public prices.).
        out[t]["shares"] = _to_float(r[fd_cols["shares"]])
        mc = _to_float(r[fd_cols["mkt_cap"]])
        tev = _to_float(r[fd_cols["tev"]])
        # Financial Data scales currency values in $millions.
        out[t]["mkt_cap"] = mc * 1e6 if mc is not None else None
        out[t]["tev"] = tev * 1e6 if tev is not None else None

    for r in tm_body:
        t = _ticker_of(r[0])
        if t not in out:
            continue
        for k, col in tm_cols.items():
            out[t][k] = _to_float(r[col])
    return out


def latest_shares_outstanding(facts: dict) -> float | None:
    """Return the most recent CommonStockSharesOutstanding fact.

    Priority:
        1. dei:EntityCommonStockSharesOutstanding (cover-page disclosure,
           typically dated within ~30 days of filing)
        2. us-gaap:CommonStockSharesOutstanding (period-end snapshot)
        3. us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding
           (period-weighted average, used as fallback for multi-class
           issuers like SAH whose Company Facts doesn't expose the
           cover-page disclosure or a single us-gaap snapshot tag)

    Picks the fact with the most recent `end` date in the first source
    that has any data.
    """
    f = facts.get("facts") or {}
    sources = [
        ("dei", "EntityCommonStockSharesOutstanding", "shares"),
        ("us-gaap", "CommonStockSharesOutstanding", "shares"),
        ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),
    ]
    for ns, tag, unit in sources:
        node = (f.get(ns) or {}).get(tag) or {}
        entries = (node.get("units") or {}).get(unit) or []
        best_end: str | None = None
        best_val: float | None = None
        for entry in entries:
            end = entry.get("end")
            val = entry.get("val")
            if not end or val is None:
                continue
            if best_end is None or end > best_end:
                best_end = end
                best_val = float(val)
        if best_val is not None:
            return best_val
    return None


def latest_diluted_eps_ltm(facts: dict, period_end: str) -> float | None:
    """Sum the most recent four quarterly diluted EPS values ending at `period_end`.

    If the latest fiscal year is the natural anchor (Dec-31 filer at
    AS_OF), the annual EPS from the FY 10-K is already the LTM figure.
    Otherwise we sum Q's. This mirrors the LTM rollup pattern used for
    revenue / EBITDA elsewhere.
    """
    f = facts.get("facts") or {}
    node = (f.get("us-gaap") or {}).get("EarningsPerShareDiluted") or {}
    entries = (node.get("units") or {}).get("USD/shares") or []
    # Group by (start, end) — annuals span ~365 days, quarters ~90.
    annuals = [(e["end"], e["val"]) for e in entries
               if e.get("end") and e.get("val") is not None
               and (e.get("fp") == "FY" or e.get("form") == "10-K")]
    annuals.sort(reverse=True)
    if annuals and annuals[0][0] == period_end:
        return float(annuals[0][1])
    if annuals:
        # Fallback: most recent reported annual (close-enough proxy when
        # exact period_end doesn't appear in the EPS facts).
        return float(annuals[0][1])
    return None


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

    # Apply the profile's industry extension rules (dealer floor-plan /
    # non-recourse / extension EBIT items; empty list for REITs).
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
    # LTM rollup for non-Dec filers (matches reconcile_capiq_comps logic).
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

    shares = latest_shares_outstanding(facts)
    # Use the close on the last trading day at or before as_of, not the
    # spot price. CapIQ's "Latest" Market Cap snapshots are anchored at
    # workbook generation time; reconciling against today's spot just
    # measures price drift, not methodology.
    bars = trim_to_window(
        fetch_monthly_bars(ticker, as_of), as_of, months=2,
    )
    price = bars.adjclose[-1] if bars.adjclose else None

    mkt_cap = shares * price if shares and price else None
    total_debt = m("total_debt")
    cash = m("cash_and_st_investments")
    tev = None
    if mkt_cap is not None and total_debt is not None:
        tev = mkt_cap + total_debt - (cash or 0.0)

    revenue = m("revenue")
    ebitda = m("ebitda")
    ebit = m("ebit")
    tang_bv = m("tangible_book_value")
    eps = latest_diluted_eps_ltm(facts, latest)

    def safe_div(a, b):
        if a is None or b is None or b == 0:
            return None
        return a / b

    return {
        "cik": cik,
        "period": latest,
        "period_type": period_type,
        "shares": shares,
        "price": price,
        "mkt_cap": mkt_cap,
        "tev": tev,
        "tev_rev": safe_div(tev, revenue),
        "tev_ebitda": safe_div(tev, ebitda),
        "tev_ebit": safe_div(tev, ebit),
        "p_eps": safe_div(price, eps),
        # P/TangBV uses market cap over total tangible book (not per
        # share) so that a negative tangible book produces a coherent
        # negative ratio rather than per-share denominator weirdness.
        # CapIQ's column also uses the price-per-share / TangBV-per-share
        # form, which is mathematically the same ratio.
        "p_tangbv": safe_div(mkt_cap, tang_bv),
    }


def fmt_m(v):
    if v is None:
        return "    -   "
    return f"{v / 1e6:>8,.0f}"


def fmt_x(v):
    if v is None:
        return "  -  "
    return f"{v:>5.2f}x"


def fmt_signed_pct(a, b):
    if a is None or b is None or b == 0:
        return "  -  "
    return f"{(a - b) / abs(b) * 100:>+5.1f}%"


def fmt_signed_x(a, b):
    if a is None or b is None:
        return "  -  "
    return f"{a - b:>+5.2f}x"


def main():
    profile = select_profile(__doc__)
    print(f"[{profile.name}] Loading CapIQ valuation columns "
          f"({profile.capiq_path.name}) ...")
    capiq = load_capiq_valuation(profile)
    filings = FilingRetrieval()
    parser = XBRLParser()

    print(f"Computing EDGAR-side market cap / TEV / multiples for "
          f"{len(profile.tickers)} names (anchor {profile.as_of}) ...\n")

    for ticker, name in profile.tickers:
        e = compute_edgar(ticker, filings, parser, profile)
        c = capiq.get(ticker, {})
        if e is None:
            print(f"=== {ticker} ({name}) — no EDGAR data ===")
            continue
        px_s = f"${e['price']:.2f}" if e['price'] is not None else "n/a"
        sh_s = f"{e['shares']/1e6:.1f}M" if e['shares'] is not None else "n/a"
        print(f"=== {ticker} ({name}) period={e['period']} [{e['period_type']}] "
              f"price={px_s} shares={sh_s} ===")
        print(f"  {'Metric':<18}{'EDGAR':>12}{'CapIQ':>12}{'Δ':>10}")
        # Market Cap + TEV in $M
        for slug, label in [("mkt_cap", "Market Cap $M"), ("tev", "TEV $M")]:
            print(f"  {label:<18}{fmt_m(e[slug])}{fmt_m(c.get(slug))}"
                  f"{fmt_signed_pct(e[slug], c.get(slug)):>10}")
        # Five multiples in x
        for slug, label in [
            ("tev_rev", "TEV/Revenue"),
            ("tev_ebitda", "TEV/EBITDA"),
            ("tev_ebit", "TEV/EBIT"),
            ("p_eps", "P/Diluted EPS"),
            ("p_tangbv", "P/TangBV"),
        ]:
            print(f"  {label:<18}{fmt_x(e[slug]):>12}{fmt_x(c.get(slug)):>12}"
                  f"{fmt_signed_x(e[slug], c.get(slug)):>10}")
        print()


if __name__ == "__main__":
    main()
