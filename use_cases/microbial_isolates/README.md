---
title: Microbial Isolates
domain: Genomics — short-read QC and assembly with `fastp` + `megahit`
summary: >-
  Register short-read QC and assembly codes, ingest genomics best-practice
  knowledge, and build a reproducible isolate-processing pipeline against real
  sequencing reads.
status: published
order: 10
---

# DSAgt Demo: Microbial Isolate Processing

> **Estimated time:** advanced / not a 10-minute demo. The isolate data is
> pulled from **NERSC** (requires an account + allocation — step 3), and
> `megahit` assembly runs minutes per sample across ~11 isolates. Treat this as
> a bring-your-own-HPC-data walkthrough; substitute your own FASTQ files for the
> NERSC path if you don't have NERSC access.

This guide documents a reproducible DSAgt demonstration for microbial isolate data processing using `fastp` and `megahit`.

## Prerequisites

- DSAgt installed (`uv sync --all-groups`)
- An agent platform installed and **already authenticated** (e.g., `claude` for Claude Code, or
  `goose`) — BYOA: dsagt writes no credentials. The default local embedder needs no API key.
- Conda (for installing fastp and megahit)
- Git installed

## Setup

### 1. Install fastp and megahit

fastp and megahit are C/C++ programs installed via Bioconda, not pip:

```bash
conda create -n isolate -c conda-forge -c bioconda fastp megahit -y
conda run -n isolate fastp --version
conda run -n isolate megahit --version
```

Note the conda env prefix (e.g., `~/miniconda3/envs/isolate/bin/`) — you'll reference these paths when registering the codes.

### 2. Initialize a DSAgt project

```bash
dsagt init
```

At the menu, name the project `isolate-pipeline` and pick your agent; the defaults are fine
for the rest. Then:

```bash
PROJ=~/dsagt-projects/isolate-pipeline
```

(The default local embedder needs no key. To use a hosted embedder instead, set
`embedding.backend: api` in `$PROJ/.dsagt/config.yaml` and export `EMBEDDING_API_KEY`
in your shell — never written to disk.)

### 3. Collect data and reference material into the project

The agent runs with the project directory as its working directory, so everything it
reads goes under `$PROJ`.

```bash
mkdir -p "$PROJ/data/microbial_isolate" "$PROJ/repos" "$PROJ/docs"
scp <nersc-username>@dtn01.nersc.gov:/global/cfs/projectdirs/amsc002/base_data/example_famous_data/* "$PROJ/data/microbial_isolate/"
git clone https://github.com/OpenGene/fastp.git "$PROJ/repos/fastp"
git clone https://github.com/voutcn/megahit.git "$PROJ/repos/megahit"
cp use_cases/microbial_isolates/genomics.md use_cases/microbial_isolates/fastp_megahit_best_practices.md "$PROJ/docs/"
```

### 4. Start the session

```bash
dsagt start isolate-pipeline
```

The agent launches from the project directory with the MCP server connected. Serverless — there are no background services to clean up.

## Execution

Use these prompts in the agent session. Replace `<CONDA_PREFIX>` with your conda env bin path (e.g., `~/miniconda3/envs/isolate/bin`). Data, repos, and docs paths are relative to the project directory.

### 1. Build knowledge base

```text
I'd like to create a new collection in the knowledge base: microbial_isolates.
The collection will contain:
1) the code package files for fastp: repos/fastp/
2) the code package files for megahit: repos/megahit/
3) a short document describing a processing pipeline: docs/genomics.md
4) best practices for fastp and megahit: docs/fastp_megahit_best_practices.md
```

### 2. Register codes

```text
Let's add <CONDA_PREFIX>/fastp to the registry
Let's add <CONDA_PREFIX>/megahit to the registry
```

**Verify:**

```text
Search the registry for assembly codes.
```

### 3. Process one sample

```text
I have an isolate file at data/microbial_isolate/53162.2.609630.AAAGGCTAGA-GATTCAGTTA.filter-ISO.fastq.gz
Information about the dataset is in the README in that directory. I need to preprocess this file and assemble it.
fastp and megahit both have data assessment capability so we don't need to create additional codes.
megahit should be run with kmax=21 and memory=0.3 to avoid OOM on this laptop.
Tell me your plan before proceeding.
```

### 4. Process remaining samples

```text
Let's run this same pipeline on the rest of the fastq files at data/microbial_isolate/
We can process them one at a time.
```

### 5. Generate datacard

```text
Search for a skill that can generate a datacard for our processed data, then use it.
```

The agent should find the `datacard-generator` skill in the `genesis` catalog via `search_skills` and install it with `install_skill` (only `skill-creator` is built in; domain skills come from catalogs).

### 6. Reconstruct pipeline

```text
Reconstruct the pipeline from the execution records as a bash script.
```

The agent calls `reconstruct_pipeline` to generate a reproducible script from the trace archive.

## Post-Conditions

1. Knowledge base contains collection `microbial_isolates` with all listed references indexed.
2. Code registry includes `fastp` and `megahit` code specs (wrapped with `dsagt-run`).
3. Processed output directories exist for each isolate sample.
4. For each completed sample:
   - Preprocessed FASTQ output exists
   - `fastp` HTML and JSON reports exist
   - Assembly output exists, including `final.contigs.fa`
5. A Level 1 datacard exists for the processed dataset.
6. A reconstructed pipeline script (bash or Snakemake) is available.
7. Code execution records in `trace_archive/` document the full provenance chain.
8. MLflow traces (in the serverless `mlflow.db` store) capture token usage, latency, and full request/response history. View with `mlflow ui --backend-store-uri sqlite:///$PROJ/mlflow.db`.

`megahit` may intermittently fail with segmentation faults on some files/hardware settings. If this occurs, rerun that sample with conservative settings while preserving the required `kmax=21` and laptop-safe memory cap.

## What This Tests

| DSAgt Capability | Steps |
|------------------|-------|
| Knowledge ingestion (source repos + documents into one collection) | 1 |
| Registering external binaries as codes | 2 |
| Registry search | 2 |
| KB-guided pipeline planning | 3 |
| Code execution with provenance across many samples | 3, 4 |
| Skill discovery and installation from a catalog | 5 |
| Pipeline reconstruction | 6 |

## Cleanup

```bash
dsagt rm isolate-pipeline -y
conda env remove -n isolate -y
```
