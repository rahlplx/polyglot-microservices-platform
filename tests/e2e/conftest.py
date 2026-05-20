"""
Shared fixtures for End-to-End Integration Tests across all 9 services.

Provides:
- Service endpoints configuration (gRPC + HTTP for each service)
- gRPC channel factory with mTLS support (using SPIFFE SVIDs)
- HTTP client factory with proper headers
- Kafka consumer/producer fixtures
- PostgreSQL connection fixtures
- OTel trace collector fixture
- Wait-for-service readiness helpers (with retry/timeout)
- Service registry mapping service names to endpoints
- Kubernetes cluster access helpers
"""

import json
import os
import re
import ssl
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRUST_DOMAIN = os.getenv("E2E_TRUST_DOMAIN", "trust.example.org")
NAMESPACE = os.getenv("E2E_NAMESPACE", "production")
CLUSTER_NAME = os.getenv("E2E_CLUSTER_NAME", "polyglot-e2e")
KAFKA_BOOTSTRAP = os.getenv("E2E_KAFKA_BOOTSTRAP", "kafka.production.svc.cluster.local:9092")
POSTGRES_HOST = os.getenv("E2E_POSTGRES_HOST", "postgres.production.svc.cluster.local")
POSTGRES_PORT = int(os.getenv("E2E_POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("E2E_POSTGRES_DB", "polyglot_platform")
POSTGRES_USER = os.getenv("E2E_POSTGRES_USER", "platform_admin")
POSTGRES_PASSWORD = os.getenv("E2E_POSTGRES_PASSWORD", "")
PROMETHEUS_URL = os.getenv("E2E_PROMETHEUS_URL", "http://prometheus.production.svc.cluster.local:9090")
TEMPO_URL = os.getenv("E2E_TEMPO_URL", "http://tempo.production.svc.cluster.local:3200")
LOKI_URL = os.getenv("E2E_LOKI_URL", "http://loki.production.svc.cluster.local:3100")
GRAFANA_URL = os.getenv("E2E_GRAFANA_URL", "http://grafana.production.svc.cluster.local:3000")
GATEWAY_HTTP_PORT = int(os.getenv("E2E_GATEWAY_HTTP_PORT", "8080"))
GATEWAY_GRPC_PORT = int(os.getenv("E2E_GATEWAY_GRPC_PORT", "50051"))

DEFAULT_READINESS_TIMEOUT = int(os.getenv("E2E_READINESS_TIMEOUT", "120"))
DEFAULT_READINESS_INTERVAL = int(os.getenv("E2E_READINESS_INTERVAL", "5"))
CDC_LAG_SLA_SECONDS = int(os.getenv("E2E_CDC_LAG_SLA", "5"))

# Kafka topics used across E2E tests
KAFKA_TOPICS = {
    "order_events": "platform.order.events",
    "payment_events": "platform.payment.events",
    "catalog_events": "platform.catalog.events",
    "notification_events": "platform.notification.events",
    "cdc_orders": "platform.cdc.orders",
    "cdc_payments": "platform.cdc.payments",
    "cdc_catalog": "platform.cdc.catalog",
    "outbox_events": "platform.outbox.events",
}

# ---------------------------------------------------------------------------
# Service Registry — Maps service names to endpoint configuration
# ---------------------------------------------------------------------------
SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "gateway": {
        "language": "go",
        "grpc_port": 50051,
        "http_port": 8080,
        "service_account": "gateway",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/gateway",
        "dns_names": [
            "gateway",
            "gateway.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "gateway.v1.GatewayService",
        "kustomize_path": "services/gateway/kustomize",
    },
    "identity": {
        "language": "rust",
        "grpc_port": 50052,
        "http_port": 8081,
        "service_account": "identity",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/identity",
        "dns_names": [
            "identity",
            "identity.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "identity.v1.IdentityService",
        "kustomize_path": "services/identity/kustomize",
    },
    "catalog": {
        "language": "typescript",
        "grpc_port": 50053,
        "http_port": 8082,
        "service_account": "catalog",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/catalog",
        "dns_names": [
            "catalog",
            "catalog.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "catalog.v1.CatalogService",
        "kustomize_path": "services/catalog/kustomize",
    },
    "order": {
        "language": "kotlin",
        "grpc_port": 50054,
        "http_port": 8083,
        "service_account": "order",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/order",
        "dns_names": [
            "order",
            "order.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "order.v1.OrderService",
        "kustomize_path": "services/order/kustomize",
    },
    "payment": {
        "language": "go",
        "grpc_port": 50055,
        "http_port": 8084,
        "service_account": "payment",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/payment",
        "dns_names": [
            "payment",
            "payment.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "payment.v1.PaymentService",
        "kustomize_path": "services/payment/kustomize",
    },
    "notification": {
        "language": "python",
        "grpc_port": 50056,
        "http_port": 8085,
        "service_account": "notification",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/notification",
        "dns_names": [
            "notification",
            "notification.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "notification.v1.NotificationService",
        "kustomize_path": "services/notification/kustomize",
    },
    "analytics": {
        "language": "python",
        "grpc_port": 50057,
        "http_port": 8086,
        "service_account": "analytics",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/analytics",
        "dns_names": [
            "analytics",
            "analytics.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "analytics.v1.AnalyticsService",
        "kustomize_path": "services/analytics/kustomize",
    },
    "rl-engine": {
        "language": "python",
        "grpc_port": 50058,
        "http_port": 8087,
        "service_account": "rl-engine",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/rl-engine",
        "dns_names": [
            "rl-engine",
            "rl-engine.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "gateway.v1.RateLimitService",
        "kustomize_path": "services/rl-engine/kustomize",
    },
    "schema-registry": {
        "language": "go",
        "grpc_port": 50059,
        "http_port": 8088,
        "service_account": "schema-registry",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/schema-registry",
        "dns_names": [
            "schema-registry",
            "schema-registry.production.svc.cluster.local",
        ],
        "health_endpoint": "/healthz",
        "grpc_service": "schema.v1.SchemaRegistryService",
        "kustomize_path": "services/schema-registry/kustomize",
    },
}

ALL_SERVICES = list(SERVICE_REGISTRY.keys())

# ---------------------------------------------------------------------------
# Kubernetes Helper
# ---------------------------------------------------------------------------
class KubectlHelper:
    """Helper for executing kubectl commands against the E2E cluster."""

    def __init__(self, namespace: str = NAMESPACE, context: Optional[str] = None):
        self.namespace = namespace
        self.context = context

    def _run(self, cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a kubectl command with optional context."""
        full_cmd = ["kubectl", "-n", self.namespace]
        if self.context:
            full_cmd.extend(["--context", self.context])
        full_cmd.extend(cmd)
        return subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def get_pod_name(self, service: str) -> Optional[str]:
        """Get the first running pod name for a service."""
        result = self._run([
            "get", "pods",
            "-l", f"app.kubernetes.io/name={service}",
            "--field-selector=status.phase=Running",
            "-o", "jsonpath={.items[0].metadata.name}",
        ])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        # Fallback: alternate label selector
        result = self._run([
            "get", "pods",
            "-l", f"app={service}",
            "--field-selector=status.phase=Running",
            "-o", "jsonpath={.items[0].metadata.name}",
        ])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    def exec_in_pod(
        self, pod_name: str, command: List[str], container: Optional[str] = None
    ) -> Tuple[int, str, str]:
        """Execute a command in a pod and return (returncode, stdout, stderr)."""
        cmd = ["exec", pod_name]
        if container:
            cmd.extend(["-c", container])
        cmd.append("--")
        cmd.extend(command)
        result = self._run(cmd, timeout=60)
        return result.returncode, result.stdout, result.stderr

    def port_forward(
        self, service: str, local_port: int, remote_port: int
    ) -> subprocess.Popen:
        """Start a port-forward to a service. Returns Popen handle."""
        cmd = [
            "kubectl", "-n", self.namespace,
            "port-forward", f"svc/{service}", f"{local_port}:{remote_port}",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)  # Allow port-forward to establish
        return proc

    def scale_deployment(self, service: str, replicas: int) -> bool:
        """Scale a deployment to the given number of replicas."""
        result = self._run([
            "scale", "deployment", service, f"--replicas={replicas}",
        ])
        return result.returncode == 0

    def delete_pod(self, pod_name: str, force: bool = False) -> bool:
        """Delete a pod (optionally force)."""
        cmd = ["delete", "pod", pod_name]
        if force:
            cmd.extend(["--force", "--grace-period=0"])
        result = self._run(cmd)
        return result.returncode == 0

    def get_deployment_status(self, service: str) -> Optional[Dict[str, Any]]:
        """Get deployment status: replicas, ready, available."""
        result = self._run([
            "get", "deployment", service, "-o", "json",
        ])
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            spec_replicas = data.get("spec", {}).get("replicas", 0)
            status = data.get("status", {})
            return {
                "desired": spec_replicas,
                "ready": status.get("readyReplicas", 0),
                "available": status.get("availableReplicas", 0),
                "updated": status.get("updatedReplicas", 0),
            }
        except json.JSONDecodeError:
            return None

    def get_resource_yaml(self, kind: str, name: str) -> Optional[str]:
        """Get YAML of a Kubernetes resource."""
        result = self._run(["get", kind, name, "-o", "yaml"])
        if result.returncode == 0:
            return result.stdout
        return None

    def apply_manifest(self, manifest_path: str) -> bool:
        """Apply a kustomize or YAML manifest."""
        result = self._run(["apply", "-k", manifest_path])
        return result.returncode == 0

    def get_pods_for_service(self, service: str) -> List[Dict[str, Any]]:
        """Get all pods for a service with their status."""
        result = self._run([
            "get", "pods",
            "-l", f"app.kubernetes.io/name={service}",
            "-o", "json",
        ])
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout)
            return [
                {
                    "name": item["metadata"]["name"],
                    "phase": item.get("status", {}).get("phase", "Unknown"),
                    "containers": [
                        c["name"] for c in item.get("spec", {}).get("containers", [])
                    ],
                }
                for item in data.get("items", [])
            ]
        except json.JSONDecodeError:
            return []


# ---------------------------------------------------------------------------
# SPIRE API Client
# ---------------------------------------------------------------------------
class SpireApiClient:
    """Client for interacting with SPIRE Server and Agent APIs."""

    def __init__(self, kubectl: KubectlHelper, server_pod: str = "spire-server-0"):
        self.kubectl = kubectl
        self.server_pod = server_pod

    def server_healthcheck(self) -> Tuple[bool, str]:
        """Check SPIRE server health."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            self.server_pod,
            ["/opt/spire/bin/spire-server", "healthcheck"],
            container="spire-server",
        )
        return rc == 0, stdout.strip() or stderr.strip()

    def list_entries(self) -> Optional[str]:
        """List all registration entries."""
        rc, stdout, _ = self.kubectl.exec_in_pod(
            self.server_pod,
            ["/opt/spire/bin/spire-server", "entry", "list"],
            container="spire-server",
        )
        return stdout.strip() if rc == 0 else None

    def show_entry(self, spiffe_id: str) -> Optional[str]:
        """Show a specific registration entry by SPIFFE ID."""
        rc, stdout, _ = self.kubectl.exec_in_pod(
            self.server_pod,
            ["/opt/spire/bin/spire-server", "entry", "show", "-spiffeID", spiffe_id],
            container="spire-server",
        )
        return stdout.strip() if rc == 0 else None

    def create_entry(self, spiffe_id: str, parent_id: str, selector: str) -> Tuple[bool, str]:
        """Create a registration entry in SPIRE server."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            self.server_pod,
            [
                "/opt/spire/bin/spire-server", "entry", "create",
                "-spiffeID", spiffe_id,
                "-parentID", parent_id,
                "-selector", selector,
            ],
            container="spire-server",
        )
        return rc == 0, stdout.strip() or stderr.strip()

    def fetch_workload_svid(self, pod_name: str, socket_path: str = "/run/spire/sockets/agent.sock") -> Optional[str]:
        """Fetch X.509 SVID from the Workload API for a pod."""
        rc, stdout, _ = self.kubectl.exec_in_pod(
            pod_name,
            ["/opt/spire/bin/spire-agent", "api", "fetch", "-socketPath", socket_path],
        )
        return stdout.strip() if rc == 0 else None


# ---------------------------------------------------------------------------
# HTTP Client Factory
# ---------------------------------------------------------------------------
class HttpClientFactory:
    """Factory for creating HTTP clients with proper headers and auth."""

    def __init__(self, gateway_url: str = "http://localhost:8080"):
        self.gateway_url = gateway_url.rstrip("/")

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        service: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
        """Make a GET request through the gateway.

        Returns (status_code, response_body, response_headers).
        """
        import urllib.request
        import urllib.error

        url = f"{self.gateway_url}{path}"
        req_headers = headers or {}
        if service:
            req_headers["X-Target-Service"] = service

        req = urllib.request.Request(url, headers=req_headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8")) if resp.read else {}
                return resp.status, body, dict(resp.headers)
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                body = {"error": str(e)}
            return e.code, body, {}
        except Exception as e:
            return 0, {"error": str(e)}, {}

    def post(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        service: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
        """Make a POST request through the gateway.

        Returns (status_code, response_body, response_headers).
        """
        import urllib.request
        import urllib.error

        url = f"{self.gateway_url}{path}"
        req_headers = headers or {}
        req_headers["Content-Type"] = "application/json"
        if service:
            req_headers["X-Target-Service"] = service

        body_bytes = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = json.loads(resp.read().decode("utf-8")) if resp.read else {}
                return resp.status, resp_body, dict(resp.headers)
        except urllib.error.HTTPError as e:
            try:
                resp_body = json.loads(e.read().decode("utf-8"))
            except Exception:
                resp_body = {"error": str(e)}
            return e.code, resp_body, {}
        except Exception as e:
            return 0, {"error": str(e)}, {}


# ---------------------------------------------------------------------------
# gRPC Channel Factory (with mTLS)
# ---------------------------------------------------------------------------
class GrpcChannelFactory:
    """Factory for creating gRPC channels with mTLS support using SPIFFE SVIDs.

    In production, channels use SVID certificates obtained from the SPIRE
    Workload API. For testing, supports both mTLS and plaintext modes.
    """

    def __init__(self, use_mtls: bool = True, svid_cert_path: Optional[str] = None):
        self.use_mtls = use_mtls
        self.svid_cert_path = svid_cert_path

    def create_channel(self, target: str) -> Any:
        """Create a gRPC channel to the given target.

        Args:
            target: host:port string (e.g., "gateway.production.svc.cluster.local:50051")

        Returns:
            grpc.Channel instance
        """
        try:
            import grpc
        except ImportError:
            pytest.skip("grpcio package not installed")

        if self.use_mtls and self.svid_cert_path:
            # Load SVID certificate and key for mTLS
            cert_path = os.path.join(self.svid_cert_path, "svid.pem")
            key_path = os.path.join(self.svid_cert_path, "svid_key.pem")
            bundle_path = os.path.join(self.svid_cert_path, "bundle.pem")

            if os.path.exists(cert_path) and os.path.exists(key_path):
                with open(cert_path, "rb") as f:
                    cert_chain = f.read()
                with open(key_path, "rb") as f:
                    private_key = f.read()

                root_certificates = None
                if os.path.exists(bundle_path):
                    with open(bundle_path, "rb") as f:
                        root_certificates = f.read()

                credentials = grpc.ssl_channel_credentials(
                    root_certificates=root_certificates,
                    private_key=private_key,
                    certificate_chain=cert_chain,
                )
                return grpc.secure_channel(target, credentials)

        # Fallback: insecure channel (for local development only)
        return grpc.insecure_channel(target)

    def create_channel_with_credentials(
        self,
        target: str,
        root_certificates: bytes,
        private_key: bytes,
        certificate_chain: bytes,
    ) -> Any:
        """Create a gRPC channel with explicit TLS credentials."""
        try:
            import grpc
        except ImportError:
            pytest.skip("grpcio package not installed")

        credentials = grpc.ssl_channel_credentials(
            root_certificates=root_certificates,
            private_key=private_key,
            certificate_chain=certificate_chain,
        )
        return grpc.secure_channel(target, credentials)


# ---------------------------------------------------------------------------
# Kafka Fixture Helpers
# ---------------------------------------------------------------------------
class KafkaHelper:
    """Helper for producing and consuming Kafka messages in E2E tests."""

    def __init__(self, bootstrap_servers: str = KAFKA_BOOTSTRAP):
        self.bootstrap_servers = bootstrap_servers
        self._producer = None
        self._consumers: List[Any] = []

    def get_producer(self) -> Any:
        """Get a Kafka producer instance (lazy initialization)."""
        if self._producer is None:
            try:
                from kafka import KafkaProducer
            except ImportError:
                pytest.skip("kafka-python package not installed")
            self._producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                retries=3,
                retry_backoff_ms=500,
            )
        return self._producer

    def produce(self, topic: str, key: str, value: Dict[str, Any]) -> Any:
        """Produce a message to a Kafka topic. Returns FutureMetadata."""
        producer = self.get_producer()
        future = producer.send(topic, key=key, value=value)
        producer.flush(timeout=30)
        return future

    def create_consumer(
        self,
        topics: List[str],
        group_id: Optional[str] = None,
        auto_offset_reset: str = "earliest",
    ) -> Any:
        """Create and return a Kafka consumer subscribed to the given topics."""
        try:
            from kafka import KafkaConsumer
        except ImportError:
            pytest.skip("kafka-python package not installed")

        group = group_id or f"e2e-test-{uuid.uuid4().hex[:8]}"
        consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=self.bootstrap_servers,
            group_id=group,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            key_deserializer=lambda m: m.decode("utf-8") if m else None,
            consumer_timeout_ms=30000,
            enable_auto_commit=False,
        )
        self._consumers.append(consumer)
        return consumer

    def consume_until(
        self,
        topics: List[str],
        predicate: callable,
        timeout_seconds: int = 30,
        group_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Consume messages until predicate matches or timeout.

        Args:
            topics: Topics to subscribe to
            predicate: Function that takes a message dict and returns True for match
            timeout_seconds: Maximum wait time

        Returns:
            First matching message or None
        """
        consumer = self.create_consumer(topics, group_id=group_id)
        deadline = time.time() + timeout_seconds
        try:
            for message in consumer:
                if message.value and predicate(message.value):
                    return message.value
                if time.time() > deadline:
                    break
        except Exception:
            pass
        finally:
            consumer.close()
        return None

    def close_all(self):
        """Close all producers and consumers."""
        if self._producer:
            self._producer.close()
            self._producer = None
        for consumer in self._consumers:
            try:
                consumer.close()
            except Exception:
                pass
        self._consumers.clear()


# ---------------------------------------------------------------------------
# PostgreSQL Helper
# ---------------------------------------------------------------------------
class PostgresHelper:
    """Helper for PostgreSQL database operations in E2E tests."""

    def __init__(
        self,
        host: str = POSTGRES_HOST,
        port: int = POSTGRES_PORT,
        database: str = POSTGRES_DB,
        user: str = POSTGRES_USER,
        password: str = POSTGRES_PASSWORD,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._connection = None

    def get_connection(self) -> Any:
        """Get a PostgreSQL connection (lazy initialization)."""
        if self._connection is None or self._connection.closed:
            try:
                import psycopg2
            except ImportError:
                pytest.skip("psycopg2 package not installed")
            self._connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.user,
                password=self.password,
                connect_timeout=10,
            )
            self._connection.autocommit = True
        return self._connection

    def execute(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Execute a query and return results as list of dicts."""
        conn = self.get_connection()
        try:
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if cur.description:
                    return [dict(row) for row in cur.fetchall()]
                return []
        except Exception:
            conn.rollback()
            raise

    def execute_one(self, query: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        """Execute a query and return a single row as dict."""
        results = self.execute(query, params)
        return results[0] if results else None

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        result = self.execute_one(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
            (table_name,),
        )
        return result.get("exists", False) if result else False

    def count_rows(self, table_name: str, where: str = "1=1") -> int:
        """Count rows in a table with optional WHERE clause."""
        result = self.execute_one(f"SELECT COUNT(*) as cnt FROM {table_name} WHERE {where}")
        return result.get("cnt", 0) if result else 0

    def close(self):
        """Close the database connection."""
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._connection = None


# ---------------------------------------------------------------------------
# OTel Trace Collector Helper
# ---------------------------------------------------------------------------
class OTelTraceHelper:
    """Helper for querying OTel traces from Tempo and metrics from Prometheus."""

    def __init__(
        self,
        tempo_url: str = TEMPO_URL,
        prometheus_url: str = PROMETHEUS_URL,
        loki_url: str = LOKI_URL,
    ):
        self.tempo_url = tempo_url.rstrip("/")
        self.prometheus_url = prometheus_url.rstrip("/")
        self.loki_url = loki_url.rstrip("/")

    def query_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Query a trace by ID from Tempo."""
        import urllib.request
        import urllib.error

        url = f"{self.tempo_url}/api/traces/{trace_id}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def query_prometheus(self, query: str) -> Optional[Dict[str, Any]]:
        """Execute a PromQL query against Prometheus."""
        import urllib.request
        import urllib.error
        import urllib.parse

        params = urllib.parse.urlencode({"query": query})
        url = f"{self.prometheus_url}/api/v1/query?{params}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def query_prometheus_range(
        self, query: str, start: str, end: str, step: str = "15s"
    ) -> Optional[Dict[str, Any]]:
        """Execute a PromQL range query against Prometheus."""
        import urllib.request
        import urllib.error
        import urllib.parse

        params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
        url = f"{self.prometheus_url}/api/v1/query_range?{params}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def query_loki(self, query: str, limit: int = 100) -> Optional[Dict[str, Any]]:
        """Query Loki logs."""
        import urllib.request
        import urllib.error
        import urllib.parse

        params = urllib.parse.urlencode({"query": query, "limit": limit})
        url = f"{self.loki_url}/loki/api/v1/query_range?{params}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def check_red_metrics(self, service_name: str) -> Dict[str, Any]:
        """Check Rate, Errors, Duration (RED) metrics for a service."""
        result = {
            "service": service_name,
            "rate": None,
            "errors": None,
            "duration_p50": None,
            "duration_p95": None,
            "duration_p99": None,
        }
        # Rate
        rate_resp = self.query_prometheus(
            f'sum(rate(http_server_duration_seconds_count{{service_name="{service_name}"}}[5m]))'
        )
        if rate_resp and rate_resp.get("status") == "success":
            results = rate_resp.get("data", {}).get("result", [])
            if results:
                result["rate"] = float(results[0].get("value", [0, "0"])[1])

        # Errors
        err_resp = self.query_prometheus(
            f'sum(rate(http_server_duration_seconds_count{{service_name="{service_name}",http.status_code=~"5.."}}[5m]))'
        )
        if err_resp and err_resp.get("status") == "success":
            results = err_resp.get("data", {}).get("result", [])
            if results:
                result["errors"] = float(results[0].get("value", [0, "0"])[1])

        # Duration percentiles
        for p, key in [(50, "duration_p50"), (95, "duration_p95"), (99, "duration_p99")]:
            dur_resp = self.query_prometheus(
                f'histogram_quantile(0.{p:02d}, sum(rate(http_server_duration_seconds_bucket{{service_name="{service_name}"}}[5m])) by (le))'
            )
            if dur_resp and dur_resp.get("status") == "success":
                results = dur_resp.get("data", {}).get("result", [])
                if results:
                    result[key] = float(results[0].get("value", [0, "0"])[1])

        return result

    def check_alert_rules(self) -> List[Dict[str, Any]]:
        """Check Prometheus alert rules and their firing state."""
        import urllib.request

        url = f"{self.prometheus_url}/api/v1/alerts"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("data", {}).get("alerts", [])
        except Exception:
            return []

    def check_grafana_dashboards(self) -> List[Dict[str, Any]]:
        """List Grafana dashboards and verify data availability."""
        import urllib.request

        url = f"{GRAFANA_URL}/api/search?type=dash-db"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Wait-for-Service Readiness Helpers
# ---------------------------------------------------------------------------
def wait_for_service_ready(
    service_name: str,
    timeout: int = DEFAULT_READINESS_TIMEOUT,
    interval: int = DEFAULT_READINESS_INTERVAL,
    kubectl: Optional[KubectlHelper] = None,
) -> bool:
    """Wait for a service to become ready by checking its health endpoint.

    Uses kubectl port-forward to reach the service health endpoint.
    Falls back to checking pod readiness if port-forward is unavailable.

    Returns True if service becomes ready within timeout, False otherwise.
    """
    kubectl = kubectl or KubectlHelper()
    deadline = time.time() + timeout

    while time.time() < deadline:
        # Check deployment has ready replicas
        status = kubectl.get_deployment_status(service_name)
        if status and status.get("ready", 0) >= 1:
            return True

        # Try direct health check via pod exec
        pod_name = kubectl.get_pod_name(service_name)
        if pod_name:
            rc, stdout, _ = kubectl.exec_in_pod(
                pod_name, ["curl", "-sf", "http://localhost:8080/healthz"]
            )
            if rc == 0:
                return True

        time.sleep(interval)

    return False


def wait_for_all_services_ready(
    services: Optional[List[str]] = None,
    timeout: int = DEFAULT_READINESS_TIMEOUT,
    interval: int = DEFAULT_READINESS_INTERVAL,
    kubectl: Optional[KubectlHelper] = None,
) -> Dict[str, bool]:
    """Wait for all services to become ready.

    Returns a dict mapping service name -> ready (bool).
    """
    services = services or ALL_SERVICES
    results = {}
    for svc in services:
        results[svc] = wait_for_service_ready(svc, timeout, interval, kubectl)
    return results


def wait_for_kafka_topic(
    topic_name: str,
    bootstrap_servers: str = KAFKA_BOOTSTRAP,
    timeout: int = 60,
    interval: int = 5,
) -> bool:
    """Wait for a Kafka topic to exist."""
    try:
        from kafka import KafkaAdminClient
    except ImportError:
        pytest.skip("kafka-python package not installed")

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers)
            topics = admin.list_topics()
            admin.close()
            if topic_name in topics:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def wait_for_condition(
    predicate: callable,
    timeout: int = DEFAULT_READINESS_TIMEOUT,
    interval: int = DEFAULT_READINESS_INTERVAL,
    message: str = "Condition not met within timeout",
) -> bool:
    """Generic wait-for-condition helper with retry and timeout.

    Args:
        predicate: Callable that returns True when condition is met
        timeout: Maximum wait time in seconds
        interval: Time between retries in seconds
        message: Error message on timeout

    Returns:
        True if condition met within timeout

    Raises:
        TimeoutError if condition not met
    """
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception as e:
            last_error = e
        time.sleep(interval)
    raise TimeoutError(f"{message} (last error: {last_error})")


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def project_root() -> Path:
    """Provide the project root path."""
    return Path(__file__).parent.parent.parent


@pytest.fixture(scope="session")
def kubectl() -> KubectlHelper:
    """Provide a kubectl helper for the test session."""
    return KubectlHelper(namespace=NAMESPACE)


@pytest.fixture(scope="session")
def spire_client(kubectl: KubectlHelper) -> SpireApiClient:
    """Provide a SPIRE API client for the test session."""
    return SpireApiClient(kubectl=kubectl)


@pytest.fixture(scope="session")
def http_client_factory() -> HttpClientFactory:
    """Provide an HTTP client factory for the test session."""
    gateway_url = os.getenv("E2E_GATEWAY_URL", f"http://localhost:{GATEWAY_HTTP_PORT}")
    return HttpClientFactory(gateway_url=gateway_url)


@pytest.fixture(scope="session")
def grpc_channel_factory() -> GrpcChannelFactory:
    """Provide a gRPC channel factory for the test session."""
    svid_path = os.getenv("E2E_SVID_PATH")
    use_mtls = os.getenv("E2E_USE_MTLS", "true").lower() == "true"
    return GrpcChannelFactory(use_mtls=use_mtls, svid_cert_path=svid_path)


@pytest.fixture(scope="session")
def kafka_helper() -> Generator[KafkaHelper, None, None]:
    """Provide a Kafka helper for the test session. Closes on teardown."""
    helper = KafkaHelper(bootstrap_servers=KAFKA_BOOTSTRAP)
    yield helper
    helper.close_all()


@pytest.fixture(scope="session")
def postgres_helper() -> Generator[PostgresHelper, None, None]:
    """Provide a PostgreSQL helper for the test session. Closes on teardown."""
    helper = PostgresHelper()
    yield helper
    helper.close()


@pytest.fixture(scope="session")
def otel_helper() -> OTelTraceHelper:
    """Provide an OTel trace/metrics helper for the test session."""
    return OTelTraceHelper()


@pytest.fixture(scope="session")
def service_registry() -> Dict[str, Dict[str, Any]]:
    """Provide the service registry for the test session."""
    return SERVICE_REGISTRY


@pytest.fixture(scope="session")
def all_services() -> List[str]:
    """Provide the list of all service names."""
    return ALL_SERVICES


@pytest.fixture(scope="session")
def infra_k8s_base(project_root: Path) -> Path:
    """Provide the path to infra/kubernetes/base."""
    return project_root / "infra" / "kubernetes" / "base"


@pytest.fixture(scope="session")
def infra_k8s_platform(project_root: Path) -> Path:
    """Provide the path to infra/kubernetes/platform."""
    return project_root / "infra" / "kubernetes" / "platform"


@pytest.fixture(scope="session")
def infra_k8s_production(project_root: Path) -> Path:
    """Provide the path to infra/kubernetes/overlays/production."""
    return project_root / "infra" / "kubernetes" / "overlays" / "production"


@pytest.fixture(scope="session")
def schemas_proto_root(project_root: Path) -> Path:
    """Provide the path to schemas/proto."""
    return project_root / "schemas" / "proto"


@pytest.fixture(scope="session")
def services_root(project_root: Path) -> Path:
    """Provide the path to services/."""
    return project_root / "services"


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def unique_id() -> str:
    """Generate a unique identifier for test isolation."""
    return f"e2e-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def test_customer_id(unique_id: str) -> str:
    """Generate a unique customer ID for testing."""
    return f"cust-{unique_id}"


@pytest.fixture
def test_order_id(unique_id: str) -> str:
    """Generate a unique order ID for testing."""
    return f"ord-{unique_id}"


@pytest.fixture
def test_product_id(unique_id: str) -> str:
    """Generate a unique product ID for testing."""
    return f"prod-{unique_id}"


@pytest.fixture
def test_timestamp() -> str:
    """Generate an ISO 8601 timestamp for the current time."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pytest Configuration
# ---------------------------------------------------------------------------
def pytest_configure(config):
    """Register custom markers for E2E test suite."""
    markers = [
        "e2e: marks tests as end-to-end integration tests (require full cluster)",
        "saga: marks tests as order saga E2E tests",
        "cdc: marks tests as CDC pipeline E2E tests",
        "discovery: marks tests as service discovery E2E tests",
        "observability: marks tests as observability stack E2E tests",
        "resilience: marks tests as cross-service resilience E2E tests",
        "security: marks tests as security E2E tests",
        "slow: marks tests as slow (>60s expected runtime)",
        "destructive: marks tests that modify cluster state (scale down, kill pods)",
        "offline: marks tests that can run without a live cluster (manifest validation)",
    ]
    for marker in markers:
        config.addinivalue_line("markers", marker)
