"""
OpenTelemetry tracing setup for FastAPI.

v4.0: Auto-instrument FastAPI app with OTLP exporter.
Set OTEL_EXPORTER_OTLP_ENDPOINT env var to enable.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import (
    Resource,
    SERVICE_NAME,
    SERVICE_VERSION,
)

logger = logging.getLogger("hltv.tracing")

_tracer_provider: TracerProvider | None = None


def setup_tracing(
    service_name: str = "hltv-api",
    service_version: str = "4.0.0",
    otlp_endpoint: str | None = None,
) -> bool:
    """Initialize OpenTelemetry tracing.

    Args:
        service_name: Service name for traces.
        service_version: Service version.
        otlp_endpoint: OTLP collector endpoint.

    Returns:
        True if tracing was enabled.
    """
    global _tracer_provider

    endpoint = otlp_endpoint or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", ""
    )

    if not endpoint:
        logger.debug("OTLP endpoint not set, tracing disabled")
        return False

    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
    })

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    logger.info(
        "OpenTelemetry tracing enabled → %s (service=%s v%s)",
        endpoint, service_name, service_version,
    )
    return True


def instrument_fastapi(app) -> None:
    """Instrument a FastAPI app with OpenTelemetry.

    Args:
        app: FastAPI application instance.
    """
    if _tracer_provider is None:
        return
    from opentelemetry.instrumentation.fastapi import (
        FastAPIInstrumentor,
    )
    FastAPIInstrumentor.instrument_app(app)
    logger.info("FastAPI instrumented with OpenTelemetry")
