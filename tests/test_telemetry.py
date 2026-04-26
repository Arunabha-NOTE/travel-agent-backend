from unittest.mock import MagicMock, patch
from app.core.telemetry import setup_telemetry, get_tracer, instrument_fastapi


def test_get_tracer():
    tracer = get_tracer("test")
    assert tracer is not None


@patch("app.core.telemetry.OTLPSpanExporter")
@patch("app.core.telemetry.BatchSpanProcessor")
@patch("app.core.telemetry.TracerProvider")
def test_setup_telemetry(mock_provider, mock_processor, mock_exporter):
    # Mock settings to use OTLP
    with patch("app.core.telemetry.settings") as mock_settings:
        mock_settings.OTEL_TRACES_EXPORTER = "otlp"
        mock_settings.OTEL_LOGS_EXPORTER = "none"
        mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318"
        mock_settings.OTEL_SERVICE_NAME = "test-service"
        mock_settings.ENVIRONMENT = "test"

        # Reset initialized flag for testing
        import app.core.telemetry

        app.core.telemetry._telemetry_initialized = False

        setup_telemetry()

        assert app.core.telemetry._telemetry_initialized is True
        mock_provider.assert_called_once()


def test_instrument_fastapi():
    mock_app = MagicMock()
    with patch(
        "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app"
    ) as mock_instrument:
        instrument_fastapi(mock_app)
        mock_instrument.assert_called_once_with(mock_app, excluded_urls="/metrics")
