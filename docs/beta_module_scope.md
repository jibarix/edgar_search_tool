# 5Y Monthly Beta + R² Module — Scope

**Status:** Draft for review.
**Purpose:** Replicate CapIQ's per-firm `5 Year Beta` and `5 Year Beta R-Squared` columns for the comparables workbook. Output two numbers per ticker; nothing else.

This is a CapIQ-replication task, scoped alongside the other reconcile scripts (`reconcile_capiq_comps.py`, `reconcile_capiq_correlation.py`). Bottom-up beta chain (unlever → cash-correct → total-beta → relever) is **out of scope** and will be a separate later task.

## 1. Methodology

| Parameter | Choice |
|---|---|
| Return frequency | Monthly |
| Window | 5 years (60 months) ending at `as_of` |
| Index | S&P 500 (`^GSPC`) |
| Returns | Log returns from adjusted close |
| Regression | Single OLS: `r_stock = α + β · r_index + ε`; β and R² from same fit |
| Source | Yahoo v8 chart endpoint via stdlib `urllib.request` |

β and R² come from the same OLS so they're internally consistent (decision validated in prior conversation — CapIQ has this property; Damodaran's published series does not).

## 2. Module API

### Inputs
- `peers: list[str]` — ticker list (caller-supplied, no defaults)
- `as_of: str` — ISO date; window ends here. Default = today.

### Output
```python
@dataclass
class PeerBeta:
    ticker: str
    n_obs: int               # months in regression
    beta: float
    r_squared: float
    std_err_beta: float      # OLS s.e. — costs nothing to expose, useful for diagnostics
    alpha: float             # OLS intercept — same
    period_start: str        # ISO date of first return obs
    period_end: str          # ISO date of last return obs
```

Returned as `list[PeerBeta]` in caller's input order.

## 3. Data Source

**Yahoo v8 chart endpoint**: `https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1mo&range=5y`

- Direct HTTP via stdlib `urllib.request` — no PyPI dependency added (consistent with the active Mini Shai-Hulud supply-chain posture).
- Adjusted close (`adjclose`) handles splits and dividends.
- Local cache at `cache/yahoo/{ticker}_{as_of}.json` mirroring the EDGAR cache pattern. 24-hour TTL.

## 4. File Layout

```
edgar/
  market_data/                    ← NEW: non-EDGAR data lives here
    __init__.py
    yahoo.py                      ← v8 chart endpoint client + cache
  metrics/
    beta.py                       ← 5Y monthly OLS β + R²
scripts/
  reconcile_capiq_beta.py         ← validate against CapIQ Operating Statistics
docs/
  beta_module_scope.md            ← this file
```

## 5. Edge Cases

- **<24 monthly obs**: return `None` for β and R² (matches Damodaran's "less than 2 years → not estimated" threshold).
- **Date alignment**: monthly bars from different tickers may fall on different month-end dates. Reindex to the index's date sequence; drop any month where either side has no observation.
- **Yahoo transient errors**: retry 3× with exponential backoff (2s/4s/8s). Hard failure → raise, don't degrade silently.
- **Near-zero R²**: not a numerical concern for plain β + R² output (the `√R²` blow-up only matters in the deferred total-beta step).

## 6. Reconciliation

`scripts/reconcile_capiq_beta.py`:

1. Pull β + R² from the module for the 8 US dealers.
2. Read CapIQ `5 Year Beta` (Operating Statistics col 12) and `5 Year Beta R-Squared` (Valuation col 8).
3. Print per-peer Δβ and ΔR² side-by-side.

**Acceptance criteria** (provisional, refine after first run):

- |Δβ| ≤ 0.05 and |ΔR²| ≤ 0.03 for ≥ 6 of 8 dealers
- No individual peer exceeds |Δβ| 0.15 or |ΔR²| 0.10 — anything that wide signals a real bug (wrong index, wrong adjusted-close convention, delisting mid-window) rather than methodological noise

Expected residual sources (won't be zero):
- Log vs simple returns (~0.5–1% relative)
- Month-end date convention differences vs CapIQ
- CapIQ's exact "5Y" window definition (60 months back from quarter-end vs `as_of`)

## 7. Explicitly Out of Scope (Deferred)

- Peer D/E, cash, tax rates — not needed for β + R²
- Unlever / cash-correct / total-beta / relever chain
- Subject company inputs
- MCS hooks
- Damodaran weekly / blended methodology
- NYSE Composite as alternative index

These belong to the bottom-up beta module, which is a separate later task.

---

**Next step after sign-off:** implement `edgar/market_data/yahoo.py` + `edgar/metrics/beta.py` + `scripts/reconcile_capiq_beta.py`. Estimated ~150 lines total. No new PyPI dependencies.
