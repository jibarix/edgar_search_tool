"""Reconcile EDGAR-derived metrics against a CapIQ *Company Screening
Report* (the bottom-up-beta workbook).

This workbook is a different shape from the 11-sheet comparables files
the other reconcile scripts consume: sheets are
['Screening', 'Aggregates', 'Screen Criteria'], with one row per company
on 'Screening', a dedicated `Exchange:Ticker` column, and raw $USDmm LTM
fundamentals plus a 5Y β / R². The 'Aggregates' sheet carries a
"Market Cap. Weighted Avg." β — the bottom-up-beta target for the
Health Care Services screen.

Three tests are emitted:

1. Per-ticker fundamentals: EDGAR LTM vs CapIQ ($USDmm), Δ%.
2. Per-ticker risk: EDGAR 5Y monthly β / R² vs CapIQ.
3. Bottom-up β:
   a. Replicate CapIQ's market-cap-weighted-average β over every
      screened name from the sheet's own β + market-cap columns
      (pure CapIQ inputs — validates our weighting math against the
      Aggregates 0.788).
   b. Bottom-up β from EDGAR: unlever each resolvable US peer's
      EDGAR β with EDGAR total debt, CapIQ equity (market cap) and
      EDGAR effective tax, then report the median unlevered β.

Only Nasdaq/NYSE/OTC* listings are pushed through EDGAR; TSX/TSXV/CNSX
(Canadian-only) rows are kept for the CapIQ-side aggregate but skipped
for the EDGAR pull since they do not file with the SEC.
"""
from __future__ import annotations

import io
import os
import statistics
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import argparse

from edgar.company_lookup import format_cik, search_company
from edgar.filing_retrieval import FilingRetrieval
from edgar.xbrl_parser import XBRLParser
from edgar import metrics as edgar_metrics
from edgar.metrics.ltm import build_ltm_statement
from edgar.metrics.beta import compute_peer_betas
from _capiq_profiles import (
    get_profile,
    load_capiq_workbook,
    to_float as _to_float,
)

# Exchanges whose tickers are SEC filers worth a Company Facts pull.
# Canadian venues (TSX/TSXV/CNSX/NEO) are CapIQ-side only.
_US_PREFIXES = ("Nasdaq", "NYSE", "BATS", "Cboe", "OTCPK", "OTCQX", "OTCQB")

# Marginal tax rate for unlevering (US federal statutory). CapIQ's
# bottom-up convention uses a marginal, not effective, rate; the
# EDGAR-side variant additionally reports an effective-tax version.
_MARGINAL_TAX = 0.21


def _ticker_of(cell: str) -> tuple[str, str]:
    """'NasdaqGS:ADUS' -> ('NasdaqGS', 'ADUS'). Bare cell -> ('', cell)."""
    s = str(cell).strip()
    if ":" in s:
        exch, tkr = s.split(":", 1)
        return exch.strip(), tkr.strip()
    return "", s


def load_screening(profile):
    """Return (per_ticker, all_rows, capiq_wavg_beta).

    per_ticker: {ticker -> {...}} for US-exchange names (EDGAR-eligible).
    all_rows:   list of every screened name's {beta, mktcap, ...} for the
                CapIQ-side aggregate replication.
    capiq_wavg_beta: the Aggregates "Market Cap. Weighted Avg." β.
    """
    wb = load_capiq_workbook(profile.capiq_path)

    ws = wb["Screening"]
    rows = list(ws.iter_rows(values_only=True))
    h = next(
        i for i, r in enumerate(rows)
        if r and r[0] and str(r[0]).strip() == "Company Name"
    )
    hdr = [str(c).strip() if c else "" for c in rows[h]]

    def col(substr: str) -> int:
        for i, c in enumerate(hdr):
            if c.startswith(substr):
                return i
        raise KeyError(f"no column starting {substr!r} in {hdr}")

    c_name = 0
    c_tkr = col("Exchange:Ticker")
    c_beta = col("5 Year Beta [Latest]")
    c_r2 = col("5 Year Beta R-Squared")
    c_mc = col("Market Capitalization")
    c_debt = col("Total Debt")
    c_cash = col("Cash And Equivalents")
    c_rev = col("Total Revenue [LTM]")
    c_int = col("Interest Expense [LTM]")
    c_gp = col("Gross Profit [LTM]")
    c_ebit = col("EBIT [LTM]")
    c_ebitda = col("EBITDA [LTM]")
    c_ni = col("Net Income [LTM]")
    c_da = col("Depreciation & Amort")

    per: dict[str, dict] = {}
    allrows: list[dict] = []
    for r in rows[h + 1:]:
        if not r[c_name]:
            continue
        exch, tkr = _ticker_of(r[c_tkr])
        rec = {
            "name": str(r[c_name]).strip(),
            "exch": exch,
            "ticker": tkr,
            "beta": _to_float(r[c_beta]),
            "r2": _to_float(r[c_r2]),
            "mktcap": _to_float(r[c_mc]),
            "total_debt": _to_float(r[c_debt]),
            "cash": _to_float(r[c_cash]),
            "revenue": _to_float(r[c_rev]),
            # CapIQ Screening signs interest expense negative (it's an
            # expense line); EDGAR's interest_exp_margin yields a positive
            # magnitude. Normalise to magnitude so Δ% is meaningful.
            "interest_expense": (
                abs(_to_float(r[c_int]))
                if _to_float(r[c_int]) is not None else None
            ),
            "gross_profit": _to_float(r[c_gp]),
            "ebit": _to_float(r[c_ebit]),
            "ebitda": _to_float(r[c_ebitda]),
            "ni": _to_float(r[c_ni]),
            "da": _to_float(r[c_da]),
        }
        allrows.append(rec)
        if exch.startswith(_US_PREFIXES) and tkr not in per:
            per[tkr] = rec

    ag = list(wb["Aggregates"].iter_rows(values_only=True))
    ah = next(
        i for i, r in enumerate(ag)
        if r and r[0] and str(r[0]).strip() == ""
        and any(c and "5 Year Beta [Latest]" in str(c) for c in r)
    )
    a_hdr = [str(c).strip() if c else "" for c in ag[ah]]
    a_beta = next(
        i for i, c in enumerate(a_hdr) if c.startswith("5 Year Beta [Latest]")
    )
    wavg = None
    for r in ag[ah + 1:]:
        if r and r[0] and str(r[0]).strip() == "Market Cap. Weighted Avg.":
            wavg = _to_float(r[a_beta])
            break
    return per, allrows, wavg


def _pick_annual_period(stmt, as_of: str) -> str | None:
    """Annual period whose fiscal year matches `as_of`, else the latest.

    The shared reconcile path takes the most-recent 10-K (periods[0]).
    For a year-end-vintage screen (CapIQ "[LTM]" anchored at as_of's
    fiscal year) that compares EDGAR FY+1 against CapIQ FY — a one-year
    period mismatch. Selecting the FY-aligned period makes the
    fundamentals comparison apples-to-apples. This is screening-script
    local on purpose: the dealer/mall reconcile scripts intentionally
    want the latest filing and must not regress.
    """
    if not stmt.periods:
        return None
    yr = as_of[:4]
    for p in stmt.periods:
        if p[:4] == yr:
            return p
    return stmt.periods[0]


def compute_edgar(ticker: str, filings: FilingRetrieval,
                  parser: XBRLParser, profile) -> dict | None:
    """EDGAR LTM fundamentals ($, raw) for one ticker, or None."""
    matches = search_company(ticker)
    if not matches:
        return None
    cik = format_cik(matches[0]["cik"])
    facts = filings.get_company_facts(cik)
    if not facts:
        return None

    as_of = profile.as_of
    overrides = profile.chain_overrides

    annual = parser.parse_company_facts(
        facts, statement_type="ALL", period_type="annual", num_periods=4
    )
    a_periods = annual.get("periods", [])
    if not a_periods:
        return None

    if a_periods[0] != as_of and a_periods[0][5:] != "12-31":
        qtr = parser.parse_company_facts(
            facts, statement_type="ALL", period_type="quarterly",
            num_periods=12,
        )
        ltm = build_ltm_statement(annual, qtr, as_of, overrides)
        if ltm is not None:
            stmt, latest = ltm
            ptype = "ltm"
        else:
            stmt = edgar_metrics.NormalizedStatement(annual, overrides)
            latest = _pick_annual_period(stmt, as_of)
            ptype = "annual"
    else:
        stmt = edgar_metrics.NormalizedStatement(annual, overrides)
        latest = _pick_annual_period(stmt, as_of)
        ptype = "annual"

    if latest is None:
        return None

    def m(slug: str) -> float | None:
        spec = edgar_metrics.REGISTRY.get(slug)
        return spec.fn(stmt).get(latest) if spec else None

    rev = m("revenue")

    def from_margin(slug: str) -> float | None:
        mg = m(slug)
        return mg * rev if mg is not None and rev is not None else None

    return {
        "period": latest,
        "ptype": ptype,
        "revenue": rev,
        "gross_profit": m("gross_profit"),
        "ebit": m("ebit"),
        "ebitda": m("ebitda"),
        "ni": m("ni"),
        "interest_expense": from_margin("interest_exp_margin"),
        "da": from_margin("da_margin"),
        "cash": m("cash_and_st_investments"),
        # CapIQ "Total Debt [Latest Annual]" does not map to a single
        # EDGAR debt basis across names: some reconcile to plain
        # `total_debt` (ADUS), some to `total_debt_incl_leases` (AIRS),
        # some to neither (AMN). Keep the predictable plain basis here;
        # the debt column is a known per-name residual, and
        # `total_debt_incl_leases` additionally mis-scrapes for some
        # filers (AONC: 16,265 vs CapIQ 133) — tracked separately.
        "total_debt": m("total_debt"),
        "tax_rate": m("tax_rate_effective"),
    }


def fmt_m(v):
    return "      -  " if v is None else f"{v / 1e6:9.1f}"


def fmt_delta(e, c):
    """e is raw $; c is CapIQ $USDmm. Δ% against CapIQ."""
    if e is None or c is None or c == 0:
        return "    -  "
    pct = (e / 1e6 - c) / abs(c) * 100
    return f"{pct:+7.1f}%"


def unlever(beta, debt, equity, tax):
    if beta is None or equity in (None, 0) or debt is None:
        return None
    return beta / (1.0 + (1.0 - tax) * (debt / equity))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default=None,
                    help="override the screening profile's LTM/β anchor")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap EDGAR pulls (smoke test); CapIQ aggregate "
                         "still spans the full sheet")
    args, _ = ap.parse_known_args()

    profile = get_profile("screening_hc")
    if args.as_of:
        profile = profile.__class__(
            name=profile.name, capiq_path=profile.capiq_path,
            as_of=args.as_of, tickers=profile.tickers,
            extension_rules=profile.extension_rules,
            chain_overrides=profile.chain_overrides,
        )

    print(f"[{profile.name}] {profile.capiq_path.name} "
          f"(anchor {profile.as_of})")
    per, allrows, capiq_wavg = load_screening(profile)
    print(f"Screened names: {len(allrows)}  |  "
          f"US-exchange (EDGAR-eligible): {len(per)}")

    # ── Test 3a: CapIQ-input market-cap-weighted-avg β replication ────
    num = den = 0.0
    used = 0
    for r in allrows:
        b, mc = r["beta"], r["mktcap"]
        if b is None or mc in (None, 0):
            continue
        num += b * mc
        den += mc
        used += 1
    repl = num / den if den else None
    print("\n=== Bottom-up β · CapIQ-input replication ===")
    print(f"  Σ(β·MktCap)/Σ(MktCap) over {used} names with β+MC : "
          f"{repl:.3f}" if repl is not None else "  (no data)")
    if capiq_wavg is not None:
        print(f"  CapIQ Aggregates 'Market Cap. Weighted Avg.' β  : "
              f"{capiq_wavg:.3f}")
        if repl is not None:
            print(f"  Δ                                               : "
                  f"{repl - capiq_wavg:+.4f}")

    filings = FilingRetrieval()
    parser = XBRLParser()

    targets = sorted(per)
    if args.limit:
        targets = targets[:args.limit]

    print(f"\n=== Per-ticker fundamentals (EDGAR vs CapIQ, $USDmm) ===")
    edgar_rows: dict[str, dict] = {}
    fund_keys = [
        ("revenue", "Revenue"), ("gross_profit", "Gross Profit"),
        ("ebit", "EBIT"), ("ebitda", "EBITDA"), ("ni", "Net Income"),
        ("interest_expense", "Interest Exp"), ("da", "D&A"),
        ("cash", "Cash"), ("total_debt", "Total Debt"),
    ]
    for tkr in targets:
        cap = per[tkr]
        e = compute_edgar(tkr, filings, parser, profile)
        if e is None:
            print(f"\n{tkr:<7}{cap['name'][:40]:<42} no EDGAR data")
            continue
        edgar_rows[tkr] = e
        print(f"\n{tkr:<7}{cap['name'][:40]:<42} "
              f"period {e['period']} [{e['ptype']}]")
        print(f"  {'Metric':<14}{'EDGAR':>11}{'CapIQ':>11}{'Δ%':>9}")
        for k, lbl in fund_keys:
            print(f"  {lbl:<14}{fmt_m(e[k]):>11}{fmt_m(_mm(cap[k])):>11}"
                  f"{fmt_delta(e[k], cap[k]):>9}")

    # ── Test 2: β / R² reconcile ──────────────────────────────────────
    print(f"\n=== 5Y β / R² (EDGAR vs CapIQ) ===")
    print(f"  {'Ticker':<7}{'β EDGAR':>9}{'β CapIQ':>9}{'Δβ':>8}"
          f"{'R² EDGAR':>10}{'R² CapIQ':>10}{'ΔR²':>8}  N")
    beta_results = {r.ticker: r for r in
                    compute_peer_betas(targets, profile.as_of)}
    edgar_betas: dict[str, float] = {}
    for tkr in targets:
        r = beta_results.get(tkr)
        cap = per[tkr]
        cb, cr = cap["beta"], cap["r2"]
        if r is None or r.beta is None:
            print(f"  {tkr:<7}  -- insufficient obs")
            continue
        edgar_betas[tkr] = r.beta
        db = r.beta - cb if cb is not None else None
        dr = r.r_squared - cr if (cr is not None
                                  and r.r_squared is not None) else None
        print(f"  {tkr:<7}{r.beta:>9.3f}"
              f"{(cb if cb is not None else float('nan')):>9.3f}"
              f"{(db if db is not None else float('nan')):>+8.3f}"
              f"{(r.r_squared if r.r_squared is not None else float('nan')):>10.3f}"
              f"{(cr if cr is not None else float('nan')):>10.3f}"
              f"{(dr if dr is not None else float('nan')):>+8.3f}"
              f"  {r.n_obs}")

    # ── Test 3b: EDGAR-side bottom-up β ───────────────────────────────
    print(f"\n=== Bottom-up β · EDGAR β + EDGAR debt + CapIQ equity ===")
    unlev_marg: list[float] = []
    unlev_eff: list[float] = []
    for tkr in targets:
        b = edgar_betas.get(tkr)
        e = edgar_rows.get(tkr)
        cap = per[tkr]
        if b is None or e is None:
            continue
        debt = e["total_debt"] / 1e6 if e["total_debt"] is not None else None
        equity = cap["mktcap"]
        um = unlever(b, debt, equity, _MARGINAL_TAX)
        if um is not None:
            unlev_marg.append(um)
        t = e.get("tax_rate")
        if t is not None and 0.0 <= t <= 0.6:
            ue = unlever(b, debt, equity, t)
            if ue is not None:
                unlev_eff.append(ue)
    if unlev_marg:
        print(f"  peers used                         : {len(unlev_marg)}")
        print(f"  median unlevered β (t={_MARGINAL_TAX:.0%} marginal) : "
              f"{statistics.median(unlev_marg):.3f}")
        print(f"  mean   unlevered β (t={_MARGINAL_TAX:.0%} marginal) : "
              f"{statistics.fmean(unlev_marg):.3f}")
    if unlev_eff:
        print(f"  median unlevered β (effective tax) : "
              f"{statistics.median(unlev_eff):.3f}  "
              f"(n={len(unlev_eff)})")
    if not unlev_marg:
        print("  (no resolvable peers with β + debt + equity)")


def _mm(v):
    """CapIQ value is already $USDmm; lift to raw $ for fmt_m()."""
    return v * 1e6 if v is not None else None


if __name__ == "__main__":
    main()
