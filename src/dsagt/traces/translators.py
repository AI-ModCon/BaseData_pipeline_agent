"""Translators — one platform's raw records → a :class:`~dsagt.traces.trace.Trace`.

Pure functions of their input records, no I/O.  The shared ``translate``
template covers every platform but Claude: build a tool-result map, find the
turn-start (prompt) indices, and lower each turn's records into ordered
events that ``Trace.add_turn`` turns into a span subtree.  Claude overrides
``translate`` outright — its grammar exceeds this shape.

The Claude grammar is ported from MLflow's ``claude_code/tracing.py`` —
© Databricks, Inc., Apache-2.0 — specifically its turn-windowing,
skill/command skips, and next-timestamp span durations.  See NOTICE.
"""

from __future__ import annotations

import json
import re
from abc import ABC

from dsagt.traces.trace import (
    Trace,
    _DEFAULT_SPAN_SECONDS,
    _ROLE_ASSISTANT,
    _ROLE_USER,
    _TYPE_QUEUE_OP,
    _message,
    _parse_ts,
    _text_block,
    _tool_result_block,
    _tool_use_block,
    _usage,
)


class Translator(ABC):
    """Map one platform's records to a :class:`Trace`.

    The default ``translate`` is the shared template every platform but Claude
    uses: build a tool-result map, find the turn-start (prompt) indices, and for
    each turn lower its records into ordered ``("llm"|"tool", …)`` events that
    ``Trace.add_turn`` turns into a span subtree.  A subclass supplies the small
    parse hooks (``_is_prompt`` / ``_prompt_text`` / ``_ts`` / ``_events`` and,
    where needed, ``_tool_results`` / ``_normalize`` / ``_prompt_indices``).
    Claude overrides ``translate`` outright — its grammar exceeds this shape.
    """

    agent: str
    root_name: str

    def translate(self, records, *, trace_id, session_id, project) -> Trace | None:
        records = self._normalize(records)
        results = self._tool_results(records)
        prompts = self._prompt_indices(records)
        if not prompts:
            return None
        trace = Trace(trace_id, session_id, self.agent, project)
        bounds = prompts + [len(records)]
        for k, start in enumerate(prompts):
            self._build_turn(trace, records, start, bounds[k + 1], results)
        return trace if trace.spans else None

    def _build_turn(self, trace, records, start, end, results) -> None:
        root_ts = self._ts(records[start])
        last_ts = root_ts
        events = []
        for i in range(start + 1, end):
            rec = records[i]
            ts = self._ts(rec)
            if ts is not None:
                last_ts = ts
            events.extend(self._events(rec, ts, results))
        trace.add_turn(
            root_id=f"turn-{start}",
            root_name=self.root_name,
            prompt=self._prompt_text(records[start]),
            root_ts=root_ts,
            events=events,
            last_ts=last_ts,
        )

    # -- hooks (defaults; concrete translators fill what they need) ----------

    def _normalize(self, records):
        return records

    def _prompt_indices(self, records) -> list[int]:
        return [i for i, r in enumerate(records) if self._is_prompt(r)]

    def _tool_results(self, records) -> dict:
        return {}

    def _is_prompt(self, rec) -> bool:
        raise NotImplementedError

    def _prompt_text(self, rec) -> str:
        raise NotImplementedError

    def _ts(self, rec) -> float | None:
        raise NotImplementedError

    def _events(self, rec, ts, results) -> list:
        raise NotImplementedError


class GooseTranslator(Translator):
    """Goose message rows → Trace (content blocks: text / toolRequest / toolResponse)."""

    agent = "goose"
    root_name = "goose_conversation"

    @staticmethod
    def _blocks(msg) -> list[dict]:
        c = msg.get("content")
        return c if isinstance(c, list) else []

    def _is_prompt(self, rec) -> bool:
        return rec.get("role") == _ROLE_USER and any(
            b.get("type") == "text" for b in self._blocks(rec)
        )

    def _prompt_text(self, rec) -> str:
        return "".join(
            b.get("text", "") for b in self._blocks(rec) if b.get("type") == "text"
        )

    def _ts(self, rec) -> float | None:
        return _parse_ts(rec.get("ts"))

    def _tool_results(self, records) -> dict:
        results: dict = {}
        for msg in records:
            for b in self._blocks(msg):
                if b.get("type") == "toolResponse" and (tid := b.get("id")):
                    results[tid] = self._result_text(b)
        return results

    @staticmethod
    def _result_text(block) -> object:
        value = (block.get("toolResult") or {}).get("value") or {}
        content = value.get("content")
        if isinstance(content, list):
            return "".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )
        return content if content is not None else ""

    def _events(self, rec, ts, results) -> list:
        if rec.get("role") != _ROLE_ASSISTANT:
            return []
        out = []
        for b in self._blocks(rec):
            if b.get("type") == "text" and b.get("text", "").strip():
                out.append(("llm", ts, b["text"], None, None))
            elif b.get("type") == "toolRequest":
                call = (b.get("toolCall") or {}).get("value") or {}
                out.append(
                    (
                        "tool",
                        ts,
                        call.get("name", "unknown"),
                        call.get("arguments", {}),
                        results.get(b.get("id"), ""),
                    )
                )
        return out


class OpenCodeTranslator(Translator):
    """opencode flattened parts → Trace (call + result live in one tool part)."""

    agent = "opencode"
    root_name = "opencode_conversation"

    def _is_prompt(self, rec) -> bool:
        d = rec.get("data") or {}
        return (
            rec.get("role") == _ROLE_USER
            and d.get("type") == "text"
            and bool(d.get("text", "").strip())
        )

    def _prompt_text(self, rec) -> str:
        return (rec.get("data") or {}).get("text", "")

    def _ts(self, rec) -> float | None:
        return rec.get("ts")

    def _events(self, rec, ts, results) -> list:
        d = rec.get("data") or {}
        if (
            d.get("type") == "text"
            and rec.get("role") == _ROLE_ASSISTANT
            and d.get("text", "").strip()
        ):
            return [("llm", ts, d["text"], rec.get("model"), None)]
        if d.get("type") == "tool":
            state = d.get("state") or {}
            return [
                (
                    "tool",
                    ts,
                    d.get("tool", "unknown"),
                    state.get("input", {}),
                    state.get("output", ""),
                )
            ]
        return []


_CLINE_USER_INPUT_RE = re.compile(r"<user_input[^>]*>(.*?)</user_input>", re.DOTALL)


class ClineTranslator(Translator):
    """Cline message records → Trace (Anthropic block list; ms timestamps)."""

    agent = "cline"
    root_name = "cline_conversation"

    @staticmethod
    def _content(msg) -> list[dict]:
        c = msg.get("content")
        return c if isinstance(c, list) else []

    def _join_text(self, msg) -> str:
        return "".join(
            b.get("text", "") for b in self._content(msg) if b.get("type") == "text"
        )

    def _is_prompt(self, rec) -> bool:
        return rec.get("role") == _ROLE_USER and any(
            b.get("type") == "text" and b.get("text", "").strip()
            for b in self._content(rec)
        )

    def _prompt_text(self, rec) -> str:
        text = self._join_text(rec)
        found = _CLINE_USER_INPUT_RE.findall(text)
        return "".join(found).strip() if found else text.strip()

    def _ts(self, rec) -> float | None:
        ts = rec.get("ts")
        return ts / 1000.0 if isinstance(ts, (int, float)) else None

    def _tool_results(self, records) -> dict:
        results: dict = {}
        for msg in records:
            for b in self._content(msg):
                if b.get("type") == "tool_result" and (tid := b.get("tool_use_id")):
                    results[tid] = self._result_text(b)
        return results

    @staticmethod
    def _result_text(block) -> object:
        content = block.get("content")
        if isinstance(content, list):
            return "".join(
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
        return content if content is not None else ""

    def _events(self, rec, ts, results) -> list:
        if rec.get("role") != _ROLE_ASSISTANT:
            return []
        out = []
        text = self._join_text(rec)
        if text.strip():
            out.append(("llm", ts, text, rec.get("model"), None))
        for b in self._content(rec):
            if b.get("type") == "tool_use":
                out.append(
                    (
                        "tool",
                        ts,
                        b.get("name", "unknown"),
                        b.get("input", {}),
                        results.get(b.get("id"), ""),
                    )
                )
        return out


class CodexTranslator(Translator):
    """Codex rollout records → Trace (OpenAI Responses format).

    Normalizes the rollout into ``{ts, p}`` conversation items, then fits the
    template — except the prompt is the *last* user message in a consecutive run
    (Codex injects an AGENTS.md context message earlier), so ``_prompt_indices``
    is overridden with that lookahead.
    """

    agent = "codex"
    root_name = "codex_conversation"

    def _normalize(self, records) -> list[dict]:
        return [
            {"ts": _parse_ts(r.get("timestamp")), "p": r["payload"]}
            for r in records
            if r.get("type") == "response_item" and isinstance(r.get("payload"), dict)
        ]

    def _ts(self, rec) -> float | None:
        return rec["ts"]

    def _tool_results(self, records) -> dict:
        results: dict = {}
        for rec in records:
            p = rec["p"]
            if p.get("type") in ("function_call_output", "custom_tool_call_output"):
                if cid := p.get("call_id"):
                    results[cid] = p.get("output", "")
        return results

    def _prompt_indices(self, records) -> list[int]:
        msg_idxs = [i for i, r in enumerate(records) if r["p"].get("type") == "message"]
        prompts = []
        for pos, i in enumerate(msg_idxs):
            if records[i]["p"].get("role") != _ROLE_USER:
                continue
            nxt = msg_idxs[pos + 1] if pos + 1 < len(msg_idxs) else None
            if nxt is None or records[nxt]["p"].get("role") == _ROLE_ASSISTANT:
                prompts.append(i)
        return prompts

    def _prompt_text(self, rec) -> str:
        return self._msg_text(rec["p"])

    @staticmethod
    def _msg_text(item) -> str:
        return "".join(
            b.get("text", "")
            for b in (item.get("content") or [])
            if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")
        )

    def _events(self, rec, ts, results) -> list:
        p = rec["p"]
        ptype = p.get("type")
        if ptype == "message" and p.get("role") == _ROLE_ASSISTANT:
            text = self._msg_text(p)
            return [("llm", ts, text, None, None)] if text.strip() else []
        if ptype in ("function_call", "custom_tool_call"):
            name, tool_input = self._tool_call(p)
            return [
                ("tool", ts, name, tool_input, results.get(p.get("call_id", ""), ""))
            ]
        return []

    @staticmethod
    def _tool_call(item) -> tuple[str, object]:
        name = item.get("name", "unknown")
        if item.get("type") == "function_call":
            raw = item.get("arguments", "")
            try:
                return name, json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return name, raw
        return name, item.get("input", "")  # custom_tool_call: raw input string


class ClaudeTranslator(Translator):
    """Claude transcript → Trace — bespoke; overrides the template.

    Claude emits separate entries per thinking / text / tool_use, folds queued
    "steer" messages into the request window, splits a turn's duration across
    multiple tool calls, and carries token usage — richer than the event
    template, so it builds spans directly via ``Trace``'s ``add_*`` methods.
    """

    agent = "claude"

    def translate(self, records, *, trace_id, session_id, project) -> Trace | None:
        starts = self._prompt_indices(records)
        if not starts:
            return None
        trace = Trace(trace_id, session_id, self.agent, project)
        bounds = starts + [len(records)]
        for k, user_idx in enumerate(starts):
            self._build_turn(trace, records, user_idx, bounds[k + 1])
        return trace if trace.spans else None

    # _build_turn here takes no results arg (Claude looks results up per turn),
    # so it intentionally shadows the template's signature.
    def _build_turn(self, trace, records, user_idx, end_idx) -> None:  # type: ignore[override]
        user_rec = records[user_idx]
        user_msg = (user_rec.get("message") or {}).get("content", "")
        prompt = (
            user_msg if isinstance(user_msg, str) else self._text_and_tools(user_msg)[0]
        )
        root_id = user_rec.get("uuid") or f"turn-{user_idx}"
        root_ts = _parse_ts(user_rec.get("timestamp"))
        root = trace.add_agent_root(
            root_id, "claude_code_conversation", start_time=root_ts, prompt=prompt
        )

        counter = 0
        final_response: str | None = None
        last_ts = root_ts
        for i in range(user_idx + 1, end_idx):
            rec = records[i]
            if (t := _parse_ts(rec.get("timestamp"))) is not None:
                last_ts = t
            if rec.get("type") != _ROLE_ASSISTANT:
                continue
            msg = rec.get("message") or {}
            ts = _parse_ts(rec.get("timestamp"))
            text, tools = self._text_and_tools(msg.get("content"))
            nxt = self._next_timestamp(records, i, stop=end_idx)
            duration = (
                (nxt - ts)
                if (ts is not None and nxt is not None and nxt > ts)
                else _DEFAULT_SPAN_SECONDS
            )

            if text.strip() and not tools:
                final_response = text
                trace.add_llm_span(
                    f"{root_id}-{counter}",
                    parent_id=root_id,
                    start_time=ts,
                    end_time=(ts + duration) if ts is not None else None,
                    request=self._window_messages(records, i),
                    response=[_text_block(text)],
                    model=msg.get("model"),
                    usage=_usage(msg.get("usage")),
                )
                counter += 1

            if tools:
                results = self._tool_results_after(records, i)
                tool_duration = duration / len(tools)
                for idx_t, tu in enumerate(tools):
                    tid = tu.get("id", "")
                    t_start = (ts + idx_t * tool_duration) if ts is not None else None
                    trace.add_tool_span(
                        f"{root_id}-{counter}",
                        parent_id=root_id,
                        start_time=t_start,
                        end_time=(
                            (t_start + tool_duration) if t_start is not None else None
                        ),
                        name=tu.get("name", "unknown"),
                        tool_input=tu.get("input", {}),
                        result=results.get(tid, ""),
                        tool_id=tid,
                    )
                    counter += 1

        root["end_time"] = last_ts
        if final_response is not None:
            root["attributes"]["response"] = final_response

    # -- Claude grammar (ported from mlflow claude_code; see NOTICE) ---------

    def _prompt_indices(self, records) -> list[int]:
        return [i for i in range(len(records)) if self._is_user_prompt(records, i)]

    @staticmethod
    def _is_user_prompt(records, i) -> bool:
        rec = records[i]
        if rec.get("type") != _ROLE_USER or rec.get("toolUseResult"):
            return False
        prev = records[i - 1] if i > 0 else None
        prev_tur = prev.get("toolUseResult") if isinstance(prev, dict) else None
        if isinstance(prev_tur, dict) and prev_tur.get("commandName"):
            return False
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            if content[0].get("type") == "tool_result":
                return False
        if isinstance(content, str):
            if "<local-command-stdout>" in content or not content.strip():
                return False
        return bool(content)

    @staticmethod
    def _text_and_tools(content) -> tuple[str, list[dict]]:
        text, tools = "", []
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    text += b.get("text", "")
                elif b.get("type") == "tool_use":
                    tools.append(b)
        elif isinstance(content, str):
            text = content
        return text, tools

    @staticmethod
    def _next_timestamp(records, idx, stop=None) -> float | None:
        end = len(records) if stop is None else stop
        for j in range(idx + 1, end):
            if (t := _parse_ts(records[j].get("timestamp"))) is not None:
                return t
        return None

    def _block_from_raw(self, raw) -> dict | None:
        btype = raw.get("type")
        if btype == "text":
            return _text_block(raw.get("text", ""))
        if btype == "tool_use":
            return _tool_use_block(
                raw.get("name"), raw.get("input") or {}, raw.get("id")
            )
        if btype == "tool_result":
            return _tool_result_block(raw.get("content"), raw.get("tool_use_id"))
        return None  # thinking / unknown — no conversational payload

    def _message_from_record(self, record) -> dict | None:
        msg = record.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")
        if not role or not content:
            return None
        if isinstance(content, str):
            return _message(role, [_text_block(content)])
        blocks = [b for raw in content if (b := self._block_from_raw(raw))]
        return _message(role, blocks) if blocks else None

    def _window_messages(self, records, current_idx) -> list[dict]:
        """The user/tool entries since the previous text-bearing assistant turn."""
        out: list[dict] = []
        for i in range(current_idx - 1, -1, -1):
            rec = records[i]
            if rec.get("type") == _ROLE_ASSISTANT:
                text, _ = self._text_and_tools(
                    (rec.get("message") or {}).get("content")
                )
                if text.strip():
                    break
            if (
                rec.get("type") == _TYPE_QUEUE_OP
                and rec.get("operation") == "enqueue"
                and (steer := rec.get("content"))
            ):
                txt = steer if isinstance(steer, str) else str(steer)
                out.append(_message(_ROLE_USER, [_text_block(txt)]))
                continue
            if (m := self._message_from_record(rec)) is not None:
                out.append(m)
        out.reverse()
        return out

    @staticmethod
    def _tool_results_after(records, start_idx) -> dict:
        results: dict = {}
        for i in range(start_idx + 1, len(records)):
            rec = records[i]
            if rec.get("type") != _ROLE_USER:
                continue
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        if tid := b.get("tool_use_id"):
                            results[tid] = b.get("content", "")
        return results
