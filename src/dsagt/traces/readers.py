"""Readers — locate and read a platform's on-disk session into raw records.

Each reader resolves *the latest session for this project* on its platform's
own storage (JSONL transcripts for claude/codex, SQLite for goose/opencode, a
per-session directory for cline) and reads the whole session's records.  The
matching translator (:mod:`dsagt.traces.translators`) turns those records into
a :class:`~dsagt.traces.trace.Trace`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class Reader(ABC):
    """Find this project's active session for an agent and read its records.

    Each reader resolves *the latest session for this project* and reads it.  A
    reader can also be pinned (:meth:`pin`) to a specific session — the startup
    catch-up does this to re-read the *previous* session rather than whatever is
    newest now.  :meth:`active_source` returns an opaque, agent-shaped token for
    the session being read — a transcript path (claude/codex), a DB session id
    (goose/opencode), or a session-dir name (cline) — which the server records
    in ``state.yaml`` so the next session's catch-up can pin it back.  The token
    round-trips through YAML, so its native type (str/int) is preserved.
    """

    agent: str
    _pinned = None

    def pin(self, source) -> None:
        """Pin to a specific session token (as returned by :meth:`active_source`)."""
        self._pinned = source

    def active_source(self):
        """Token identifying the session being read, or ``None`` if none.

        Subclasses override to resolve the latest session when unpinned; the
        base returns the pinned token (``None`` when neither pinned nor
        overridden).
        """
        return self._pinned

    @abstractmethod
    def read(self) -> list[dict]:
        """The whole active session's raw records (re-read each pass; the
        collector's ack set dedupes, so reads need not be incremental)."""


class JsonlReader(Reader):
    """Read the whole active ``*.jsonl`` file, framing only complete lines.

    A trailing half-written line is dropped (picked up next pass).  Subclasses
    supply :meth:`active_file`; the framing is identical for claude and codex.
    A pinned reader reads that exact file instead of the newest.
    """

    @abstractmethod
    def active_file(self) -> Path | None: ...

    def _file(self) -> Path | None:
        if self._pinned is not None:
            p = Path(self._pinned)
            return p if p.is_file() else None
        return self.active_file()

    def active_source(self) -> str | None:
        f = self._file()
        return str(f) if f else None

    def read(self) -> list[dict]:
        f = self._file()
        if f is None:
            return []
        with open(f, "rb") as fh:
            chunk = fh.read()
        last_nl = chunk.rfind(b"\n")
        if last_nl == -1:
            return []
        out: list[dict] = []
        for line in chunk[: last_nl + 1].splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # One corrupt complete line must not drop the whole session's
                # transcript — it persists on disk and would re-fail every
                # heartbeat.  Skip it, as we already skip the trailing partial.
                logger.warning("skipping unparseable transcript line in %s", f)
        return out


def _transcript_dir(project_dir: str | Path, projects_root: Path | None = None) -> Path:
    """``~/.claude/projects/<mangled-cwd>`` for a project directory.

    Claude derives the dir name by replacing every non-alphanumeric character of
    the launch cwd with ``-``.  The MCP server launches as ``cd <project_dir> &&
    claude``, so cwd == project_dir.
    """
    root = projects_root or (Path.home() / ".claude" / "projects")
    mangled = re.sub(r"[^a-zA-Z0-9]", "-", os.path.abspath(project_dir))
    return root / mangled


class ClaudeReader(JsonlReader):
    """The most-recently-modified transcript in the project's ``~/.claude`` dir."""

    agent = "claude"

    def __init__(self, project_dir, *, projects_root: Path | None = None):
        self._dir = _transcript_dir(project_dir, projects_root)

    def active_file(self) -> Path | None:
        if not self._dir.is_dir():
            return None
        files = list(self._dir.glob("*.jsonl"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None


class CodexReader(JsonlReader):
    """The newest ``rollout-*.jsonl`` whose ``session_meta.cwd`` is this project.

    DSAGT always runs codex with ``CODEX_HOME=<project>/.codex-data`` (its MCP
    config lives there — see agents/codex.py), so rollouts land under
    ``<project>/.codex-data/sessions/YYYY/MM/DD/``, not the global
    ``~/.codex/sessions/``.  Each rollout opens with a ``session_meta`` record
    carrying the launch ``cwd``; the filter guards against stray files.
    """

    agent = "codex"

    def __init__(self, project_dir, *, sessions_root: Path | None = None):
        self._project_dir = os.path.abspath(project_dir)
        self._root = (
            Path(sessions_root)
            if sessions_root
            else Path(self._project_dir) / ".codex-data" / "sessions"
        )

    def _rollout_cwd(self, path: Path) -> str | None:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline()
        if not first.strip():
            return None
        try:
            rec = json.loads(first)
        except json.JSONDecodeError:
            # A corrupt newest rollout must not abort discovery of the valid
            # project rollout behind it — treat it as non-matching and move on.
            logger.warning("skipping unparseable rollout header %s", path)
            return None
        if rec.get("type") != "session_meta":
            return None
        return (rec.get("payload") or {}).get("cwd")

    def active_file(self) -> Path | None:
        if not self._root.is_dir():
            return None
        files = sorted(
            self._root.glob("**/rollout-*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in files:
            if self._rollout_cwd(f) == self._project_dir:
                return f
        return None


_GOOSE_DB = Path.home() / ".local" / "share" / "goose" / "sessions" / "sessions.db"


class GooseReader(Reader):
    """Read the project's active Goose session from its SQLite store (read-only)."""

    agent = "goose"

    def __init__(self, project_dir, *, db_path: Path | None = None):
        self._project_dir = os.path.abspath(project_dir)
        self._db = Path(db_path) if db_path else _GOOSE_DB

    def _latest_session(self, con):
        row = con.execute(
            "SELECT id FROM sessions WHERE working_dir = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (self._project_dir,),
        ).fetchone()
        return row[0] if row else None

    def active_source(self):
        if self._pinned is not None:
            return self._pinned
        if not self._db.exists():
            return None
        con = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
        try:
            return self._latest_session(con)
        finally:
            con.close()

    def read(self) -> list[dict]:
        if not self._db.exists():
            return []
        con = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
        try:
            sid = (
                self._pinned if self._pinned is not None else self._latest_session(con)
            )
            if sid is None:
                return []
            return [
                {"role": role, "content": _loads_list(cj), "ts": ts}
                for role, cj, ts in con.execute(
                    "SELECT role, content_json, created_timestamp FROM messages "
                    "WHERE session_id = ? ORDER BY id",
                    (sid,),
                )
            ]
        finally:
            con.close()


_OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


class OpenCodeReader(Reader):
    """Read + flatten the project's active opencode session (sqlite, read-only).

    opencode splits a session into ``message`` rows (role/model) and ``part``
    rows (the text/tool payloads); this joins them into one time-ordered list of
    parts, each tagged with its message's role + model and a timestamp in
    seconds (opencode stores milliseconds).
    """

    agent = "opencode"

    def __init__(self, project_dir, *, db_path: Path | None = None):
        self._project_dir = os.path.abspath(project_dir)
        self._db = Path(db_path) if db_path else _OPENCODE_DB

    def _latest_session(self, con):
        row = con.execute(
            "SELECT id FROM session WHERE directory = ? "
            "ORDER BY time_updated DESC LIMIT 1",
            (self._project_dir,),
        ).fetchone()
        return row[0] if row else None

    def active_source(self):
        if self._pinned is not None:
            return self._pinned
        if not self._db.exists():
            return None
        con = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
        try:
            return self._latest_session(con)
        finally:
            con.close()

    def read(self) -> list[dict]:
        if not self._db.exists():
            return []
        con = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
        try:
            sid = (
                self._pinned if self._pinned is not None else self._latest_session(con)
            )
            if sid is None:
                return []
            messages = {
                mid: _loads_dict(d)
                for mid, d in con.execute(
                    "SELECT id, data FROM message WHERE session_id = ?", (sid,)
                )
            }
            parts = []
            for mid, t_created, data in con.execute(
                "SELECT message_id, time_created, data FROM part "
                "WHERE session_id = ? ORDER BY time_created",
                (sid,),
            ):
                m = messages.get(mid, {})
                parts.append(
                    {
                        "role": m.get("role"),
                        "model": (m.get("model") or {}).get("modelID"),
                        # time_created is NULL for an unfinalized streaming part;
                        # guard the ms->s divide (mirrors ClineTranslator._ts).
                        "ts": (
                            t_created / 1000.0
                            if isinstance(t_created, (int, float))
                            else None
                        ),
                        "data": _loads_dict(data),
                    }
                )
            return parts
        finally:
            con.close()


_CLINE_SESSIONS_ROOT = Path.home() / ".cline" / "data" / "sessions"


class ClineReader(Reader):
    """Locate the project's active Cline CLI session by its metadata ``cwd``.

    Each session is ``~/.cline/data/sessions/<id>/`` with ``<id>.json`` (metadata
    incl. ``cwd`` + ``model``) and ``<id>.messages.json`` (the whole message list).
    """

    agent = "cline"

    def __init__(self, project_dir, *, sessions_root: Path | None = None):
        self._project_dir = os.path.abspath(project_dir)
        self._root = Path(sessions_root) if sessions_root else _CLINE_SESSIONS_ROOT

    def _active_dir(self) -> Path | None:
        if not self._root.is_dir():
            return None
        for d in sorted(self._root.iterdir(), key=lambda p: p.name, reverse=True):
            meta = d / f"{d.name}.json"
            if not meta.exists():
                continue
            try:
                cwd = json.loads(meta.read_text()).get("cwd", "")
            except (json.JSONDecodeError, OSError):
                continue
            if os.path.abspath(cwd) == self._project_dir:
                return d
        return None

    def _dir(self) -> Path | None:
        if self._pinned is not None:
            d = self._root / str(self._pinned)
            return d if d.is_dir() else None
        return self._active_dir()

    def active_source(self) -> str | None:
        d = self._dir()
        return d.name if d else None

    def read(self) -> list[dict]:
        d = self._dir()
        if d is None:
            return []
        msgs_path = d / f"{d.name}.messages.json"
        if not msgs_path.exists():
            return []
        try:
            data = json.loads(msgs_path.read_text())
        except (json.JSONDecodeError, OSError):
            return []
        model = self._session_model(d)
        messages = data.get("messages", []) if isinstance(data, dict) else data
        for m in messages:
            m["model"] = model
        return messages

    def _session_model(self, session_dir: Path) -> str | None:
        try:
            meta = json.loads((session_dir / f"{session_dir.name}.json").read_text())
            return meta.get("model")
        except (json.JSONDecodeError, OSError):
            return None


def _loads_list(raw: str) -> list:
    try:
        out = json.loads(raw)
        return out if isinstance(out, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _loads_dict(raw: str) -> dict:
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
