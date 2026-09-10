"""The canonical ``Trace`` form — nested span data plus composition / query
methods — and the block / message / usage shapes it is built from.

A session ``Trace`` carries one AGENT subtree per turn (an AGENT root with
``llm`` / ``tool_<name>`` children), matching the per-prompt granularity
MLflow's own claude autolog produces.  Fidelity is capped by what the
transcript persisted: every timestamp and token count is ``None``-tolerant.
"""

from __future__ import annotations

from datetime import datetime

_DEFAULT_SPAN_SECONDS = (
    1.0  # fallback turn-span duration when no next timestamp bounds it
)
_ROLE_ASSISTANT = "assistant"
_ROLE_USER = "user"
_TYPE_QUEUE_OP = "queue-operation"


def _parse_ts(ts: object) -> float | None:
    """ISO-8601 string (or epoch number) → epoch seconds; ``None`` on failure."""
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# The block / message / usage shapes (the one place they're constructed)
# ---------------------------------------------------------------------------


def _text_block(text: str | None) -> dict:
    return {"type": "text", "text": text or ""}


def _tool_use_block(name, tool_input, tool_call_id=None) -> dict:
    return {
        "type": "tool_use",
        "id": tool_call_id,
        "name": name,
        "input": tool_input or {},
    }


def _tool_result_block(output, tool_call_id=None) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_call_id, "content": output}


def _message(role: str, blocks: list[dict]) -> dict:
    return {"role": role, "content": blocks}


def _usage(raw: dict | None) -> dict | None:
    """Token counts from a transcript ``usage`` dict; ``None`` when absent."""
    if not raw:
        return None
    return {
        "input_tokens": raw.get("input_tokens"),
        "output_tokens": raw.get("output_tokens"),
        "cache_read_input_tokens": raw.get("cache_read_input_tokens"),
        "cache_write_input_tokens": raw.get("cache_creation_input_tokens"),
    }


class Trace:
    """One finished agent session: id fields plus a list of span dicts.

    The span/message/block shapes are documented in the package docstring and
    built *only* by the ``add_*`` methods here, so the schema has one home.
    Consumers read ``spans`` (and ``to_exchanges()``) directly — the data is
    already in the dict shape both the MLflow logger and memory want.
    """

    def __init__(self, trace_id: str, session_id: str, agent: str, project: str):
        self.trace_id = trace_id
        self.session_id = session_id
        self.agent = agent
        self.project = project
        self.spans: list[dict] = []

    @property
    def started_at(self) -> float | None:
        return self.spans[0]["start_time"] if self.spans else None

    @property
    def ended_at(self) -> float | None:
        return self.spans[-1]["end_time"] if self.spans else None

    # -- composition (the only place a span dict is constructed) -------------

    def add_agent_root(self, span_id, name, *, start_time, prompt) -> dict:
        span = {
            "span_id": span_id,
            "name": name,
            "kind": "AGENT",
            "parent_id": None,
            "start_time": start_time,
            "end_time": None,
            "status": "ok",
            "request": [],
            "response": [],
            "model": None,
            "usage": None,
            "attributes": {"prompt": prompt},
        }
        self.spans.append(span)
        return span

    def add_llm_span(
        self,
        span_id,
        *,
        parent_id,
        start_time,
        end_time,
        request,
        response,
        model=None,
        usage=None,
    ) -> dict:
        span = {
            "span_id": span_id,
            "name": "llm",
            "kind": "LLM",
            "parent_id": parent_id,
            "start_time": start_time,
            "end_time": end_time,
            "status": "ok",
            "request": request,
            "response": response,
            "model": model,
            "usage": usage,
            "attributes": {},
        }
        self.spans.append(span)
        return span

    def add_tool_span(
        self,
        span_id,
        *,
        parent_id,
        start_time,
        end_time,
        name,
        tool_input,
        result,
        tool_id="",
    ) -> dict:
        span = {
            "span_id": span_id,
            "name": f"tool_{name}",
            "kind": "TOOL",
            "parent_id": parent_id,
            "start_time": start_time,
            "end_time": end_time,
            "status": "ok",
            "request": [],
            "response": [],
            "model": None,
            "usage": None,
            "attributes": {
                "tool_name": name,
                "tool_id": tool_id,
                "input": tool_input,
                "result": result,
            },
        }
        self.spans.append(span)
        return span

    def add_turn(self, *, root_id, root_name, prompt, root_ts, events, last_ts) -> None:
        """Append one AGENT subtree from a turn's ordered ``events``.

        Each event is a tuple — ``("llm", ts, text, model, usage)`` or
        ``("tool", ts, name, input, result)`` — in transcript order.  This is the
        shared builder the four template translators use: it derives each span's
        duration from the next event's timestamp (1s fallback for the last), and
        threads the request "window" (the prompt, then each tool call+result)
        into the following ``llm`` span's ``request`` — which is what memory's
        ``to_exchanges`` reads.
        """
        root = self.add_agent_root(
            root_id, root_name, start_time=root_ts, prompt=prompt
        )
        pending = [_message(_ROLE_USER, [_text_block(prompt)])]
        ts_list = [e[1] for e in events]
        final_response: str | None = None
        for i, ev in enumerate(events):
            ts = ev[1]
            nxt = next((t for t in ts_list[i + 1 :] if t is not None), last_ts)
            dur = (
                (nxt - ts)
                if (ts is not None and nxt is not None and nxt > ts)
                else _DEFAULT_SPAN_SECONDS
            )
            end = (ts + dur) if ts is not None else None
            if ev[0] == "llm":
                _, _, text, model, usage = ev
                final_response = text
                self.add_llm_span(
                    f"{root_id}-{i}",
                    parent_id=root_id,
                    start_time=ts,
                    end_time=end,
                    request=list(pending),
                    response=[_text_block(text)],
                    model=model,
                    usage=usage,
                )
                pending = []
            else:  # "tool"
                _, _, name, tin, result = ev
                self.add_tool_span(
                    f"{root_id}-{i}",
                    parent_id=root_id,
                    start_time=ts,
                    end_time=end,
                    name=name,
                    tool_input=tin,
                    result=result,
                )
                tool_input = tin if isinstance(tin, dict) else {"raw": tin}
                pending.append(
                    _message(_ROLE_ASSISTANT, [_tool_use_block(name, tool_input)])
                )
                pending.append(_message(_ROLE_USER, [_tool_result_block(result)]))
        root["end_time"] = last_ts if last_ts is not None else root_ts
        if final_response is not None:
            root["attributes"]["response"] = final_response

    # -- query / projection -------------------------------------------------

    def roots(self) -> list[dict]:
        return [s for s in self.spans if s["parent_id"] is None]

    def children(self, root_id) -> list[dict]:
        return [s for s in self.spans if s["parent_id"] == root_id]

    def subset(self, root_ids: set[str]) -> "Trace":
        """A copy carrying only the given AGENT roots and their direct children."""
        keep = [
            s
            for s in self.spans
            if (s["parent_id"] is None and s["span_id"] in root_ids)
            or s["parent_id"] in root_ids
        ]
        out = Trace(self.trace_id, self.session_id, self.agent, self.project)
        out.spans = keep
        return out

    def to_exchanges(self) -> list[dict]:
        """Project the ``llm`` spans onto memory's conversational shape.

        One ``llm`` span → one ``{turn_id, timestamp, new_messages, response}``
        exchange; ``turn_id`` is the span id (groups a turn's chunks back
        together downstream), ``request`` is already the windowed message list,
        ``response`` the output blocks — so this is a straight projection.
        """
        return [
            {
                "turn_id": s["span_id"],
                "timestamp": s["start_time"],
                "new_messages": s["request"],
                "response": s["response"],
            }
            for s in self.spans
            if s["kind"] == "LLM"
        ]
