---
name: aidrin
description: AI data readiness check (AIDRIN) for tabular files. `gate` runs the
  project's metric profile before/after a pipeline stage and writes one JSON
  report; the passthrough form runs any aidrin command.
executable: dsagt-run --code aidrin -- python codes/aidrin/scripts/aidrin.py
parameters:
  subcommand:
    type: string
    required: true
    cli: positional
    description: "`gate`, or an aidrin subcommand (`run`, `list`, `summarize`, `data-quality`, `batch`)"
  args:
    type: string
    required: false
    cli: "positional:1"
    description: Remaining arguments; see the forms below
---

# aidrin

Readiness check for tabular data (CSV, Excel, JSON, HDF5, Parquet, npz) using
AIDRIN. Present in a project only when `dsagt init --readiness aidrin` was
chosen; the `aidrin` executable comes from `readiness.executable` in
`.dsagt/config.yaml`.

## Gate (the per-stage check)

```bash
dsagt-run --code aidrin -- python codes/aidrin/scripts/aidrin.py gate <file> \
    [--profile quality|supervised] [--target COL] \
    [--categorical "a,b"] [--numerical "c,d"] --report audit/step_N_pre.aidrin.json
```

Runs every metric in the profile and writes `{"file", "profile", "metrics": {metric: result}}`
to stdout and to `--report`. Exit code is nonzero if any metric failed; the
report still records the other metrics.

| Profile | Metrics | Required options |
|---|---|---|
| `quality` (default) | completeness, duplicity, outliers | none |
| `supervised` | quality + class-imbalance, feature-relevance | `--target`; `--categorical` and/or `--numerical` |

Run the gate on the stage input before the operation and on the stage output
after it, then compare the two reports.

## Passthrough (any aidrin command)

```bash
dsagt-run --code aidrin -- python codes/aidrin/scripts/aidrin.py [--report PATH] <aidrin args...>
```

Examples:

```bash
... aidrin.py list
... aidrin.py summarize data/x.csv --summary
... aidrin.py --report audit/corr.json run correlations data/x.csv "a,b,c"
... aidrin.py run k-anonymity data/x.csv "age,sex,zip"
```

Positional forms for the common metrics (`aidrin run <metric> -h` prints each):

| Metric | Arguments after `<file>` |
|---|---|
| completeness, duplicity, outliers | none |
| class-imbalance | `<target-column>` |
| feature-relevance | `"<categorical cols>" "<numerical cols>" <target-column>` |
| correlations | `"<columns>"` |
| k-anonymity | `"<quasi-identifiers>"` |

Fairness-rate and privacy metrics assume sensitive attributes or
quasi-identifiers; confirm with the user that the dataset has them before
running those.
