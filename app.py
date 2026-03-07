import json
import os
import ssl
import time
from pathlib import Path
from urllib import error, request

from flask import Flask, Response, g, jsonify, render_template, request as flask_request
from markupsafe import Markup
from opentelemetry import context, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest, multiprocess


DEFAULT_CONFIG = Path(__file__).parent / "config" / "services.json"
STATIC_ICONS_DIR = Path(__file__).parent / "static" / "icons"
SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
SERVICE_ACCOUNT_TOKEN = SERVICE_ACCOUNT_DIR / "token"
SERVICE_ACCOUNT_CA = SERVICE_ACCOUNT_DIR / "ca.crt"

ICON_MAP = {
    "argocd": (
        '<path d="M12 3l6 3v6l-6 3-6-3V6l6-3z"/>'
        '<path d="M12 7l3 1.5v3L12 13l-3-1.5v-3L12 7z" fill="none" stroke="currentColor" stroke-width="1.5"/>'
    ),
    "grafana": (
        '<circle cx="8" cy="13" r="3"/>'
        '<circle cx="13" cy="8" r="4"/>'
        '<circle cx="16" cy="14" r="2"/>'
        '<path d="M4 17c2-3 4-4 8-4s6 1 8 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
    ),
    "prometheus": (
        '<path d="M12 2l7 4v8c0 4.5-3.1 8.4-7 10-3.9-1.6-7-5.5-7-10V6l7-4z"/>'
        '<path d="M12 8v5l3 2" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "gatus": (
        '<path d="M4 19h16"/>'
        '<path d="M7 15l3-3 3 2 4-5" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="7" cy="15" r="1.3"/><circle cx="10" cy="12" r="1.3"/><circle cx="13" cy="14" r="1.3"/><circle cx="17" cy="9" r="1.3"/>'
    ),
    "chat": (
        '<path d="M4 6h16v10H9l-5 4V6z"/>'
        '<path d="M8 10h8M8 13h5" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>'
    ),
    "jellyfin": (
        '<path d="M12 3l7 12H5l7-12z"/>'
        '<path d="M12 8l4 7H8l4-7z" fill="none" stroke="currentColor" stroke-width="1.5" />'
    ),
    "outline": (
        '<rect x="5" y="4" width="14" height="16" rx="1.5"/>'
        '<path d="M8 8h8M8 11h8M8 14h5" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>'
    ),
    "wiki": (
        '<path d="M5 5h11l3 3v11H8l-3-3V5z"/>'
        '<path d="M16 5v3h3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>'
        '<path d="M9 10h6M9 13h6" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>'
    ),
    "cluster-info": (
        '<circle cx="12" cy="12" r="8"/>'
        '<path d="M12 8v.01M12 11v5" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>'
    ),
    "docs": (
        '<path d="M6 4h8l4 4v12H6z"/>'
        '<path d="M14 4v4h4M9 12h6M9 15h6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "status": (
        '<path d="M5 17l4-4 3 2 5-6" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M4 19h16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
    ),
    "app": (
        '<rect x="4" y="4" width="16" height="16" rx="2"/>'
        '<path d="M8 8h8v8H8z" fill="none" stroke="currentColor" stroke-width="1.5"/>'
    ),
}

ICON_ALIASES = {
    "ar": "argocd",
    "gf": "grafana",
    "pr": "prometheus",
    "gt": "gatus",
    "ch": "chat",
    "jf": "jellyfin",
    "ol": "outline",
    "wk": "wiki",
    "ci": "cluster-info",
}

TRACER_NAME = "cluster-home"
_TRACING_CONFIGURED = False
HTTP_REQUESTS = Counter(
    "cluster_home_http_requests_total",
    "Total HTTP requests handled by cluster-home.",
    ["method", "handler", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "cluster_home_http_request_duration_seconds",
    "HTTP request latency for cluster-home.",
    ["method", "handler"],
)


def _otlp_endpoint() -> str:
    return (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or ""
    ).strip()


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _otlp_insecure(endpoint: str) -> bool:
    if not endpoint:
        return False
    if "OTEL_EXPORTER_OTLP_TRACES_INSECURE" in os.environ:
        return _env_flag("OTEL_EXPORTER_OTLP_TRACES_INSECURE", False)
    if "OTEL_EXPORTER_OTLP_INSECURE" in os.environ:
        return _env_flag("OTEL_EXPORTER_OTLP_INSECURE", False)
    return endpoint.startswith("http://")


def configure_tracing() -> bool:
    global _TRACING_CONFIGURED

    endpoint = _otlp_endpoint()
    if not endpoint:
        return False
    if _TRACING_CONFIGURED:
        return True

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": os.environ.get("OTEL_SERVICE_NAME", TRACER_NAME)}
        )
    )
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=_otlp_insecure(endpoint),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _TRACING_CONFIGURED = True
    return True


def _start_request_span() -> None:
    tracer = trace.get_tracer(TRACER_NAME)
    span = tracer.start_span(
        f"{flask_request.method} {flask_request.path}",
        kind=SpanKind.SERVER,
    )
    span.set_attribute("http.request.method", flask_request.method)
    span.set_attribute("url.path", flask_request.path)
    if flask_request.host:
        span.set_attribute("server.address", flask_request.host)

    token = context.attach(trace.set_span_in_context(span))
    g._otel_request_span = span
    g._otel_request_token = token


def _finish_request_span(*, status_code: int | None = None, error_obj: BaseException | None = None) -> None:
    span = g.pop("_otel_request_span", None)
    token = g.pop("_otel_request_token", None)
    if span is None:
        return

    if status_code is not None:
        span.set_attribute("http.response.status_code", status_code)
        if status_code >= 500:
            span.set_status(Status(StatusCode.ERROR))

    if error_obj is not None:
        span.record_exception(error_obj)
        span.set_status(Status(StatusCode.ERROR))

    span.end()
    if token is not None:
        context.detach(token)


def _handler_label() -> str:
    if flask_request.url_rule is not None:
        return flask_request.url_rule.rule
    return flask_request.path


def _metrics_response() -> Response:
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "").strip()
    if multiproc_dir:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        payload = generate_latest(registry)
    else:
        payload = generate_latest()
    return Response(payload, mimetype=CONTENT_TYPE_LATEST)


def load_config(path: str | None = None) -> dict:
    requested_path = path or os.environ.get("HOME_CONFIG_PATH")
    config_path = Path(requested_path) if requested_path else DEFAULT_CONFIG
    if not config_path.exists():
        config_path = DEFAULT_CONFIG
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def render_icon(icon: str | None, name: str) -> Markup:
    key = (icon or "").strip().lower()
    if key in ICON_ALIASES:
        key = ICON_ALIASES[key]
    if not key:
        normalized = name.strip().lower().replace(" ", "-")
        key = normalized if normalized in ICON_MAP else normalized.split("-")[0]
    svg_paths = ICON_MAP.get(key, ICON_MAP["app"])
    return Markup(
        f'<svg viewBox="0 0 24 24" aria-hidden="true" class="glyph glyph-{key}" '
        f'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
        f'stroke-linejoin="round">{svg_paths}</svg>'
    )


def render_icon_markup(icon: str | None, name: str) -> Markup:
    key = (icon or "").strip().lower()
    if key in ICON_ALIASES:
        key = ICON_ALIASES[key]
    if not key:
        normalized = name.strip().lower().replace(" ", "-")
        key = normalized if normalized in ICON_MAP else normalized.split("-")[0]

    icon_file = STATIC_ICONS_DIR / f"{key}.svg"
    if icon_file.exists():
        return Markup(
            f'<img src="/static/icons/{key}.svg" alt="" aria-hidden="true" class="logo-mark">'
        )

    return render_icon(key, name)


def cluster_stat_template(
    namespaces: str = "n/a",
    nodes: str = "n/a",
    deployments: str = "n/a",
    ready: str = "n/a",
    healthy_pods: str = "n/a",
    unhealthy: str = "n/a",
) -> list[dict[str, str]]:
    return [
        {"label": "Namespaces", "value": namespaces},
        {"label": "Nodes", "value": nodes},
        {"label": "Deployments", "value": deployments},
        {"label": "Ready", "value": ready},
        {"label": "Healthy pods", "value": healthy_pods},
        {"label": "Unhealthy", "value": unhealthy},
    ]


def load_cluster_info() -> dict:
    enabled = os.environ.get("CLUSTER_INFO_ENABLED", "true").lower() == "true"
    if not enabled:
        return {
            "available": False,
            "mode": "disabled",
            "summary": "Cluster info disabled",
            "stats": cluster_stat_template(),
        }

    host = os.environ.get("KUBERNETES_SERVICE_HOST")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    if not host or not SERVICE_ACCOUNT_TOKEN.exists() or not SERVICE_ACCOUNT_CA.exists():
        return {
            "available": False,
            "mode": "local",
            "summary": "Running outside the cluster",
            "stats": cluster_stat_template(),
        }

    token = SERVICE_ACCOUNT_TOKEN.read_text(encoding="utf-8").strip()
    context = ssl.create_default_context(cafile=str(SERVICE_ACCOUNT_CA))
    base_url = f"https://{host}:{port}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    def fetch_json(path: str) -> dict:
        tracer = trace.get_tracer(TRACER_NAME)
        with tracer.start_as_current_span(
            f"kubernetes.api {path}",
            kind=SpanKind.CLIENT,
        ) as span:
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("url.path", path)
            span.set_attribute("server.address", host)

            req = request.Request(f"{base_url}{path}", headers=headers)
            with request.urlopen(req, context=context, timeout=1.5) as response:
                span.set_attribute("http.response.status_code", response.status)
                return json.loads(response.read().decode("utf-8"))

    try:
        namespaces = fetch_json("/api/v1/namespaces").get("items", [])
        nodes = fetch_json("/api/v1/nodes").get("items", [])
        deployments = fetch_json("/apis/apps/v1/deployments").get("items", [])
        pods = fetch_json("/api/v1/pods").get("items", [])
    except (error.URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError, OSError):
        return {
            "available": False,
            "mode": "unreachable",
            "summary": "Kubernetes API unavailable",
            "stats": cluster_stat_template(),
        }

    unhealthy_pods = 0
    for pod in pods:
        phase = pod.get("status", {}).get("phase")
        statuses = pod.get("status", {}).get("containerStatuses", [])
        all_ready = bool(statuses) and all(status.get("ready") for status in statuses)
        if phase != "Running" or not all_ready:
            unhealthy_pods += 1

    ready_deployments = 0
    for deployment in deployments:
        desired = deployment.get("spec", {}).get("replicas", 1)
        available = deployment.get("status", {}).get("availableReplicas", 0)
        if available >= desired:
            ready_deployments += 1

    healthy_pods = max(len(pods) - unhealthy_pods, 0)

    return {
        "available": True,
        "mode": "cluster",
        "summary": "Live Kubernetes snapshot",
        "stats": cluster_stat_template(
            namespaces=str(len(namespaces)),
            nodes=str(len(nodes)),
            deployments=str(len(deployments)),
            ready=f"{ready_deployments}/{len(deployments)}",
            healthy_pods=str(healthy_pods),
            unhealthy=str(unhealthy_pods),
        ),
    }


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    tracing_enabled = configure_tracing()
    app.config.update(SITE_CONFIG=load_config())

    if test_config:
        app.config.update(test_config)

    if tracing_enabled:
        @app.before_request
        def begin_request_span() -> None:
            _start_request_span()

        @app.after_request
        def end_request_span(response):
            _finish_request_span(status_code=response.status_code)
            return response

        @app.teardown_request
        def teardown_request_span(error_obj: BaseException | None) -> None:
            if error_obj is not None:
                _finish_request_span(error_obj=error_obj)

    @app.before_request
    def begin_metrics_timer() -> None:
        if flask_request.path == "/metrics":
            return
        g._metrics_started_at = time.perf_counter()

    @app.after_request
    def record_request_metrics(response):
        started_at = g.pop("_metrics_started_at", None)
        if started_at is None:
            return response

        handler = _handler_label()
        duration = max(time.perf_counter() - started_at, 0.0)
        HTTP_REQUEST_DURATION.labels(
            method=flask_request.method,
            handler=handler,
        ).observe(duration)
        HTTP_REQUESTS.labels(
            method=flask_request.method,
            handler=handler,
            status=str(response.status_code),
        ).inc()
        return response

    @app.context_processor
    def inject_helpers() -> dict:
        return {"render_icon": render_icon_markup}

    @app.get("/")
    def home():
        config = app.config["SITE_CONFIG"]
        groups = config.get("groups", [])
        link_count = sum(len(group.get("items", [])) for group in groups)
        cluster_info = app.config.get("CLUSTER_INFO") or load_cluster_info()
        return render_template(
            "home.html",
            title=config.get("title", "Cluster Home"),
            subtitle=config.get("subtitle", ""),
            groups=groups,
            link_count=link_count,
            cluster_info=cluster_info,
        )

    @app.get("/health")
    def health():
        config = app.config["SITE_CONFIG"]
        group_count = len(config.get("groups", []))
        link_count = sum(len(group.get("items", [])) for group in config.get("groups", []))
        return jsonify(
            {
                "status": "ok",
                "groups": group_count,
                "links": link_count,
            }
        )

    @app.get("/metrics")
    def metrics():
        return _metrics_response()

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
