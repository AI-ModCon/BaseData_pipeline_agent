"""
Trace pipeline — read each agent's on-disk session, normalize it to one common
``Trace``, and hand that to whatever consumes traces (the MLflow sink here, the
episodic-memory indexer in :mod:`dsagt.memory`).

While a session runs, the MCP server wakes on a timer and, for the running agent:
a **Reader** finds and reads the platform's session files on disk into raw
records; the matching **Translator** maps those records into one **Trace**; and
the **TraceCollector** hands the result to its consumers, skipping the turns it
already handled.

One module per stage: :mod:`~dsagt.traces.trace` (the canonical form),
:mod:`~dsagt.traces.readers`, :mod:`~dsagt.traces.translators`,
:mod:`~dsagt.traces.collector`, :mod:`~dsagt.traces.sink` (the MLflow
consumer).  Everything here imports only the standard library at module scope;
mlflow loads lazily on the sink's first ``write``, which needs
``dsagt[traces]``.

Class map — ``▷`` inherits · ``◆`` owns · ``◇`` holds  (``*`` = many)::

    Trace                       one session: id fields + spans (list of dicts)
                                + compose / query / to_exchanges methods

    Reader  «abstract»          locate + read a platform's session → raw records
    ├─▷ JsonlReader «abstract»    shared whole-file line framing; active_file() hook
    │     ├─▷ ClaudeReader        ~/.claude/projects/<cwd>/*.jsonl (newest)
    │     └─▷ CodexReader         ~/.codex/sessions/**/rollout-*.jsonl (by cwd)
    ├─▷ GooseReader              goose sessions.db        (sqlite, read-only)
    ├─▷ OpenCodeReader           opencode.db              (sqlite, read-only)
    └─▷ ClineReader              ~/.cline/.../<id>.messages.json (whole file)

    Translator  «abstract»      raw records → Trace (pure); shared turn template
    ├─▷ ClaudeTranslator         overrides translate() — bespoke grammar
    ├─▷ CodexTranslator          fills parse hooks (+ normalize / prompt-index)
    ├─▷ GooseTranslator          fills parse hooks
    ├─▷ OpenCodeTranslator       fills parse hooks
    └─▷ ClineTranslator          fills parse hooks

    TraceCollector              the driver: read → translate → hand to consumers
                                (MLflow sink, memory indexer); a per-consumer
                                ack set makes repeated passes idempotent

    MLflowSink                  consumer: Trace → backdated spans in the store
"""

from dsagt.traces.collector import TraceCollector, make_trace_collector
from dsagt.traces.readers import (
    ClaudeReader,
    ClineReader,
    CodexReader,
    GooseReader,
    JsonlReader,
    OpenCodeReader,
    Reader,
    _transcript_dir,
)
from dsagt.traces.sink import MLflowSink
from dsagt.traces.trace import Trace
from dsagt.traces.translators import (
    ClaudeTranslator,
    ClineTranslator,
    CodexTranslator,
    GooseTranslator,
    OpenCodeTranslator,
    Translator,
)

__all__ = [
    "Trace",
    "Reader",
    "JsonlReader",
    "ClaudeReader",
    "CodexReader",
    "GooseReader",
    "OpenCodeReader",
    "ClineReader",
    "Translator",
    "ClaudeTranslator",
    "CodexTranslator",
    "GooseTranslator",
    "OpenCodeTranslator",
    "ClineTranslator",
    "TraceCollector",
    "make_trace_collector",
    "MLflowSink",
    "_transcript_dir",
]
