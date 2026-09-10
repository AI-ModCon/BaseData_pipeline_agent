"""TraceCollector — the driver: read → translate → hand to consumers.

The MCP-server heartbeat's engine, and the piece a downstream application
embeds: :func:`make_trace_collector` wires an agent's (reader, translator)
pair to the MLflow sink (plus any extra consumers), and
:class:`TraceCollector` runs the pass with per-consumer ack sets so repeated
passes are idempotent.
"""

from __future__ import annotations

import fcntl
import json
import logging
import threading
from contextlib import contextmanager
from pathlib import Path

from dsagt.traces.readers import (
    ClaudeReader,
    ClineReader,
    CodexReader,
    GooseReader,
    OpenCodeReader,
)
from dsagt.traces.sink import MLflowSink
from dsagt.traces.translators import (
    ClaudeTranslator,
    ClineTranslator,
    CodexTranslator,
    GooseTranslator,
    OpenCodeTranslator,
)

logger = logging.getLogger(__name__)

# An agent appears here once both its reader and translator exist; the collector
# runs for any agent in the table and is simply absent for the rest.
_PIPELINES = {
    "claude": lambda pd, pr, sr: (
        ClaudeReader(pd, projects_root=pr),
        ClaudeTranslator(),
    ),
    "codex": lambda pd, pr, sr: (CodexReader(pd, sessions_root=sr), CodexTranslator()),
    "goose": lambda pd, pr, sr: (GooseReader(pd), GooseTranslator()),
    "opencode": lambda pd, pr, sr: (OpenCodeReader(pd), OpenCodeTranslator()),
    "cline": lambda pd, pr, sr: (ClineReader(pd, sessions_root=sr), ClineTranslator()),
}


def make_trace_collector(
    agent,
    project_dir,
    project,
    session_id,
    tracking_uri,
    *,
    projects_root: Path | None = None,
    sessions_root: Path | None = None,
    extra_consumers: list | None = None,
    source=None,
    ack_dir: str | Path = ".dsagt",
) -> "TraceCollector | None":
    """Build the collector for ``agent``, or ``None`` if no pipeline is registered.

    The MLflow logger is always the first consumer (observability is universal);
    ``extra_consumers`` (e.g. a :class:`~dsagt.memory.MemoryExtractor` when
    episodic memory is enabled) are appended, each acking independently.

    ``source`` pins the reader to a specific session (the startup catch-up passes
    the *previous* session's recorded :meth:`Reader.active_source` token), so it
    re-reads that exact session instead of whatever is newest now — uniformly
    across all agents (transcript path, DB session id, or session-dir name).

    ``sessions_root`` overrides where the codex/cline reader looks for session
    transcripts (each reader documents its own default) — a downstream
    application watching a session someone started by hand passes the agent's
    global sessions dir (e.g. ``~/.codex/sessions``).  ``projects_root`` is the
    claude equivalent.  Both are ignored for agents whose reader has no such
    root.

    ``ack_dir`` is where the per-consumer ack files land, resolved against
    ``project_dir`` (an absolute path is used as-is) — a downstream application
    keeps trace state beside its own (e.g. ``.nmstudio``); dsagt's is ``.dsagt``.
    """
    builder = _PIPELINES.get(agent)
    if builder is None:
        return None
    reader, translator = builder(project_dir, projects_root, sessions_root)
    if source is not None:
        reader.pin(source)
    consumers = [MLflowSink(tracking_uri, project), *(extra_consumers or [])]
    return TraceCollector(
        reader,
        translator,
        project=project,
        session_id=session_id,
        project_dir=project_dir,
        consumers=consumers,
        ack_dir=ack_dir,
    )


class TraceCollector:
    """Periodically read the session, translate it, and hand it to consumers.

    A *consumer* is anything with a ``name`` and a ``write(trace)`` — the MLflow
    logger and the memory indexer both qualify (no shared base needed).  Each
    consumer keeps its own ack set (``<ack_dir>/trace_acks_<name>.json``), keyed
    by session-qualified turn id (``<session_id>:<span_id>``) so the
    per-transcript ``turn-N`` indices can't collide across sessions in the
    shared file.  A re-pass or an N+1 catch-up can only waste work, never
    double-log or lose a turn, and a failing consumer holds back only its own
    mark.

    Completeness watermark: a periodic pass emits only *completed* turns (all but
    the still-open last one); the deferred final turn flushes when a later prompt
    bounds it or at end-of-session (``include_last=True``).  An OS file lock
    serializes overlapping passes against the shared ack files.
    """

    def __init__(
        self,
        reader,
        translator,
        *,
        project,
        session_id,
        project_dir,
        consumers,
        ack_dir: str | Path = ".dsagt",
    ):
        self._reader = reader
        self._translator = translator
        self._project = project
        self._session_id = session_id
        self._project_dir = Path(project_dir)
        self._consumers = list(consumers)
        # pathlib join: an absolute ack_dir stands alone, a relative one nests
        # under project_dir.
        self._ack_dir = self._project_dir / ack_dir
        self._lock = threading.Lock()

    def active_source(self):
        """The reader's session token (see :meth:`Reader.active_source`), or
        ``None``.  Recorded in ``state.yaml`` so the next session's catch-up can
        pin this exact session — uniform across all agents.
        """
        try:
            return self._reader.active_source()
        except Exception:  # noqa: BLE001 — best-effort; never break the heartbeat
            return None

    def _acks_path(self, name: str) -> Path:
        return self._ack_dir / f"trace_acks_{name}.json"

    def _load_acks(self, name: str) -> set[str]:
        try:
            return set(json.loads(self._acks_path(name).read_text()))
        except FileNotFoundError:
            return set()

    def _save_acks(self, name: str, acks: set[str]) -> None:
        self._ack_dir.mkdir(parents=True, exist_ok=True)
        self._acks_path(name).write_text(json.dumps(sorted(acks)))

    @contextmanager
    def _lock_file(self):
        self._ack_dir.mkdir(parents=True, exist_ok=True)
        with open(self._ack_dir / "trace_acks.lock", "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def collect(self, *, include_last: bool = False) -> int:
        """Read → translate → hand completed turns to each consumer.

        Returns the number of turns newly delivered to at least one consumer.
        ``include_last=True`` (end-of-session flush / per-turn hook) also emits
        the otherwise-deferred final turn.  Blocking — call via
        ``asyncio.to_thread`` from the event loop.
        """
        with self._lock, self._lock_file():
            records = self._reader.read()
            if not records:
                return 0
            trace = self._translator.translate(
                records,
                trace_id=self._session_id,
                session_id=self._session_id,
                project=self._project,
            )
            if trace is None:
                return 0

            roots = trace.roots()
            candidates = roots if include_last else roots[:-1]
            # Ack keys are session-qualified.  span_id is a per-transcript record
            # index ("turn-N"), so the same ids recur in every session's
            # transcript; a bare span_id would collide across sessions in the
            # shared, never-reset ack file and suppress every turn after the
            # first session.  Qualifying by session id matches the key MLflowSink
            # already uses for its own idempotency (``{trace_id}:{span_id}``).
            key_by_span = {
                r["span_id"]: f"{self._session_id}:{r['span_id']}" for r in candidates
            }
            if not key_by_span:
                return 0

            emitted: set[str] = set()
            for consumer in self._consumers:
                acks = self._load_acks(consumer.name)
                emit_ids = {s for s, key in key_by_span.items() if key not in acks}
                if not emit_ids:
                    continue
                try:
                    consumer.write(trace.subset(emit_ids))
                    # Ack within the same per-consumer try as the write, so a
                    # failure is isolated to this consumer and turns already
                    # written can't re-emit as duplicates on the next pass.
                    self._save_acks(
                        consumer.name, acks | {key_by_span[s] for s in emit_ids}
                    )
                except Exception as e:  # noqa: BLE001 — per-consumer isolation
                    logger.warning("Trace consumer %r failed: %s", consumer.name, e)
                    continue
                emitted |= emit_ids
            return len(emitted)
