"""The MLflow replay sink — a finished agent ``Trace`` → backdated MLflow spans.

The trace-consumer half of the pipeline: :class:`MLflowSink` replays a
transcript's :class:`~dsagt.traces.trace.Trace` into the serverless sqlite
MLflow store after the fact.  It uses ``mlflow.start_span_no_context`` — the
only MLflow API that accepts an explicit ``parent_span`` and a backdated
``start_time_ns`` (``mlflow.start_span``, which DSAGT's own live tracer in
:mod:`dsagt.observability` uses, cannot backdate).

mlflow is imported lazily inside :meth:`MLflowSink.write`, so importing this
module — and building a collector around the sink — needs no extra; the first
``write`` needs ``dsagt[traces]``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_S_PER_NS = 1e9


def _to_ns(epoch_s: float | None) -> int | None:
    return int(epoch_s * _S_PER_NS) if epoch_s is not None else None


class MLflowSink:
    """Render a :class:`~dsagt.traces.trace.Trace` into MLflow spans (a trace consumer).

    Replays a finished transcript's ``Trace`` into the store via
    ``mlflow.start_span_no_context`` and mirrors the span conventions of
    MLflow's own ``claude_code`` autolog so foreign traces render identically
    in the Chat UI: an AGENT root, ``llm`` children carrying
    ``message.format="anthropic"`` + ``mlflow.chat.tokenUsage``, and
    ``tool_<name>`` children.  Agent traces carry no ``dsagt.source`` tag, so
    they stay in the normal view, separate from the internal debug traces.

    A session ``Trace`` carries one AGENT subtree per turn; the sink emits **one
    MLflow trace per AGENT root**, matching the per-prompt granularity autolog's
    Stop hook produces.  MLflow mints its own trace/span ids, so each trace is
    tagged ``dsagt.trace_id = <trace_id>:<root span_id>`` (a stable per-turn
    idempotency key) and ``dsagt.agent = <agent>`` (attribution in the store).

    A *consumer* of :class:`~dsagt.traces.collector.TraceCollector`: ``name``
    keys its own ack file (``<ack_dir>/trace_acks_mlflow.json``); ``write``
    logs the trace.  Spans are plain dicts (see the package docstring), so
    this reads them directly — no per-object serialization.
    """

    name = "mlflow"

    def __init__(self, tracking_uri: str, experiment: str):
        self._uri = tracking_uri
        self._experiment = experiment

    def write(self, trace) -> list[str]:
        """Log every turn subtree; return the MLflow trace id of each."""
        try:
            import mlflow
        except ImportError as e:
            raise ImportError("the MLflow sink needs `dsagt[traces]`") from e

        mlflow.set_tracking_uri(self._uri)
        mlflow.set_experiment(trace.project or self._experiment)

        children: dict[str, list] = {}
        for span in trace.spans:
            if span["parent_id"] is not None:
                children.setdefault(span["parent_id"], []).append(span)

        trace_ids = []
        for root in trace.spans:
            if root["parent_id"] is None:
                trace_ids.append(
                    self._emit_subtree(root, children.get(root["span_id"], []), trace)
                )
        return trace_ids

    def _emit_subtree(self, root, children, trace) -> str:
        """Emit one MLflow trace for an AGENT ``root`` and its direct children."""
        import mlflow
        from mlflow.entities import SpanType
        from mlflow.tracing.constant import (
            SpanAttributeKey,
            TokenUsageKey,
            TraceMetadataKey,
        )
        from mlflow.tracing.trace_manager import InMemoryTraceManager

        kind_to_type = {
            "AGENT": SpanType.AGENT,
            "LLM": SpanType.LLM,
            "TOOL": SpanType.TOOL,
            "OTHER": SpanType.UNKNOWN,
        }

        ml_root = mlflow.start_span_no_context(
            name=root["name"],
            span_type=kind_to_type[root["kind"]],
            inputs={"prompt": root["attributes"].get("prompt", "")},
            start_time_ns=_to_ns(root["start_time"]),
        )

        for span in children:
            if span["kind"] == "LLM":
                child = mlflow.start_span_no_context(
                    name=span["name"],
                    parent_span=ml_root,
                    span_type=SpanType.LLM,
                    start_time_ns=_to_ns(span["start_time"]),
                    inputs={
                        "model": span["model"] or "unknown",
                        "messages": span["request"],
                    },
                    attributes={
                        "model": span["model"] or "unknown",
                        SpanAttributeKey.MESSAGE_FORMAT: "anthropic",
                    },
                )
                if span["usage"]:
                    inp = span["usage"].get("input_tokens") or 0
                    out = span["usage"].get("output_tokens") or 0
                    usage = {
                        TokenUsageKey.INPUT_TOKENS: inp,
                        TokenUsageKey.OUTPUT_TOKENS: out,
                        TokenUsageKey.TOTAL_TOKENS: inp + out,
                    }
                    # Cache counts, when the transcript has them (mirrors
                    # mlflow.anthropic's autolog).  For a Claude session most
                    # input is cache reads, so a cost computed from the store
                    # undercounts badly without these.
                    if (v := span["usage"].get("cache_read_input_tokens")) is not None:
                        usage[TokenUsageKey.CACHE_READ_INPUT_TOKENS] = v
                    if (v := span["usage"].get("cache_write_input_tokens")) is not None:
                        usage[TokenUsageKey.CACHE_CREATION_INPUT_TOKENS] = v
                    child.set_attribute(SpanAttributeKey.CHAT_USAGE, usage)
                child.set_outputs(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": span["response"],
                    }
                )
            else:  # TOOL / OTHER
                child = mlflow.start_span_no_context(
                    name=span["name"],
                    parent_span=ml_root,
                    span_type=kind_to_type[span["kind"]],
                    start_time_ns=_to_ns(span["start_time"]),
                    inputs=span["attributes"].get("input", {}),
                    attributes={
                        "tool_name": span["attributes"].get("tool_name"),
                        "tool_id": span["attributes"].get("tool_id"),
                    },
                )
                child.set_outputs({"result": span["attributes"].get("result", "")})
            child.end(end_time_ns=_to_ns(span["end_time"]))

        # Trace-level metadata: session correlation + the per-turn canonical id
        # (idempotency key) + request/response previews for the trace list.
        try:
            mgr = InMemoryTraceManager.get_instance()
            with mgr.get_trace(ml_root.trace_id) as in_mem:
                meta = {
                    TraceMetadataKey.TRACE_SESSION: trace.session_id,
                    "dsagt.trace_id": f"{trace.trace_id}:{root['span_id']}",
                    "dsagt.agent": trace.agent,
                }
                in_mem.info.trace_metadata = {**in_mem.info.trace_metadata, **meta}
                if prompt := root["attributes"].get("prompt"):
                    in_mem.info.request_preview = str(prompt)[:1000]
                if response := root["attributes"].get("response"):
                    in_mem.info.response_preview = str(response)[:1000]
        except Exception as e:  # noqa: BLE001
            logger.warning("MLflowSink: could not stamp trace metadata: %s", e)

        ml_root.set_outputs({"response": root["attributes"].get("response", "")})
        ml_root.end(end_time_ns=_to_ns(root["end_time"]))
        return ml_root.trace_id
