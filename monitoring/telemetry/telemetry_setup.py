import logging
from config.settings import settings

logger = logging.getLogger(__name__)


def setup_telemetry(app):
    """Configure OpenTelemetry tracing. Falls back gracefully if the OTLP
    collector is not reachable (e.g. in a local / Replit dev environment)."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource.create({
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": settings.VERSION,
        })

        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry configurado com sucesso.")
    except Exception as e:
        logger.warning(
            f"OpenTelemetry não pôde ser inicializado (coletor indisponível?). "
            f"Rastreamento desativado. Detalhe: {e}"
        )
