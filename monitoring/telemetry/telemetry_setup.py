import logging
from config.settings import settings

logger = logging.getLogger(__name__)
_provider_initialized = False
_provider_config: tuple[str, str, str] | None = None


def setup_telemetry(app, app_settings=None):
    """Configure OpenTelemetry tracing. Falls back gracefully if the OTLP
    collector is not reachable (e.g. in a local / Replit dev environment)."""
    global _provider_initialized, _provider_config
    config = app_settings or settings
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        if not _provider_initialized:
            resource = Resource.create({
                "service.name": config.OTEL_SERVICE_NAME,
                "service.version": config.VERSION,
            })
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=config.OTEL_EXPORTER_OTLP_ENDPOINT)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            _provider_config = (
                config.OTEL_SERVICE_NAME,
                config.VERSION,
                config.OTEL_EXPORTER_OTLP_ENDPOINT,
            )
            _provider_initialized = True
        else:
            requested_config = (
                config.OTEL_SERVICE_NAME,
                config.VERSION,
                config.OTEL_EXPORTER_OTLP_ENDPOINT,
            )
            if requested_config != _provider_config:
                logger.warning(
                    "TracerProvider é process-global; a configuração OTEL desta app "
                    "difere da primeira configuração e continuará usando o provider existente."
                )

        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry configurado com sucesso.")
    except Exception as e:
        logger.warning(
            f"OpenTelemetry não pôde ser inicializado (coletor indisponível?). "
            f"Rastreamento desativado. Detalhe: {e}"
        )
