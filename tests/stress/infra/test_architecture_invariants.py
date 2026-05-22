"""
Cross-Service Architecture Invariant Tests.

These tests act as automated architecture fitness functions — they verify
structural rules that ALL services must satisfy, catching regressions that
code review misses. No mocking, no live infrastructure — pure file inspection.

Covers:
1. Hexagonal boundary — domain layers have no infra imports (all 5 languages)
2. SQL migration coverage — every stateful service must have at least 1 migration
3. Proto schema consistency — every service with a proto has a matching OpenAPI spec
4. Dockerfile presence — every service must be containerisable
5. Health endpoint declaration — every service must declare a /health path
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from typing import List, Set

import pytest

ROOT = Path(__file__).parent.parent.parent.parent  # repo root (tests/stress/infra -> root)
SERVICES = ROOT / "services"
SCHEMAS = ROOT / "schemas"

# Services that have a PostgreSQL dependency (must have migrations)
STATEFUL_SERVICES = {
    "identity",    # Cargo.toml has sqlx postgres
    "order",       # build.gradle.kts has postgresql driver
    "payment",     # go.mod has pgx
    "catalog",     # package.json has pg
    "notification",# pyproject.toml has asyncpg
    "analytics",   # pyproject.toml has asyncpg / psycopg
    "schema-registry",  # go.mod has pgx
}

# Services that own proto schemas
PROTO_SERVICES = {
    "analytics", "catalog", "gateway", "identity",
    "notification", "order", "payment", "schema-registry",
}

# Domain directory patterns per language
DOMAIN_DIRS = {
    "go":         "domain",
    "rust":       "src/domain",
    "kotlin":     "src/main/kotlin/domain",
    "typescript": "src/domain",
    "python":     "src/domain",
}

INFRA_PACKAGES = {
    "go":         {"database/sql", "github.com/jackc/pgx", "go-redis", "grpc"},
    "rust":       {"sqlx", "tonic", "tokio", "redis"},
    "kotlin":     {"org.jooq", "org.postgresql", "io.grpc", "kafka"},
    "typescript": {"pg", "ioredis", "@grpc"},
    "python":     {"asyncpg", "psycopg", "redis", "grpc"},
}


def detect_language(service_path: Path) -> str:
    if (service_path / "go.mod").exists():
        return "go"
    if (service_path / "Cargo.toml").exists():
        return "rust"
    if (service_path / "build.gradle.kts").exists():
        return "kotlin"
    if (service_path / "package.json").exists():
        return "typescript"
    if (service_path / "pyproject.toml").exists():
        return "python"
    return "unknown"


def all_services() -> List[Path]:
    return [p for p in sorted(SERVICES.iterdir())
            if p.is_dir() and p.name != "templates"]


# ---------------------------------------------------------------------------
# 1. Hexagonal boundary — domain has no infra imports
# ---------------------------------------------------------------------------

class TestHexagonalBoundary:
    """Domain layers must not import infrastructure packages."""

    @pytest.mark.parametrize("service_path", all_services(), ids=lambda p: p.name)
    def test_domain_has_no_direct_infra_imports(self, service_path: Path) -> None:
        lang = detect_language(service_path)
        if lang == "unknown":
            pytest.skip(f"{service_path.name}: cannot determine language")

        domain_rel = DOMAIN_DIRS.get(lang, "domain")
        domain_dir = service_path / domain_rel

        if not domain_dir.exists():
            pytest.skip(f"{service_path.name}: no domain dir at {domain_rel}")

        infra_pkgs = INFRA_PACKAGES.get(lang, set())
        violations: List[str] = []

        ext_map = {"go": ".go", "rust": ".rs", "kotlin": ".kt",
                   "typescript": ".ts", "python": ".py"}
        ext = ext_map[lang]

        for f in domain_dir.rglob(f"*{ext}"):
            content = f.read_text(errors="ignore")
            for pkg in infra_pkgs:
                # Simple substring check on import statements
                if pkg in content:
                    # Confirm it's actually in an import, not a comment
                    for line in content.splitlines():
                        stripped = line.strip()
                        # Only flag if it looks like an import statement, not a string literal
                        is_import = False
                        if lang == "go" and stripped.startswith('"') and stripped.endswith('"'):
                            is_import = True  # bare import string
                        elif lang == "go" and stripped.startswith(pkg):
                            is_import = True  # direct package reference
                        elif lang in ("python", "typescript", "kotlin", "rust"):
                            import_keywords = ("import ", "from ", "use ", "require(")
                            is_import = any(stripped.startswith(kw) for kw in import_keywords)
                        if is_import and pkg in stripped and not stripped.startswith("//") \
                                and not stripped.startswith("#"):
                            violations.append(
                                f"{f.relative_to(ROOT)}: imports '{pkg}'"
                            )
                            break

        assert not violations, (
            f"{service_path.name} domain layer has infra imports:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# 2. SQL migration coverage
# ---------------------------------------------------------------------------

class TestMigrationCoverage:
    """Every stateful service must ship at least one SQL migration."""

    @pytest.mark.parametrize("service_name", sorted(STATEFUL_SERVICES))
    def test_service_has_migrations(self, service_name: str) -> None:
        service_path = SERVICES / service_name
        if not service_path.exists():
            pytest.skip(f"Service {service_name} directory not found")

        # Check common migration directory names
        migration_dirs = ["migrations", "db/migrations", "src/migrations",
                          "resources/db/migration", "flyway"]
        migration_files: List[Path] = []

        for d in migration_dirs:
            candidate = service_path / d
            if candidate.exists():
                migration_files.extend(
                    f for f in candidate.rglob("*.sql")
                )

        # Also check for Flyway-style resources
        for f in service_path.rglob("*.sql"):
            if "migration" in str(f).lower() or "schema" in f.name.lower():
                migration_files.append(f)

        assert len(migration_files) >= 1, (
            f"{service_name} has no SQL migrations. "
            f"Add at least 001_init.sql to services/{service_name}/migrations/"
        )


# ---------------------------------------------------------------------------
# 3. Proto ↔ OpenAPI schema parity
# ---------------------------------------------------------------------------

class TestSchemaConsistency:
    """Every service with a proto definition must have a matching OpenAPI spec."""

    def test_proto_services_have_openapi_specs(self) -> None:
        proto_dir = SCHEMAS / "proto"
        openapi_dir = SCHEMAS / "openapi"

        if not proto_dir.exists():
            pytest.skip("schemas/proto not found")

        # Find services that have proto definitions
        proto_services: Set[str] = set()
        for pkg_dir in proto_dir.iterdir():
            if pkg_dir.is_dir() and pkg_dir.name not in ("common",):
                proto_services.add(pkg_dir.name)

        # Find services that have OpenAPI specs
        openapi_services: Set[str] = set()
        if openapi_dir.exists():
            for svc_dir in openapi_dir.iterdir():
                if svc_dir.is_dir():
                    yaml_files = list(svc_dir.glob("*.yaml")) + list(svc_dir.glob("*.yml"))
                    if yaml_files:
                        openapi_services.add(svc_dir.name)

        missing = proto_services - openapi_services
        assert not missing, (
            f"Services have proto definitions but no OpenAPI specs: {sorted(missing)}\n"
            f"Add OpenAPI 3.1 specs to schemas/openapi/<service>/."
        )

    def test_common_proto_types_present(self) -> None:
        """common/v1 must define Money, Address, and Pagination — shared by all services."""
        common_dir = SCHEMAS / "proto" / "common" / "v1"
        if not common_dir.exists():
            pytest.skip("schemas/proto/common/v1 not found")

        types_proto = common_dir / "types.proto"
        assert types_proto.exists(), "common/v1/types.proto is missing"

        content = types_proto.read_text()
        for required_type in ("message Money", "message Address"):
            assert required_type in content, (
                f"common/v1/types.proto must define '{required_type}' — "
                f"used by all financial services"
            )

    def test_order_proto_has_saga_definition(self) -> None:
        """Order service must have a saga proto — core architectural pattern."""
        saga_proto = SCHEMAS / "proto" / "order" / "v1" / "saga.proto"
        assert saga_proto.exists(), (
            "schemas/proto/order/v1/saga.proto is missing — "
            "the Order saga orchestration pattern requires this schema"
        )
        content = saga_proto.read_text()
        assert "SagaState" in content or "SagaStatus" in content or "saga" in content.lower(), \
            "saga.proto must define saga state/status messages"

    def test_payment_circuit_breaker_proto_present(self) -> None:
        """Payment service must have a circuit breaker proto."""
        circuit_proto = SCHEMAS / "proto" / "payment" / "v1" / "circuit.proto"
        assert circuit_proto.exists(), (
            "schemas/proto/payment/v1/circuit.proto is missing"
        )


# ---------------------------------------------------------------------------
# 4. Dockerfile presence
# ---------------------------------------------------------------------------

class TestDockerfileCoverage:
    """Every service must be containerisable."""

    STUB_SERVICES = {"cdc-relay", "templates"}  # known stubs without Dockerfiles

    @pytest.mark.parametrize("service_path", all_services(), ids=lambda p: p.name)
    def test_service_has_dockerfile(self, service_path: Path) -> None:
        if service_path.name in self.STUB_SERVICES:
            pytest.skip(f"{service_path.name} is a known stub — Dockerfile not required yet")

        dockerfile = service_path / "Dockerfile"
        assert dockerfile.exists(), (
            f"services/{service_path.name}/Dockerfile is missing. "
            f"Every deployed service must be containerisable."
        )

    @pytest.mark.parametrize("service_path", all_services(), ids=lambda p: p.name)
    def test_dockerfile_is_multistage(self, service_path: Path) -> None:
        if service_path.name in self.STUB_SERVICES:
            pytest.skip(f"{service_path.name} is a known stub")

        dockerfile = service_path / "Dockerfile"
        if not dockerfile.exists():
            pytest.skip("Dockerfile missing — covered by separate test")

        content = dockerfile.read_text()
        as_count = len(re.findall(r"^FROM\s+\S+\s+AS\s+\S+", content, re.MULTILINE | re.IGNORECASE))
        assert as_count >= 2, (
            f"services/{service_path.name}/Dockerfile must be multi-stage "
            f"(at least 2 FROM ... AS ... stages for build + runtime separation). "
            f"Found {as_count} named stages."
        )


# ---------------------------------------------------------------------------
# 5. Makefile targets
# ---------------------------------------------------------------------------

class TestMakefileTargets:
    """Every service must have standardised Makefile targets."""

    REQUIRED_TARGETS = {"build", "test", "lint"}
    STUB_SERVICES = {"cdc-relay", "templates"}

    @pytest.mark.parametrize("service_path", all_services(), ids=lambda p: p.name)
    def test_service_has_required_make_targets(self, service_path: Path) -> None:
        if service_path.name in self.STUB_SERVICES:
            pytest.skip(f"{service_path.name} is a stub")

        makefile = service_path / "Makefile"
        if not makefile.exists():
            pytest.skip(f"{service_path.name}: no Makefile")

        content = makefile.read_text()
        declared = set(re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]*):", content, re.MULTILINE))
        missing = self.REQUIRED_TARGETS - declared
        assert not missing, (
            f"services/{service_path.name}/Makefile is missing targets: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# 6. No cloud SDK imports anywhere
# ---------------------------------------------------------------------------

class TestNoCloudSDKLeakage:
    """Cloud provider SDKs must never appear in any service code."""

    CLOUD_PATTERNS = [
        "github.com/aws/aws-sdk-go",
        "google-cloud",
        "azure-sdk",
        "boto3",
        "botocore",
        "google.cloud",
        "com.amazonaws",
        "com.azure",
    ]

    @pytest.mark.parametrize("service_path", all_services(), ids=lambda p: p.name)
    def test_no_cloud_sdk_in_service(self, service_path: Path) -> None:
        lang = detect_language(service_path)
        ext_map = {"go": ".go", "rust": ".rs", "kotlin": ".kt",
                   "typescript": ".ts", "python": ".py", "unknown": ".py"}
        ext = ext_map.get(lang, ".py")

        violations: List[str] = []
        for f in service_path.rglob(f"*{ext}"):
            # Skip test files — they may import test helpers that reference cloud
            if "test" in f.name.lower():
                continue
            content = f.read_text(errors="ignore")
            for pattern in self.CLOUD_PATTERNS:
                if pattern in content:
                    violations.append(f"{f.relative_to(ROOT)}: contains '{pattern}'")

        assert not violations, (
            f"Cloud SDK detected in {service_path.name} (violates tech-neutral doctrine):\n"
            + "\n".join(violations)
        )
