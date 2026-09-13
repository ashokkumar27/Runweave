"""Allowlisted operational telemetry; no automatic HTTP/model/prompt instrumentation."""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure(endpoint: str):
    if endpoint:
        provider = TracerProvider()
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces"))
        )
        trace.set_tracer_provider(provider)


def operation(name: str, run_id: str):
    # Never record exceptions automatically: SDK exception bodies can contain payloads.
    return trace.get_tracer("agent-runtime").start_as_current_span(
        name, attributes={"run.id": run_id}, record_exception=False, set_status_on_exception=False
    )


def configure_logging():
    """Third-party exceptions may echo payloads; log classifications, never their bodies."""
    import logging

    class SafeFormatter(logging.Formatter):
        def format(self, record):
            category = type(record.exc_info[1]).__name__ if record.exc_info else "diagnostic"
            return f"{record.levelname} {record.name}: {category}"

    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
