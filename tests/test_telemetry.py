from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_runtime import telemetry


def test_trace_does_not_record_exception_payload(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    try:
        with telemetry.operation("run.finish", "run-id"):
            raise ValueError("private-input-and-credential")
    except ValueError:
        pass
    span = exporter.get_finished_spans()[0]
    assert dict(span.attributes) == {"run.id": "run-id"}
    assert span.events == ()
    assert "private" not in span.to_json()
