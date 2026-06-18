import os
import sys
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Log SDK imports
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

class LoggerWriter:
    """
    Redirects stdout/stderr write calls to standard logging.
    """
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, message):
        if message and message.strip():
            self.logger.log(self.level, message.rstrip())

    def flush(self):
        pass

def setup_telemetry(app):
    """
    Sets up OpenTelemetry tracing and logging to export data to OTel Collector or New Relic.
    Configurable via standard environment variables:
    - OTEL_SERVICE_NAME: Name of the service (default: "find-my-br-train")
    - OTEL_EXPORTER_OTLP_ENDPOINT: Endpoint of the OTel Collector (default: "http://localhost:4317")
    - OTEL_EXPORTER_OTLP_PROTOCOL: Exporter protocol, either "grpc" or "http/protobuf" (default: "grpc")
    """
    # 1. Resource name (Service Name)
    service_name = os.getenv("OTEL_SERVICE_NAME", "find-my-br-train")
    resource = Resource.create({"service.name": service_name})
    
    # 2. Tracer Provider
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    
    # 3. OTLP Exporter Configuration
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    otlp_protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").lower()
    
    is_http = (
        otlp_protocol == "http/protobuf" or 
        ":4318" in otlp_endpoint or 
        "/v1/" in otlp_endpoint
    )
    
    if is_http:
        # Use HTTP protobuf trace exporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        # Ensure the OTLP/HTTP endpoint ends with '/v1/traces'
        http_endpoint = otlp_endpoint
        if not http_endpoint.endswith("/v1/traces") and not http_endpoint.endswith("/v1/traces/"):
            if http_endpoint.endswith("/"):
                http_endpoint += "v1/traces"
            else:
                http_endpoint += "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=http_endpoint)
        
        # Use HTTP protobuf log exporter
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        # Ensure the OTLP/HTTP log endpoint ends with '/v1/logs'
        log_endpoint = otlp_endpoint
        if not log_endpoint.endswith("/v1/logs") and not log_endpoint.endswith("/v1/logs/"):
            if log_endpoint.endswith("/"):
                log_endpoint += "v1/logs"
            else:
                log_endpoint += "/v1/logs"
        log_exporter = OTLPLogExporter(endpoint=log_endpoint)
    else:
        # Use gRPC trace exporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        
        # Use gRPC log exporter
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        log_exporter = OTLPLogExporter(endpoint=otlp_endpoint, insecure=True)
        
    # 4. Span Processor Setup
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    
    # 5. Log Provider Setup
    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)
    
    log_processor = BatchLogRecordProcessor(log_exporter)
    logger_provider.add_log_record_processor(log_processor)
    
    # Attach the OTel LoggingHandler to the root logger so all logs are collected
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    
    # 6. Prevent recursion and redirect stdout/stderr to logger
    raw_stdout = sys.__stdout__
    raw_stderr = sys.__stderr__

    def fix_handler_streams(logger_instance):
        for h in logger_instance.handlers:
            if isinstance(h, logging.StreamHandler):
                if h.stream in (sys.stdout, sys.stderr):
                    h.stream = raw_stderr

    # Fix root logger handlers
    fix_handler_streams(logging.getLogger())
    
    # Fix all other active loggers
    for name in logging.root.manager.loggerDict:
        fix_handler_streams(logging.getLogger(name))

    # Redirect sys.stdout and sys.stderr
    stdout_logger = logging.getLogger("stdout")
    stdout_logger.setLevel(logging.INFO)
    sys.stdout = LoggerWriter(stdout_logger, logging.INFO)

    stderr_logger = logging.getLogger("stderr")
    stderr_logger.setLevel(logging.ERROR)
    sys.stderr = LoggerWriter(stderr_logger, logging.ERROR)
    
    # 7. Define request hook for user tracking
    def server_request_hook(span, scope):
        if span and span.is_recording():
            # Get headers from ASGI scope
            headers = scope.get("headers", [])
            user_id = None
            authorization = None
            
            for k, v in headers:
                k_str = k.decode("utf-8", errors="ignore").lower()
                if k_str == "x-user-id":
                    user_id = v.decode("utf-8", errors="ignore")
                elif k_str == "authorization":
                    authorization = v.decode("utf-8", errors="ignore")
                    
            # If not in headers, extract from query string
            if not user_id:
                query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
                if query_string:
                    from urllib.parse import parse_qs
                    params = parse_qs(query_string)
                    user_id = params.get("user_id", [None])[0] or params.get("user", [None])[0]
                    
            if not user_id and authorization:
                user_id = authorization
                
            if user_id:
                span.set_attribute("user.id", str(user_id))
                span.set_attribute("enduser.id", str(user_id))

    # 8. Instrument FastAPI
    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=server_request_hook,
        excluded_urls="/health,/healthcheck,/ready,/train_routes/.*"
    )
