import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

def setup_telemetry(app):
    """
    Sets up OpenTelemetry tracing and exports data to SigNoz OTel Collector.
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
    
    # SigNoz normally receives gRPC at port 4317 and HTTP at port 4318
    is_http = (
        otlp_protocol == "http/protobuf" or 
        ":4318" in otlp_endpoint or 
        "/v1/" in otlp_endpoint
    )
    
    if is_http:
        # Use HTTP protobuf exporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        # Ensure the OTLP/HTTP endpoint ends with '/v1/traces' as required by OTel Python OTLPSpanExporter
        http_endpoint = otlp_endpoint
        if not http_endpoint.endswith("/v1/traces") and not http_endpoint.endswith("/v1/traces/"):
            if http_endpoint.endswith("/"):
                http_endpoint += "v1/traces"
            else:
                http_endpoint += "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=http_endpoint)
    else:
        # Use gRPC exporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        
    # 4. Span Processor
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    
    # 5. Define request hook for user tracking
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

    # 6. Instrument FastAPI
    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=server_request_hook,
        excluded_urls="/health,/healthcheck,/ready,/train_routes/.*"
    )
