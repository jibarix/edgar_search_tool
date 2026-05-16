# Known Issues

Tracked defects in the EDGAR pull/metric layer. Newest first.

---

## KI-5 · `utils/cache.py` is not concurrency-safe (parallel-run race)

- **Severity:** Medium (infrastructure, not a metric defect) — only
  bites when reconcile scripts run in parallel against shared cache
- **Status:** **Resolved** 2026-05-16 — steps 1–3 applied & validated
- **Found:** 2026-05-16, running all four dealer reconcile scripts in
  parallel; comps + correlation crashed, beta + valuation survived
- **Component:** `utils/cache.py` → `Cache.get`

### Symptom

```
PermissionError: [WinError 32] The process cannot access the file
because it is being used by another process:
'...\cache\filing_data\company_facts_0000799850.cache'
```

raised from `os.remove(cache_path)` inside `Cache.get`. The four
reconcile scripts all pull the same issuers' Company Facts and share
one on-disk cache dir; run sequentially they are fine, run in parallel
two processes touch the same `company_facts_*.cache` and one dies.

### Root cause

`Cache.get` handles a stale/expired entry by **deleting the cache file
in the read path** with a bare `os.remove(cache_path)` (twice — once in
the expiry branch, once in the except handler at lines ~104 and ~111).
On Windows a concurrent reader holding the same file open makes
`os.remove` raise `PermissionError` (WinError 32) instead of silently
unlinking as on POSIX. There is no file lock, no per-process temp file,
and no swallow of the removal error, so a normal cache-eviction race
turns into a hard crash that aborts the whole reconcile.

This is **not** a metric/logic defect: the numbers the surviving runs
produced are correct, and re-running comps + correlation sequentially
(task `b9ml272qd`) completed exit 0 with the expected baseline deltas.

### Impact

Any parallel invocation of the reconcile harness (or any two engine
callers sharing the cache dir) can crash non-deterministically on
Windows. Masks itself as a per-ticker failure even though the engine
output is sound. Workaround today: run the reconcile scripts
sequentially (proven clean).

### Fix (applied)

`utils/cache.py` made race-tolerant rather than serialising callers:

1. **Race-tolerant eviction** — corrupt-content unlink in `get()` is
   wrapped in `try/except OSError: pass`; a failed eviction degrades
   to a cache *miss*, never a crash.
2. **Locked entry → miss** — `get()` now splits exception handling:
   `OSError` on read (locked/unreadable; the other process owns the
   file) returns `None` with **no** unlink in the hot path; only
   genuine `PickleError`/`EOFError` (corrupt content) triggers
   eviction.
3. **Eviction out of the read path** — expired entries are no longer
   unlinked in `get()`; they read as a miss and are reclaimed by the
   `cleanup()` maintenance sweep (also fully race-tolerant). `set()`
   now writes a process-unique `*.tmp` then `os.replace()`s it into
   place (atomic on POSIX and Windows), so a concurrent reader never
   observes a half-written entry.

### Validation

- Self-test: set/get roundtrip OK, no `*.tmp` leak, expired→miss
  without read-path unlink, `cleanup()` reclaims expired/corrupt.
- Original repro: comps + correlation reconcile run **in parallel**
  against the shared cache — previously both crashed on
  `company_facts_0000799850.cache` (WinError 32); now both exit 0
  with unchanged baseline deltas.

---

## KI-1 · `search_company` returns wrong company for superstring tickers

- **Severity:** High *as observed*, but **out of engine scope** — see
  "Scope" below.
- **Status:** Documented limitation (not an engine fix). To be handled
  by the planned search-validation module.
- **Found:** 2026-05-16, via the Health Care Services screening reconcile
  (`scripts/reconcile_capiq_screening.py`, ticker `AONC`)
- **Component:** `edgar/company_lookup.py` → `search_company`
  (consumed by the reconcile harness, which is **engine test
  scaffolding**, not production)

### Scope

The current reconcile scripts are **engine-accuracy test harnesses**:
they exercise the XBRL pull + metric layer, not production lookup.
In production, ticker → company resolution and the check that a
resolved filer actually belongs to the requested screen/industry will
be owned by a **separate search-validation module** that sits in front
of the engine. Mis-resolution like `AONC → Aon plc` is therefore the
validation module's responsibility to catch, not a `search_company`
defect to patch in the engine. This entry stays as a recorded
limitation so harness output (e.g. the AONC row) is read correctly —
**wrong-company, expected until the validation module exists** — and
so the future module's spec captures the superstring-ticker failure
mode as a required test case.

### Symptom

`AONC` (American Oncology Network) reconciled with a total debt of
**$16,265M vs CapIQ $133M (+12,138%)**. Every other AONC metric was
also off by orders of magnitude.

### Root cause

`search_company('AONC')` ranks a non-exact match first:

```
search_company('AONC') -> [
  {'cik': '0000315293', 'ticker': 'AON',  'name': 'Aon plc'},      # matches[0]
  {'cik': '0000824142', 'ticker': 'AAON', 'name': 'AAON, INC.'},
  {'cik': '0001400438', 'ticker': 'LGO',  'name': 'Largo Inc.'},
]
```

There is **no exact AONC row at all** (American Oncology Network may be
absent from the ticker map / filed under a different symbol), and the
resolver returns the prefix/fuzzy match `AON` (Aon plc) as the top hit.
Callers — every `reconcile_capiq_*.py` script and the MCP tools —
consume `matches[0]` unconditionally, so **Aon plc's Company Facts
(CIK 0000315293, total_debt $16.265B) were silently substituted for
AONC**. `total_debt_incl_leases` was not the bug; it merely inherited
the wrong-company base figure.

### Reproduction

```python
from edgar.company_lookup import search_company
from edgar.filing_retrieval import FilingRetrieval
print(search_company('AONC')[0])                       # -> Aon plc / AON / 0000315293
print(FilingRetrieval().get_company_facts('0000315293')['entityName'])  # -> 'Aon plc'
```

### Impact

Any time a queried ticker is **not present exactly** in the resolver's
universe but is a *superstring* of a shorter listed ticker (`AONC`⊃`AON`,
and the general `XYZ`⊃`XY` class), `matches[0]` can be a different,
often much larger company. This fails **silently** — no exception, no
empty result — so downstream metrics, reconciles, and any MCP
`compute_metric`/`get_financial_statement` call return another
company's financials. The earlier "resolver gap" names that returned
*no* data (AMED, PINC, MODV, ENZ, PHLT, ME) are the safer failure mode
of the same lookup weakness; this superstring case is the dangerous
one because it produces plausible-looking wrong numbers.

### Requirements for the planned search-validation module

Captured here as test cases the future module must cover (not engine
TODOs):

1. Prefer **exact case-insensitive ticker equality**; an exact hit must
   win over any prefix/substring/fuzzy match.
2. When no exact ticker match exists, treat the name as **unresolved**
   rather than accepting a fuzzy hit as a confident match.
3. Cross-check the resolved filer against the requested screen's
   **industry/SIC** — the superstring case (`AONC`⊃`AON`,
   health-care-services screen resolving to insurer Aon plc) must be
   rejected by an industry-alignment check even if a fuzzy ticker
   match slips through.

### Workaround until fixed

Treat any screening/reconcile row whose resolved entity name is
implausible for the ticker as unresolved. The screening reconcile's
AONC row should be read as **wrong-company, not a debt-line defect**.

---

## KI-2 · Multi-segment revenue resolves to a partial ASC606 line — RESOLVED

- **Severity:** Medium (understated revenue/gross for affected names)
- **Status:** **Resolved** 2026-05-16 via per-profile `chain_overrides`
- **Found:** Health Care Services screening reconcile, ticker `CHE`
- **Component:** `edgar/metrics/_concepts.py` global `revenue` chain

### Symptom

Chemed (`CHE`, VITAS hospice + Roto-Rooter) reconciled at Revenue
**−35.6%** (EDGAR 1,531M vs CapIQ 2,377M) while EBITDA (−0.1%) and
NI (+0.1%) were near-exact — i.e. only the revenue line was wrong.

### Root cause

The global `revenue` chain is `RevenueFromContractWithCustomer…`-first
(deliberately, and correct for auto dealers). CHE tags **both** a
partial ASC606 contract line and a total `Revenues` line for FY2024:

```
Revenue_RevenueFromContractWithCustomerExcludingAssessedTax  2024 = 1,530,978,000  (partial)
Revenue_Revenues                                             2024 = 2,431,287,000  (total)
```

The chain picked the 1,531M partial. (FY2025 only tags `Revenues`,
which is why the bug was invisible at the FY2025 anchor.)

### Fix

Added a `revenue` `chain_overrides` to the `screening_hc` profile
(`scripts/_capiq_profiles.py`) flipping `Revenues` ahead of the
contract tags — same mechanism and rationale as the existing `MALLS`
override. The **global chain is unchanged**, so the auto-dealer
comp set (which needs contract-tag-first) does not regress.

### Validation

CHE Revenue Δ **−35.6% → +2.3%** (in line with peers). No regression
on clean names: ADUS +1.8%, DVA +1.2%, DGX +3.5%, LH +2.3%, CVS +1.5%
(all unchanged); OPCH +2.8% → +4.6% (now resolves to the broader, more
correct `Revenues` total — still single-digit).

---

## KI-3 · CCRN EBITDA gap is a period/vintage artifact — NOT A BUG

- **Severity:** N/A (data-vintage, not an engine defect)
- **Status:** Closed — won't fix; documented so the row is read right
- **Found:** Health Care Services screening reconcile, ticker `CCRN`

### Symptom

Cross Country Healthcare (`CCRN`) FY2024 EBITDA reconciled at
**−85%** (EDGAR 4.6M vs CapIQ 31.1M) with revenue only −7%.

### Investigation

`ebit` = OpLoss(−16,865K) + GW impairment(370K) + asset impairment
(2,888K) = −13,607K; + D&A 18,200K = **4,593K** — EDGAR is internally
correct. The full FY2024 income statement contains **no large
impairment**; even summing every plausible CapIQ "unusual item"
add-back (GW 370K + asset 2,888K + intangible 1,800K + restructuring
4,333K + litigation 4,700K) only reaches ~15M EBITDA — still far below
CapIQ's 31.1M.

CCRN's earnings **cliffed** year-over-year: OperatingIncome FY2023
+112,713K → FY2024 −16,865K; NI +72,631K → −14,556K. CapIQ's "LTM"
column blends strong trailing-2023 quarters, so 31.1M reflects a
trailing window, not FY2024. The gap is a period-vintage artifact
amplified by the earnings cliff — **not a missing add-back**.

### Resolution

Won't fix. Synthesising add-backs to hit 31.1M would overfit the
engine to a CapIQ LTM-window mismatch. Read the CCRN screening row
as period-mismatched, not defective.

---

## KI-4 · CapIQ "Total Debt" maps to no single EDGAR basis — residual

- **Severity:** Low (known per-name residual; no clean global fix)
- **Status:** Open — documented limitation, no action
- **Found:** Health Care Services screening reconcile, debt column

### Summary

CapIQ "Total Debt [Latest Annual]" reconciles to **plain `total_debt`**
for some names (ADUS), to **`total_debt_incl_leases`** for others
(AIRS), and to **neither** for others (AMN −22%). A blanket swap to
`total_debt_incl_leases` (with operating-lease net-out) was tested and
**rejected** — it improved some names while regressing others and
exposed the wrong-company inflation from [KI-1] (AONC). The screening
script keeps the predictable plain `total_debt` basis; the debt column
is an accepted per-name residual, not a closable gap with the data
CapIQ exposes here.
