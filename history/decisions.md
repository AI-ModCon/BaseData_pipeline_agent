# Decisions

Append-only, chronological. Nothing here describes present state.

## 2026-05-21 Provenance rides in the code command

Context: execution dispatched through MCP-server tools lost provenance whenever
the agent ran a code through its own shell tool, which it did routinely.
Decision: a registered code's `executable` string carries the wrapper
(`dsagt-run --code <name> -- <command>`), so any run of the spec's command is
recorded to `trace_archive/`, whichever path invokes it.
Rejected: a server-side `execute_code(name, params)` tool. The agent's shell is
always available, so no tool surface prevents the sidestep; only a wrapper in
the command itself makes the sidestep harmless. The residual risk is an agent
reconstructing the command from memory and dropping the wrapper; the
instructions require the spec's command verbatim, and provenance is asserted
from `trace_archive/` records, never from agent claims.
Consequence: `commands/run_code.py` and `provenance.run_and_record`; the
registry exposes no execute-by-name tool.
Commits: 56384d2

## 2026-09-10 The package holds no skills

Context: `src/dsagt/skills/` carried skill directories (`skill-creator`, the
`aidrin` gate code) alongside the catalog logic, and the `aidrin` catalog source
held one skill.
Decision: base skills are entries in `skills.BASE_SKILLS`; `dsagt init`
re-clones each from the repository that maintains it (`skill-creator` from the
genesis catalog's `skills/basedata-skills/`, `aidrin` from idtlab/AIDRIN
`.claude/skills` on `develop`) into `<project>/skills/`. The readiness gate
installs AIDRIN and instructs the agent to run the profile through the `aidrin`
skill's CLI, every call wrapped by `dsagt-run --code aidrin`.
Rejected: skill directories in the package. A skill maintained in two places
drifts in one of them; the genesis catalog is the BaseData team's home for
skills. Also rejected: AIDRIN as a catalog source, which held one skill.
Consequence: the `aidrin` source and the built-in gate code are gone; the gate
adds no code to a project.
Commits: fc5d60a, d97a6c3

## 2026-09-10 One README layout per use case, data hosted off-repo

Context: use cases mixed walkthrough files, README files, and committed data
samples in differing layouts.
Decision: each `use_cases/<name>/README.md` is the walkthrough, with
frontmatter (`title`, `domain`, `summary`, `status`, `order`) and the sections
Prerequisites, Setup, Execution (numbered pasted prompts with Verify/Expect),
Post-Conditions, What This Tests, Cleanup. Folders are laid out by role
(`docs/`, `scripts/`, `skills/`, `reference/`). Data is downloaded from the
shared Google Drive folder or the public upstream source. PyPI dependencies go
in the `use-cases` dependency group; conda-only tools and source builds are
installed by `scripts/setup_env.sh` into `~/dsagt-projects/.tools/<name>/`.
Rejected: data samples in the repository (size), and provisioning logic in
dsagt itself.
Consequence: `docs/use-cases/index.md` states the layout; `hooks/gen_use_cases.py`
publishes each README as a site page.
Commits: c72fbe0, 9f43d14

## 2026-09-10 dsagt is packaged with extras for downstream consumers

Context: three lab applications (PoLaR, MeDiCi, NeuroMANCER Studio) want the
trace pipeline, the knowledge base, or the skills catalog one at a time, and
`pip install dsagt` for the trace pipeline installed torch.
Decision: core dependencies are `pyyaml`, `httpx`, `jsonschema`, `mcp`; extras
`traces`, `kb`, `cli`, `all` match the concerns; subpackages are named after
the extras (`dsagt.traces`, `dsagt.knowledge`, `dsagt.skills`, ...), every
subpackage imports on a core-only install, a lazy import of a missing extra
raises `ImportError` naming it, and `pyproject.toml` declares ranges with
`uv.lock` as the team's environment. `make_trace_collector` takes `ack_dir` and
`sessions_root`; the MLflow sink carries cache token counts.
Rejected: a copy of the trace pipeline in agent-ui. A copy was started and
discarded; the code was already shaped for piecewise use, and duplicating it
splits one distribution into pieces that carry less weight than the whole.
Consequence: `docs/developer.md` "Using dsagt as a dependency"; the
`import-leaf` CI job. The design note is parked at
`history/parked/2026-09-11-design-notes/design-notes/downstream-packaging.md`.
Commits: 11966be

## 2026-09-11 Design notes retire to the log

Context: `design-notes/` held two untracked notes. The packaging note's changes
are built (entry above). The studio note recorded two gaps, `sessions_root` on
`make_trace_collector` and cache tokens in the sink, both closed in 11966be;
its one open idea, a person-operated interface over the same tools, is in
`DEVELOPMENT.md`.
Decision: the notes are parked and `design-notes/` is gone. Present
architecture is `DESIGN.md`; open work is `DEVELOPMENT.md`; decisions are here.
Rejected: keeping design notes as a fourth document class. A note that mixes
built mechanism, decisions, and open items drifts on all three.
Consequence: `history/parked/2026-09-11-design-notes/design-notes/`.
Commits: 11966be
