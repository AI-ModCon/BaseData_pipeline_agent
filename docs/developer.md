# Developer Guide

How the DSAgt codebase is set up and how to work in it. For contribution
mechanics (branch/PR flow, commit style), see
[CONTRIBUTING.md](https://github.com/AI-ModCon/dsagt/blob/main/.github/CONTRIBUTING.md).

## Setup

DSAgt develops on [uv](https://github.com/astral-sh/uv) with Python 3.12 or 3.13:

```bash
git clone https://github.com/AI-ModCon/dsagt.git
cd dsagt
uv sync --all-groups --all-extras   # runtime + all extras + dev + docs dependencies
source .venv/bin/activate           # so dsagt / dsagt-run / dsagt-server are on PATH
```

## Tests

Use `python -m pytest`, not bare `pytest` (the bare binary can resolve the wrong
interpreter):

```bash
uv run --no-sync python -m pytest -m "not integration" -q   # unit suite
uv run --no-sync python -m pytest tests/test_config.py -q   # a single file
uv run --no-sync python -m pytest -m integration -v         # integration (needs creds)
```

Integration tests hit real embedding/LLM providers and need `EMBEDDING_*` /
`LLM_*` credentials in the environment; they're excluded from CI and the default
local run.

## Lint & format

CI enforces both on `src/` and `tests/` (scientific scripts under `use_cases/`
are exempt):

```bash
uv run ruff check src tests
uv run black src tests          # omit the paths to format everything you touched
```

## Docs

The site is MkDocs (Material). `mkdocs.yml` at the repo root is the site config;
`docs/` holds the pages. The `.github/workflows/docs.yml` workflow builds the
site with `--strict` on every PR and deploys it to GitHub Pages from `main`.

```bash
uv run mkdocs serve             # live preview at http://127.0.0.1:8000
uv run mkdocs build --strict    # what CI runs
```

## Using dsagt as a dependency

dsagt's parts install piecewise: the core distribution depends only on
`pyyaml`, `httpx`, `jsonschema`, and `mcp`, and each concern's heavy
dependencies sit behind an extra. A downstream project declares the one it
uses:

```toml
dependencies = ["dsagt[traces]>=0.2"]
```

| Extra | Adds | Enables |
|-------|------|---------|
| `traces` | mlflow | the trace pipeline's MLflow sink |
| `kb` | chromadb, sentence-transformers, llama-index, numpy, rank-bm25, … | the knowledge base |
| `cli` | questionary | the interactive `dsagt init` menus |
| `all` | all of the above | running dsagt itself (`dsagt init`, the MCP server, the CLI) |

The import paths match the extras, and every subpackage imports on a core-only
install (a lazy import that needs a missing extra raises `ImportError` naming
it):

```python
from dsagt.traces import make_trace_collector, MLflowSink   # dsagt[traces]
from dsagt.knowledge import KnowledgeBase                    # dsagt[kb]
from dsagt.skills import SkillsCatalog, install_into_project # core only
```

The trace pipeline's embedding points:

- `make_trace_collector(agent, project_dir, project, session_id, tracking_uri)`
  — `project` is the MLflow experiment name and `tracking_uri` the store
  (dsagt's own is `sqlite:///<project_dir>/mlflow.db`).
- `ack_dir=` (default `.dsagt`, resolved against `project_dir`) — where the
  per-consumer ack files land, so an application keeps trace state beside its
  own state directory.
- Every trace the sink writes carries `dsagt.agent` (the agent platform) and
  `dsagt.trace_id` (the per-turn idempotency key) in its metadata —
  attribution in the store itself.

The `import-leaf` CI job installs the core with no extras and imports every
subpackage, then installs each extra alone and imports its concern — the
guarantee these import paths rely on.

## Codebase orientation

The [Architecture](architecture.md) page is the map of the system — the
capabilities, the single `dsagt-server` MCP layout, and the observability and
memory design. `CLAUDE.md` at the repo root records the house coding and prose
conventions (it doubles as instructions for AI coding agents working in the
repo); read it before a substantial change.

## Troubleshooting

**Agent command not found.** The agent CLI isn't installed or isn't on PATH —
see the [supported agents](index.md#supported-agents).

**MCP server not connecting.** Confirm the entry point resolves:

```bash
uv run which dsagt-server
```

If it's missing, reinstall:
`pip install --force-reinstall "dsagt[all] @ git+https://github.com/AI-ModCon/dsagt.git"`.
