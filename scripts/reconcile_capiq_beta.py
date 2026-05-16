"""Reconcile the EDGAR-side 5Y monthly β + R² against Capital IQ.

For each of the 8 US dealers, computes β and R² from Yahoo monthly
adjusted-close vs ^GSPC over the 60-month window ending at AS_OF, then
reads CapIQ's "5 Year Beta" (Operating Statistics col 12) and "5 Year
Beta R-Squared" (Valuation col 8) and prints side-by-side deltas.

Acceptance criteria (per docs/beta_module_scope.md):
- |Δβ| ≤ 0.05 and |ΔR²| ≤ 0.03 for ≥ 6 of 8 dealers (PASS band)
- Hard ceiling: no peer |Δβ| > 0.15 or |ΔR²| > 0.10 (BUG)

Expected residual sources (won't be zero):
- log vs simple returns
- month-end vs first-of-month date convention differences
- CapIQ's exact 5Y window definition (likely 60 months back from
  workbook quarter-end vs our as_of)
"""
from __future__ import annotations

import io
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from edgar.metrics.beta import compute_peer_betas
from _capiq_profiles import (
    TICKER_RE,
    load_capiq_workbook,
    select_profile,
    to_float as _to_float,
)

# Tolerance bands from the scope doc.
PASS_BETA = 0.05
PASS_R2 = 0.03
HARD_BETA = 0.15
HARD_R2 = 0.10


def load_capiq_beta(profile) -> dict[str, dict]:
    """Load CapIQ {ticker -> {'beta': x, 'r2': y}} for the US dealers.

    β lives on Operating Statistics (col labeled "5 Year Beta").
    R² lives on Valuation (col labeled "5 Year Beta R-Squared").
    Same workbook, different sheets — both rows keyed by the same
    `Name (Exchange:Ticker)` cell pattern.
    """
    wb = load_capiq_workbook(profile.capiq_path)

    def _load(sheet: str, col_label: str) -> dict[str, float]:
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        h = next(
            i for i, r in enumerate(rows)
            if r and r[0] and str(r[0]).strip() == "Company Name"
        )
        hdr = [str(c).strip() if c else "" for c in rows[h]]
        col_idx = hdr.index(col_label)
        out: dict[str, float] = {}
        for r in rows[h + 1:]:
            cell = r[0]
            if not cell:
                continue
            m = TICKER_RE.search(str(cell))
            if not m:
                continue
            ticker = m.group(2).strip()
            v = _to_float(r[col_idx])
            if v is not None:
                out[ticker] = v
        return out

    betas = _load("Operating Statistics", "5 Year Beta")
    r2s = _load("Valuation", "5 Year Beta R-Squared")
    keys = set(betas) | set(r2s)
    return {t: {"beta": betas.get(t), "r2": r2s.get(t)} for t in keys}


def fmt_f(v, width=7, prec=3):
    if v is None:
        return "  -  ".ljust(width)
    return f"{v:>{width}.{prec}f}"


def fmt_signed(v, width=8, prec=3):
    if v is None:
        return "  -  ".ljust(width)
    return f"{v:>+{width}.{prec}f}"


def status_marker(d_beta, d_r2):
    """Bucket the row into PASS / WIDE / BUG based on tolerance bands."""
    if d_beta is None or d_r2 is None:
        return "n/a "
    ab, ar = abs(d_beta), abs(d_r2)
    if ab > HARD_BETA or ar > HARD_R2:
        return "BUG "
    if ab > PASS_BETA or ar > PASS_R2:
        return "WIDE"
    return "PASS"


def main():
    profile = select_profile(__doc__)
    print(f"[{profile.name}] Loading CapIQ beta + R-squared "
          f"({profile.capiq_path.name}) ...")
    capiq = load_capiq_beta(profile)
    print(f"Computing EDGAR-side β + R² for {len(profile.tickers)} names "
          f"(window ending {profile.as_of}) ...\n")

    peers = [t for t, _ in profile.tickers]
    results = compute_peer_betas(peers, profile.as_of)
    by_ticker = {r.ticker: r for r in results}

    header = (
        f"{'Ticker':<8}{'Name':<28}"
        f"{'β EDGAR':>10}{'β CapIQ':>10}{'Δβ':>10}"
        f"{'R² EDGAR':>11}{'R² CapIQ':>11}{'ΔR²':>10}  N    Status"
    )
    print(header)
    print("-" * len(header))

    pass_count = 0
    bug_count = 0
    for ticker, name in profile.tickers:
        r = by_ticker.get(ticker)
        c = capiq.get(ticker, {})
        c_beta, c_r2 = c.get("beta"), c.get("r2")
        if r is None or r.beta is None:
            note = r.period_end if r and r.period_end and r.period_end.startswith("fetch") else "insufficient obs"
            print(f"{ticker:<8}{name[:26]:<28}  -- {note}")
            continue
        d_beta = r.beta - c_beta if c_beta is not None else None
        d_r2 = r.r_squared - c_r2 if c_r2 is not None else None
        status = status_marker(d_beta, d_r2)
        if status == "PASS":
            pass_count += 1
        elif status == "BUG":
            bug_count += 1
        print(
            f"{ticker:<8}{name[:26]:<28}"
            f"{fmt_f(r.beta, 10)}{fmt_f(c_beta, 10)}{fmt_signed(d_beta, 10)}"
            f"{fmt_f(r.r_squared, 11)}{fmt_f(c_r2, 11)}{fmt_signed(d_r2, 10)}"
            f" {r.n_obs:<4} {status}"
        )

    print()
    print(f"Summary: {pass_count}/{len(profile.tickers)} PASS "
          f"(|Δβ|≤{PASS_BETA}, |ΔR²|≤{PASS_R2}); "
          f"{bug_count} BUG (>|{HARD_BETA}|β or >|{HARD_R2}|R²).")
    print(f"Target: ≥ 6 PASS, 0 BUG.")


if __name__ == "__main__":
    main()
