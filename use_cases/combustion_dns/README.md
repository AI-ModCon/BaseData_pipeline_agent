---
title: BlastNet → WELL Conversion
domain: Combustion CFD — BlastNet DNS trajectories to the WELL HDF5 format
summary: >-
  Convert BlastNet direct-numerical-simulation trajectories into the WELL HDF5
  format with a converter developed iteratively under DSAgt — ingest the format
  specification into the knowledge base, register the converter and its checker
  as codes, convert a sample trajectory with provenance, validate it against a
  holdout reference, and reconstruct the pipeline.
status: published
order: 90
---

# DSAgt Demo: BlastNet → WELL Conversion

> **Estimated time:** ~20 minutes with the sample trajectory from the data
> bundle. Full BlastNet channel-flow cases are hundreds of GB and need an HPC
> node; this demo uses one small lifted-hydrogen-jet trajectory.

[BlastNet](https://blastnet.github.io/) publishes combustion DNS datasets as
per-trajectory directories of raw float32 arrays plus an `info.json`.
Machine-learning pipelines consume them in the [WELL](https://polymathic-ai.org/the_well/)
HDF5 layout. This use case is the converter that bridges the two, and the DSAgt
session that exercises it.

The converter [`convert_to_well_format_v4.py`](blastnet_minimal_input/convert_to_well_format_v4.py)
and its checker [`check_well_output.py`](blastnet_minimal_input/check_well_output.py)
were developed over four iterations in a DSAgt session, each version validated
against holdout reference files. The development record — all four versions and
their comparison reports — is preserved under
[`blastnet_minimal_input/`](blastnet_minimal_input/) (see its
[README](blastnet_minimal_input/README.md) and
[development summary](blastnet_minimal_input/development_summary_report.md)).
The walkthrough below drives the final converter.

## Prerequisites

- DSAgt installed (`uv sync --all-groups`) and an agent platform installed and
  **already authenticated** (BYOA — dsagt writes no credentials; the default
  local embedder needs no API key).
- `numpy` and `h5py` importable in the environment `dsagt` runs in.

## Setup

```bash
dsagt init
```

At the menu, name the project `blastnet-well` and pick your agent; the defaults
are fine for the rest. Then:

```bash
PROJ=~/dsagt-projects/blastnet-well
# Demo data (one BlastNet trajectory and its holdout WELL reference file) from
# the DSAgt use-case data folder:
# https://drive.google.com/drive/folders/1RWQAJeHaikIaD7CCf8ciJ71m55S1erp6
curl -L "https://drive.usercontent.google.com/download?id=1xUZhlr6uCahSbOLiLt5wcwMzehdpaUjL&export=download&confirm=t" \
  -o combustion_dns_data.tar.gz
tar xzf combustion_dns_data.tar.gz -C "$PROJ"
# creates $PROJ/data/blastnet_data/lifted_hydrogen_jet/hydrogen-jet-5000/
#     and $PROJ/data/holdout/well_output/lifted_hydrogen_jet_traj_5000.hdf5
mkdir -p "$PROJ/codes/scripts" "$PROJ/docs"
cp use_cases/combustion_dns/blastnet_minimal_input/convert_to_well_format_v4.py \
   use_cases/combustion_dns/blastnet_minimal_input/check_well_output.py "$PROJ/codes/scripts/"
cp use_cases/combustion_dns/blastnet_minimal_input/well_format.md \
   use_cases/combustion_dns/blastnet_minimal_input/README-blastnet.md "$PROJ/docs/"
dsagt start blastnet-well
```

## Execution

Paste these prompts one at a time.

### 1. Ingest the format specifications

```text
Ingest docs/ into the knowledge base as a collection called "well_format". It
holds the WELL HDF5 format specification and the BlastNet dataset layout.
```

**Verify:** `List all knowledge base collections.` → `well_format`.

### 2. Query the specification

```text
Search the well_format collection: which BlastNet fields go into t0_fields
versus t1_fields in a WELL file, and how are boundary conditions represented?
```

**Expect:** scalar fields (pressure, density, temperature, species mass
fractions) in `t0_fields/`, velocity stacked as a vector in `t1_fields/`, and
per-type mask groups under `boundary_conditions/`.

### 3. Register the converter and checker as codes

```text
Register two codes. convert-to-well runs
`python codes/scripts/convert_to_well_format_v4.py` with a positional
trajectory directory and the options --output-path, --output-file, and
--dry-run. check-well-output runs `python codes/scripts/check_well_output.py`
with positional candidate and reference files and the options --rtol, --atol,
--spot-check, --n-points, and --seed. Run --help on each first to confirm.
```

**Verify:** `Search the registry for WELL conversion codes.` → both specs under `codes/`.

### 4. Dry run

```text
Do a dry run of the converter on
data/blastnet_data/lifted_hydrogen_jet/hydrogen-jet-5000 and tell me the grid
size, the number of snapshots, and which WELL fields it would write.
```

**Expect:** `dsagt-run` wraps the converter with `--dry-run`; no HDF5 is written.

### 5. Convert the trajectory

```text
Convert data/blastnet_data/lifted_hydrogen_jet/hydrogen-jet-5000 to
well_output/lifted_hydrogen_jet_traj_5000.hdf5 using the registered code.
```

**Expect:** one HDF5 file with `dimensions/`, `boundary_conditions/`,
`t0_fields/`, `t1_fields/velocity`, and the root attributes the specification
requires.

### 6. Validate against the holdout reference

```text
Spot-check well_output/lifted_hydrogen_jet_traj_5000.hdf5 against
data/holdout/well_output/lifted_hydrogen_jet_traj_5000.hdf5 with 10 random
points per dataset, then run the full comparison. Summarize any structural or
numerical differences.
```

**Expect:** both checker runs pass — matching structure, field shapes, and
values within tolerance.

### 7. Generate a datacard

```text
Search for a skill that can generate a datacard for the converted WELL file,
then use it.
```

### 8. Reconstruct the pipeline

```text
Reconstruct the conversion and validation pipeline from the execution records
as a bash script, with the trajectory directory as a variable at the top so it
can be rerun on the other BlastNet trajectories.
```

## Post-Conditions

1. Knowledge base contains the `well_format` collection with both specification documents.
2. Code registry contains `convert-to-well` and `check-well-output` specs.
3. `well_output/lifted_hydrogen_jet_traj_5000.hdf5` exists and the checker
   reports it matches the holdout reference.
4. A datacard exists for the converted dataset.
5. `trace_archive/` holds one execution record per converter and checker run.
6. A reconstructed pipeline script replays conversion and validation for a
   parameterized trajectory directory.
7. MLflow traces (in the serverless `mlflow.db` store) capture the session —
   `mlflow ui --backend-store-uri sqlite:///$PROJ/mlflow.db`.

## What This Tests

| DSAgt Capability | Steps |
|------------------|-------|
| Knowledge ingestion of format specifications | 1 |
| Semantic search for schema questions | 2 |
| Code registration (`save_code_spec`) and registry search | 3 |
| Code execution with provenance through `dsagt-run` | 4–6 |
| Paired operation and check codes | 5, 6 |
| Skill discovery and use (datacard generation) | 7 |
| Pipeline reconstruction with a parameterized input | 8 |

## Cleanup

```bash
dsagt rm blastnet-well -y
rm combustion_dns_data.tar.gz
```

## Notes

- The demo bundle is the first snapshots of the `hydrogen-jet-5000` trajectory
  (a full trajectory is ~32 GB) with the reference WELL file sliced
  to the same steps. It is built from the full data with
  [`make_demo_subset.py`](blastnet_minimal_input/make_demo_subset.py):

  ```bash
  python3 make_demo_subset.py <traj_dir> <reference.hdf5> <out_dir> --steps 5
  tar czf combustion_dns_data.tar.gz -C <out_dir> data
  ```

  The subset converts and checks exactly like the full trajectory, since the
  converter enumerates snapshots from `info.json` and every time-varying WELL
  dataset carries time on axis 1.
