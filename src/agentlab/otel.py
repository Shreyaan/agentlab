"""Observe-only import: normalize an OTLP/JSON trace export into AgentLab events.

A trace shows what was instrumented, not hidden state; imported traces never grant invoke/replay/interception.
"""

from agentlab.protocol import Event

ERROR_STATUS = 2  # OTLP STATUS_CODE_ERROR


def _attrs(span: dict) -> dict:
    out = {}
    for a in span.get("attributes", []):
        v = a.get("value", {})
        out[a["key"]] = next(iter(v.values()), None) if v else None
    return out


def parse_otlp(doc: dict) -> list[Event]:
    spans = [s for rs in doc.get("resourceSpans", []) for ss in rs.get("scopeSpans", []) for s in ss.get("spans", [])]
    spans.sort(key=lambda s: int(s.get("startTimeUnixNano", 0)))
    events = []
    for i, span in enumerate(spans, 1):
        attrs, failed = _attrs(span), span.get("status", {}).get("code") == ERROR_STATUS
        if tool := attrs.get("gen_ai.tool.name"):
            etype, name = ("tool_failed" if failed else "tool_completed"), tool
        elif attrs.get("gen_ai.operation.name") in ("chat", "text_completion", "generate_content"):
            etype, name = "model_call", attrs.get("gen_ai.request.model")
        else:
            etype, name = "agent_step", span.get("name")
        events.append(
            Event(
                seq=i,
                type=etype,
                name=name,
                ts=int(span.get("startTimeUnixNano", 0)) / 1e9,
                span_id=span.get("spanId"),
                parent_id=span.get("parentSpanId") or None,
                data={"span_name": span.get("name"), "source": "otel_partial"},
            )
        )
    return events
