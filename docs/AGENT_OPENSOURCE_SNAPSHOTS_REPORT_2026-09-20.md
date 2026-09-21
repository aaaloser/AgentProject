# MokioClaw Agent Open-Source Snapshot Report

**Scope:** Rich v14.3.4 snapshot; two Cases; three architectures; four resource cells; three repeats per cell. This is an exploratory report for the two Rich Cases only (`n=6` runs per architecture per cell, 72 Agent runs total). Fixture red/green acceptance is not Agent performance evidence.

## Frozen identity and resources

- Freeze commit: `5ba88ab32fe9cc46d98e3797276230c70495fe65`.
- Rich source commit: `ee8378c3bbbd7c75abc2f55c6c19e83b218ae81d`; source archive SHA-256: `3390285ef57f8a4ee777e0bbe5e92e85d2b904b4d8a5524c1ab22dc1c9c56e1e`.
- Rich image: `mokioclaw-eval-rich:14.3.4`; image ID `sha256:3e3b35aae4cf2420edc787f8a25d991d8a94a702cb972f31f339255cc661a7bb`.
- Dependency lock SHA-256: `7b91fb686b51b937cee8599573d7144a0082bbe43b6045842fed8b52234c9ac4`.
- Dockerfile SHA-256: `4b35152cedbcf25223730bd9107e07c98c8dd50fc09eb233335d82a7edb5cb13`.
- Schedule SHA-256: `d809bc86b9a928ba927c436e85d7bcaa3c106e9e00078058841b1f10a5e2874a`.
- Case YAML SHA-256: Markdown `e06c63a62ad315539ef57c7e61818fe67ea6bb5586bf351d65807eec5f836b19`; Table `4db343a5d4025a15f2a4efc2547136c9936cf2cf950af0b0706f3f6d0a68ecad`.
- Runtime envelope: Docker network `none`, 1 CPU, 512 MiB memory, pids limit 128, read-only rootfs, `/tmp:rw,noexec,nosuid,size=64m`.

Cells and execution rotation:

| Label | Cell | Limits | R1 | R2 | R3 |
|---|---|---|---:|---:|---:|
| A | `anchor-b40-t600` | 40 tool calls / 600 s | 3 | 3 | 1 |
| B | `cell-b80-t600` | 80 tool calls / 600 s | 2 | 1 | 4 |
| T | `cell-b40-t900` | 40 tool calls / 900 s | 4 | 3 | 2 |
| J | `cell-b80-t900` | 80 tool calls / 900 s | 1 | 4 | 3 |

The schedule was immutable after preflight. Every cell passed the per-cell Docker/image/identity/minimal-auth preflight before its round.

## 72-run ledger

Each cell has 18 rows, with six unique Case×architecture rows at each repeat (`repeat=1,2,3`). The final manifests contain 72 unique cell-qualified keys.

| Cell | passed | budget-exhausted | timed-out | failed | setup-failed |
|---|---:|---:|---:|---:|---:|
| A | 3 | 6 | 4 | 0 | 5 |
| B | 3 | 0 | 8 | 1 | 6 |
| T | 5 | 8 | 0 | 0 | 5 |
| J | 6 | 0 | 3 | 3 | 6 |
| **Total** | **17** | **14** | **15** | **4** | **22** |

Instrumentation totals are 2,134 tool calls. Token telemetry is available for 21/72 runs: input `4,109,731`, output `193,466`, total `4,303,197`; telemetry is unavailable for the remaining 51 runs. All 72 `estimated_cost` fields are `null`, so no billing estimate is inferred.

All 22 `setup_failed` rows are worker-stage provider 504s. Nineteen had zero tool calls; three reached 13, 18, and 38 tool calls before the provider response failed. The two R1 cleanup backups remain preserved at:

- `evals/reports/snapshots-20260920/cell-b80-t900/manifest.jsonl.bak-20260921T104805+0800-provider-504-no-tools`
- `evals/reports/snapshots-20260920/cell-b80-t600/manifest.jsonl.bak-20260921T122903+0800-provider-504-no-tools`

The repeated/new anomalies were retained as observable ledger evidence; they are not treated as successful Agent runs and were not manually retried after R1/R2 cleanup decisions.

## Mechanical analysis

The final snapshot analysis is complete (`pooled.status=complete`, no incomplete cell/architecture entries). The six non-react relaxed-cell states are:

| Architecture | Relaxed cell | State | S | E | P |
|---|---|---|---:|---:|---:|
| multi-agent | B | resource-relief-no-success | no | yes | yes |
| multi-agent | T | resource-relief-no-success | no | yes | no |
| multi-agent | J | resource-relief-no-success | no | yes | yes |
| plan-execute | B | resource-relief-no-success | no | no | yes |
| plan-execute | T | resource-relief-no-success | no | no | yes |
| plan-execute | J | resource-relief-success | yes | no | yes |

Q1 mapping:

- `multi-agent`: **both axes independently influential**; budget-priority pattern is true.
- `plan-execute`: **both axes independently influential**; budget-priority pattern is true.

Q2 mapping for `plan-execute`: **no time-wall migration signal / inconclusive**. Dual-axis conversion is false and time remains binding is false under the preregistered rule.

Per-case analysis finds mixed direction in B/T/J for both non-react architectures. Divergence is false for multi-agent B/J, true for multi-agent T, and true for plan-execute B/T/J. These are exploratory patterns, not causal claims.

The analysis warning list contains eight `unknown stage observed` entries for `intent_router`, all attached to provider-interrupted rows. This is an observability warning only; no unregistered causal label is assigned.

React is a drift canary and is excluded from Q1/Q2. Markdown passed 11/12 React runs; Table passed 0/12. Markdown drift occurred in B (one timeout); Table showed resource/provider/public-verification failures across all cells, including three J public-verification failures.

## Reproducibility artifacts

All paths below are relative to this worktree and are ignored generated artifacts under `evals/reports/snapshots-20260920/`:

- `analysis/preflight.json`
- `execution-schedule.json`
- `analysis/thresholds.json` — SHA-256 `B99BA64320362DED877777CA4BE9130BC08A8619A1BCB5CC3910D4E0721CABEB`
- `analysis/per-case.json` — SHA-256 `167FC8EC4B48B03A3FD2F8248E0F653B085DF92498A78CFC4BF23571C98EA4FB`
- `analysis/pooled.json` — SHA-256 `6F84A1281593994E7F9FF37F250F00DF366EB7BFEE14C0EC6ED8C638D1D069F2`
- `analysis/report.md` — SHA-256 `02BCD27088F4959FB4599A32B2B06126DA561225376367F96E060F5B1939925F`
- `anchor-b40-t600/`, `cell-b80-t600/`, `cell-b40-t900/`, `cell-b80-t900/` — append-only manifests, experiment identities, run results, and per-cell reports.

## Extension decision

This report is limited to the frozen Rich snapshot. The click primary and httpie backup repositories were not started. Any extension requires a separate design/plan and a new preflight identity; it must not be appended to this 72-run batch.
