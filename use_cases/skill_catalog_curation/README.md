---
title: Catalog Skills for Data Curation
domain: Skill management — an external skill catalog driving a data-curation pipeline
summary: >-
  Sync an external skill catalog, install data-curation skills (datacard
  generation, Croissant validation), ground them in KB-ingested domain docs,
  and produce a datacard for a small curated dataset.
status: published
order: 60
---

# DSAgt Demo: Catalog Skills for a Data-Curation Pipeline

> **Estimated time:** ~10 minutes (the data is tiny; the one external
> dependency is a shallow clone of the skill catalog from OSTI GitLab — needs
> network access to `gitlab.osti.gov`).

An end-to-end **data-preparation** walkthrough that exercises the skill catalog
against the `genesis` source (hosted on OSTI GitLab). The agent pulls in the
catalog's data-curation skills, grounds itself in domain context loaded into
the **knowledge base**, then prepares and **datacards a finished dataset**.

The "finished product" is a small curated dataset — a CO2-methanation **catalyst
screen** (`dataset/catalyst_screening.csv`, 8 rows) — plus the domain docs that
describe how it was produced. Everything is tiny, so the whole thing runs in
seconds with no real instruments or HPC.

## Prerequisites

- DSAgt installed (`uv sync --all-groups`) and an agent platform installed and
  **already authenticated** (BYOA — dsagt writes no credentials).
- Git, with network access to `gitlab.osti.gov` (the `genesis` catalog clones
  from OSTI GitLab, not GitHub).
- Embedding credentials are optional — `search_skills` / `kb_search` use
  semantic search when `EMBEDDING_*` is set and fall back to a keyword scorer
  otherwise (configure it for sharper relevance over the domain docs).

## Setup

```bash
dsagt init
```

At the menu, name the project `genesis-skills`, pick your agent, and **uncheck `genesis`**
at the skill-sources checkbox — the walkthrough has the agent enable that catalog itself
in step 1. Then:

```bash
PROJ=~/dsagt-projects/genesis-skills
# Demo data (catalyst_screening.csv, the domain docs, and the expected datacard)
# from the DSAgt use-case data folder:
# https://drive.google.com/drive/folders/1RWQAJeHaikIaD7CCf8ciJ71m55S1erp6
curl -L "https://drive.usercontent.google.com/download?id=1nji0Avc-n952isq5aKGLoZgTkYHe0jzR&export=download&confirm=t" -o catalog_demo_data.tar.gz
tar xzf catalog_demo_data.tar.gz -C "$PROJ" --strip-components=1 genesis_skills/mock_data
# $PROJ/mock_data now holds dataset/, domain/, expected_datacard.md
dsagt start genesis-skills
```

## Execution

Paste each prompt into the agent (running inside the project), one at a time.
Confirmation checks are consolidated in **Post-Conditions** below.

### 1. Enable the catalog source

```text
Enable the "genesis" skill source so we have its data-curation skills available. Then tell me how many skills it indexed.
```

**Expect:** `add_skill_source(source="genesis")` → a shallow clone of OSTI GitLab,
its skills indexed, source written to `.dsagt/config.yaml`.

### 2. Find and install the curation skills

```text
Search the catalog for two skills — one that creates a datacard / dataset documentation for a dataset, and one that validates Croissant / JSON-LD dataset metadata — and install the best match for each into this project.
```

**Expect:** `search_skills` surfaces **`generating-datacards`** and
**`croissant-validator`** → `install_skill` for each. Both are installed into
`<project>/skills/` and mirrored into the agent's native skills directory at
install time, each with a `PROVENANCE.txt` crediting the source.

### 3. Ingest the domain docs into the KB

```text
Ingest the domain docs under mock_data/domain/ into a new knowledge-base collection called "methanation_domain". Poll until it finishes, then tell me what's in it.
```

**Expect:** `kb_ingest(folder_path="mock_data/domain", collection_name="methanation_domain")`
returns a `job_id`; the agent polls `kb_job_status` to completion, then
`kb_list_collections` shows `methanation_domain` (2 docs).

### 4. Retrieve domain grounding

```text
Using the knowledge base, what reactor conditions were used for the CO2 conversion measurement, and what license applies to this dataset?
```

**Expect:** `kb_search` over `methanation_domain` → **250 °C, 1 atm, H2:CO2 = 4:1,
GHSV 12,000**; license **CC-BY-4.0**.

### 5. Generate the datacard for the finished dataset

```text
Use the generating-datacards skill to write a datacard for mock_data/dataset/catalyst_screening.csv. Pull the field definitions, measurement methodology, provenance, and license from the methanation_domain knowledge-base collection — don't invent them. Save it to audit/catalyst_screening_datacard.md. Then compare your sections against mock_data/expected_datacard.md and report anything missing.
```

**Expect:** the agent reads the installed skill's `SKILL.md`, queries the KB,
computes basic stats from the 8-row CSV, and writes
`audit/catalyst_screening_datacard.md` covering summary / provenance / schema /
methodology / stats / limitations / license.

### 6. Validate the metadata

```text
Use the croissant-validator skill to check the Croissant/JSON-LD metadata for this dataset (generate it from the datacard if needed), and report any schema errors.
```

**Expect:** the validator skill runs and reports a clean pass or names specific
schema issues.

## Post-Conditions

Confirm from a shell (the native skills directory is `.claude/skills/` for Claude Code,
`.agents/skills/` for Codex, Goose, and opencode, `.cline/skills/` for Cline):

```bash
dsagt info genesis-skills                  # KB lists skills_catalog__genesis-genesis-skills + methanation_domain
ls "$PROJ/skills/"                         # generating-datacards  croissant-validator
cat "$PROJ/skills/generating-datacards/PROVENANCE.txt"
ls "$PROJ/audit/"                          # catalyst_screening_datacard.md
```

1. The KB holds a `skills_catalog__genesis-genesis-skills` collection
   (searchable via `search_skills`) **and** a `methanation_domain` document
   collection (retrievable via `kb_search`).
2. `generating-datacards` and `croissant-validator` are installed into
   `<project>/skills/` and mirrored into the agent's native skills directory,
   each with a `PROVENANCE.txt` crediting the source. The next session
   auto-invokes them natively; this session used them by reading their
   `SKILL.md`.
3. `audit/catalyst_screening_datacard.md` was produced for the finished dataset,
   grounded in the KB-ingested domain docs, covering the sections in
   `mock_data/expected_datacard.md`.
4. MLflow traces (in the serverless `mlflow.db` store) capture the session —
   `mlflow ui --backend-store-uri sqlite:///$PROJ/mlflow.db`.

## What This Tests

| DSAgt Capability | Steps |
|------------------|-------|
| Enabling an external skill source in-session (`add_skill_source`) | 1 |
| Catalog search and install (`search_skills`, `install_skill`) | 2 |
| Native mirroring of installed skills | 2 |
| Knowledge ingestion with job polling | 3 |
| Semantic search for domain grounding | 4 |
| Installed-skill execution grounded in the KB | 5, 6 |

## Cleanup

```bash
dsagt rm genesis-skills -y
rm catalog_demo_data.tar.gz
```

The shared catalog cache is stored at `~/dsagt-projects/.skill_sources/` and is
reused across projects; delete it to force a fresh clone.
