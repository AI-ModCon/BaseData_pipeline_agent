---
title: VASP DFT → AI-Ready Records
domain: Materials science — VASP DFT output to AI-ready records, via catalog skills and a registered code
summary: >-
  Convert VASP DFT output into AI-ready records two ways — the agent
  discovers, installs, and authors pymatgen-based skills to convert a small
  slab calculation, then registers a NEB converter as a code and runs it with
  provenance against a five-image NEB fixture (no DFT run, no HPC).
status: published
order: 30
---

# DSAgt Demo: VASP DFT → AI-Ready Records

> **Estimated time:** ~25 minutes — the fixture data is a few MB, so the only
> real costs are a one-time `pip install pymatgen` and a shallow clone of the
> K-Dense catalog from GitHub. No DFT run, no HPC.

**Goal:** turn VASP calculations into AI-ready records in the
[ISAAC record schema](https://github.com/ISAAC-DOE/isaac-ai-ready-record)
through both of DSAgt's extension mechanisms:

1. **Skills.** The agent discovers the external skill sources, syncs the K-Dense
   catalog, installs its `pymatgen` skill, and uses the built-in `skill-creator`
   to author a `vasp-to-isaac` skill whose converter parses VASP output with
   `pymatgen.io.vasp`. It runs that skill on a small slab calculation.
2. **Codes.** The agent registers the [`vasp_neb_to_isaac.py`](vasp_neb_to_isaac.py)
   converter as a code and runs it through `dsagt-run` on a five-image
   nudged-elastic-band (NEB) calculation, so the execution is captured in
   `trace_archive/` and can be reconstructed.

Both parts use real `pymatgen.io.vasp` parsing. The slab data is a mock: valid
VASP format with the OUTCAR reduced to the lines pymatgen reads. The NEB data is
a fixture from the pymatgen test suite. The reference outputs
(`expected_isaac_record.json` for the slab, [`isaac_neb_record.json`](isaac_neb_record.json)
for the NEB) let you check the agent's results.

## Prerequisites

- DSAgt installed (`uv sync --all-groups`) and an agent platform installed and
  **already authenticated** (BYOA — dsagt writes no credentials; the default
  local embedder needs no API key).
- `pymatgen` importable in the environment `dsagt` runs in
  (`uv pip install pymatgen`) — both converters use `pymatgen.io.vasp`.
- Git, for the catalog clone.

## Setup

```bash
uv pip install pymatgen                 # the converters' one real dependency
dsagt init
```

At the menu, name the project `isaac-vasp`, pick your agent, and **uncheck every
skill source** at the skill-sources checkbox, so the project starts with no external
catalog synced — the walkthrough has the agent discover, sync, and search one from
inside the session. Then:

```bash
PROJ=~/dsagt-projects/isaac-vasp
mkdir -p "$PROJ/data"
# Demo data from the DSAgt use-case data folder
# (https://drive.google.com/drive/folders/1RWQAJeHaikIaD7CCf8ciJ71m55S1erp6):
# the NEB fixture, then the mock slab and its expected record.
curl -L "https://drive.usercontent.google.com/download?id=1uH0r7ryF9nUJaE1fxXZMAzBjiE4TXxWu&export=download&confirm=t" -o neb_fixture.tar.gz
tar xzf neb_fixture.tar.gz -C "$PROJ/data" --strip-components=1 isaac_vasp/neb
curl -L "https://drive.usercontent.google.com/download?id=19PNObF-FZkGITNJ_VIZH8j9BHWSqRPrH&export=download&confirm=t" -o slab_fixture.tar.gz
tar xzf slab_fixture.tar.gz -C "$PROJ/data" --strip-components=2 isaac_skills_demo/mock_data
# $PROJ/data now holds neb/, mock_slab/, expected_isaac_record.json
mkdir -p "$PROJ/codes/scripts"
cp use_cases/vasp_dft/vasp_neb_to_isaac.py "$PROJ/codes/scripts/"
dsagt start isaac-vasp                        # mirrors the built-in skill-creator into the agent's native skills dir
```

## Execution

Paste each prompt into the agent, one at a time. The arc: **see what you have →
find more → sync a source → install the relevant skill → author a new one → run
it → then register a converter as a code and run it with provenance.**

### 1. Native skill discovery

```text
Do you have a skill available for scaffolding new skills? Name it and give me a one-line summary of what it does.
```

**Expect:** the agent names **`skill-creator`** and summarizes it — discovered
natively, with no MCP call. `dsagt start` mirrored the built-in skill into the
agent's native skills directory, so the agent sees its name and description like
any native skill and loads the full `SKILL.md` only when it is invoked.
`search_skills` is for the not-yet-installed catalog only, so it should not fire here.

### 2. List the skill sources

```text
Where can I get more skills from? List the skill sources you can pull from and which are already synced.
```

**Expect:** `list_skill_sources` → the known sources (`k-dense-ai`, `anthropic`,
`antigravity`, `composio`, `genesis`) with URLs, each flagged available but not
synced.

### 3. Sync a source

```text
Sync the "k-dense-ai" source so we can search its catalog.
```

**Expect:** `add_skill_source(source="k-dense-ai")` → a shallow clone of K-Dense
`scientific-agent-skills`, its skills indexed into
`skills_catalog__k-dense-ai-scientific-agent-skills`, source persisted to
`.dsagt/config.yaml`. The catalog is searchable immediately — no restart.

### 4. Install the relevant skill

```text
Search the catalog for a skill that helps parse VASP output with pymatgen, then install the most relevant one into this project.
```

**Expect:** `search_skills` (catalog hits tagged `[catalog · install_skill to add]`,
`pymatgen` at or near the top) → `install_skill(skill_name="pymatgen")`. The installed
skill carries the reference docs (`pymatgen.io.vasp.Incar` / `Poscar` / `Outcar`)
the converter uses next. **Verify** it landed:

```bash
ls "$PROJ/skills/"
```

### 5. Author the converter skill with skill-creator

```text
Use the skill-creator skill to author a new project skill named "vasp-to-isaac". Following the pymatgen skill you just installed, its converter should use `pymatgen.io.vasp` — `Incar.from_file` (ENCUT, NSW, ISPIN, LDAUU), `Poscar.from_file` (formula, atom counts), and `Outcar` (final energy, energy(sigma->0), total magnetization, max force) — to read a VASP slab calc directory and emit an ISAAC-style JSON record. The mock has no vasprun.xml, so take energy/forces from the OUTCAR. Target the shape in data/expected_isaac_record.json. Save it with save_skill.
```

**Expect:** the agent reads `skill-creator`'s template and the `pymatgen` skill's IO
docs, then `save_skill` writes `<project>/skills/vasp-to-isaac/` whose script
imports `pymatgen.io.vasp` (not a hand-rolled regex parser).

### 6. Run the skill on the slab calculation

```text
Invoke the vasp-to-isaac skill on data/mock_slab/ and write the result to audit/mock_slab_isaac.json. Then diff its structure and values against data/expected_isaac_record.json and report any differences.
```

**Expect:** pymatgen parses the mock directory and the agent writes
`audit/mock_slab_isaac.json` with the key fields pymatgen extracted — final
energy ≈ -132.8421 eV (`Outcar.final_energy`), 12 atoms (`Poscar`), ENCUT 520 /
NSW 50 (`Incar`), total mag ≈ 8.0123 (`Outcar.total_mag`) — matching the reference.

### 7. Register the NEB converter as a code

```text
Register a code named vasp-neb-to-isaac. Its executable is
`python codes/scripts/vasp_neb_to_isaac.py`, which takes a positional NEB
directory argument (containing 00/, 01/, ... image subdirs) and an optional
`--output` path. Run it with `--help` first to confirm the interface, then save
the code spec with the positional `neb_dir` and the `--output` option.
```

**Verify:** `Search the registry for the vasp-neb-to-isaac code.` →
`$PROJ/codes/vasp-neb-to-isaac/SKILL.md` should exist.

### 8. Run the conversion through dsagt-run

```text
Using the registered vasp-neb-to-isaac code, convert the NEB calculation in
data/neb/ and write the ISAAC record to data/isaac_neb_record.json. Use the
exact dsagt-run command from the spec so the execution is recorded. Then tell me
the record's reaction-energy / barrier fields and how many images it summarized.
```

**Expect:** the agent runs `dsagt-run --code vasp-neb-to-isaac -- python
codes/scripts/vasp_neb_to_isaac.py data/neb/ --output data/isaac_neb_record.json`,
pymatgen parses the five OUTCARs, and a v1.05 ISAAC record lands with the
`computation` / `measurement` blocks populated (5 NEB images). Compare against the
reference [`isaac_neb_record.json`](isaac_neb_record.json) in this folder.

### 9. Reconstruct the pipeline

```text
Reconstruct the pipeline from the execution records as a bash script.
```

## Post-Conditions

Confirm from a shell (the native skills directory is `.claude/skills/` for Claude Code,
`.agents/skills/` for Codex, Goose, and opencode, `.cline/skills/` for Cline):

```bash
dsagt info isaac-vasp                     # KB shows the k-dense-ai catalog collection
ls "$PROJ/skills/"                        # pymatgen  vasp-to-isaac
ls "$PROJ/codes/"                         # vasp-neb-to-isaac
ls "$PROJ/audit/" "$PROJ/trace_archive/"
```

1. The KB holds the `skills_catalog__k-dense-ai-scientific-agent-skills`
   collection, synced in-session by the agent (step 3), searchable via
   `search_skills` but absent from the agent's context.
2. The `pymatgen` catalog skill is installed into `<project>/skills/` and
   mirrored into the agent's native skills directory.
3. A `vasp-to-isaac` skill, authored via `skill-creator` and parsing with
   `pymatgen.io.vasp`, exists and is natively discoverable.
4. `audit/mock_slab_isaac.json` was produced from the mock slab directory and
   matches the ISAAC shape and values.
5. Code registry contains the `vasp-neb-to-isaac` spec (`codes/vasp-neb-to-isaac/SKILL.md`).
6. `data/isaac_neb_record.json` is a valid ISAAC v1.05 record matching the shape
   of the reference, and `trace_archive/` holds the conversion's provenance record.
7. A reconstructed pipeline script replays the conversion.
8. MLflow traces (in the serverless `mlflow.db` store) capture the session —
   `mlflow ui --backend-store-uri sqlite:///$PROJ/mlflow.db`.

## What This Tests

| DSAgt Capability | Steps |
|------------------|-------|
| Native discovery of the built-in `skill-creator` | 1 |
| Skill-source listing and in-session sync (`list_skill_sources`, `add_skill_source`) | 2, 3 |
| Catalog search and install (`search_skills`, `install_skill`) | 4 |
| Skill authoring with `skill-creator` and `save_skill` | 5 |
| Installed-skill execution | 6 |
| Code registration (`save_code_spec`) and registry search | 7 |
| Code execution with provenance through `dsagt-run` | 8 |
| Pipeline reconstruction | 9 |

## Cleanup

```bash
dsagt rm isaac-vasp -y
rm neb_fixture.tar.gz slab_fixture.tar.gz
```

The shared catalog cache is stored at `~/dsagt-projects/.skill_sources/` and is
reused across projects; delete it to force a fresh clone.

## Notes

- `mock_slab/` is not real DFT output, but it is valid VASP format: the
  INCAR/POSCAR parse cleanly, and the OUTCAR keeps exactly the lines pymatgen's
  `Outcar` reads (TOTEN, `energy(sigma->0)`, magnetization, the force block) while
  omitting the SCF/eigenvalue blocks. There is no `vasprun.xml`, so the converter
  takes energy/forces from the OUTCAR.
- The `neb/` OUTCARs are public pymatgen test fixtures.
- With the default local embedder (`bge-small`), absolute `search_skills` scores
  are low because short queries under-score long SKILL.md text — the ranking is
  still correct (`pymatgen` first). Set `embedding.backend: api` for sharper
  relevance. With no embedder at all, `search_skills` falls back to keyword
  scoring; `install_skill` and the native mirror are filesystem operations.
- The [`skills/vasp-to-isaac/`](skills/vasp-to-isaac/) skill in this folder is a
  broader slab/bulk converter that needs `vasprun.xml`-bearing slab or bulk data.
  It is a reference for what the agent-authored skill in step 5 can grow into,
  not something this demo's data exercises.
- Sister demo: [`skill_catalog_curation`](../skill_catalog_curation/) exercises the same catalog →
  install → native loop plus KB domain ingest and datacard generation, against
  the `genesis` (OSTI GitLab) source.
