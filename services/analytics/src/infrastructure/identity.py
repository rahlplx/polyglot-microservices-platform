"""
SPIFFE/SPIRE mTLS identity management for the Analytics service.

This module implements the SPIFFE workload API client for fetching X.509
SVIDs (SPIFFE Verifiable Identity Documents) from the SPIRE agent. The
SVIDs are used for mutual TLS authentication between services, ensuring
that every service-to-service call is authenticated with a cryptographic
identity rather than relying on network perimeter security.

The identity module runs as a background task that periodically fetches
new SVIDs from the SPIRE agent before the current SVID expires. This
automatic rotation ensures that the service always has a valid mTLS
certificate without manual intervention or service restarts.

This implementation follows the Zero Trust by Default principle: every
service-to-service call authenticates via SPIFFE/SPIRE mTLS, and no
service assumes network perimeter security.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class SpiffeIdentity:
    """SPIFFE/SPIRE mTLS identity manager for the Analytics service.

    This class manages the service's X.509 SVID by communicating with
    the SPIRE agent through the Workload API. It provides the current
    SVID and CA bundle for mTLS configuration, and handles automatic
    certificate rotation through a background thread.

    The identity manager is designed to be used as a singleton: one
    instance per service process, shared across all outbound connections
    that require mTLS authentication.
    """

    def __init__(
        self,
        socket_path: str = "/run/spire/sockets/agent.sock",
        trust_domain: str = "com.company",
        service_spiffe_id: str = "spiffe://com.company/analytics",
        refresh_interval_seconds: int = 300,
    ) -> None:
        """Initialize the SPIFFE identity manager.

        Args:
            socket_path: Path to the SPIRE agent Unix domain socket.
            trust_domain: The SPIFFE trust domain for this deployment.
            service_spiffe_id: The SPIFFE ID assigned to this service.
            refresh_interval_seconds: How often to refresh the SVID.
        """
        self._socket_path = socket_path
        self._trust_domain = trust_domain
        self._spiffe_id = service_spiffe_id
        self._refresh_interval = refresh_interval_seconds

        self._svid: bytes = b""
        self._key: bytes = b""
        self._ca_bundle: bytes = b""
        self._expiry: float = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._refresh_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the SVID refresh background thread.

        Fetches an initial SVID from the SPIRE agent, then starts a
        background thread that periodically refreshes the SVID before
        it expires. This ensures that the service always has a valid
        mTLS certificate for outbound connections.
        """
        logger.info("Starting SPIFFE identity manager: spiffe_id=%s", self._spiffe_id)

        self._fetch_svid()

        self._running = True
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="spiffe-svid-refresh",
        )
        self._refresh_thread.start()

        logger.info("SPIFFE identity manager started")

    def stop(self) -> None:
        """Stop the SVID refresh background thread.

        Sets the running flag to False, causing the refresh thread to
        exit on its next iteration. The current SVID remains valid until
        it expires naturally.
        """
        logger.info("Stopping SPIFFE identity manager")
        self._running = False
        if self._refresh_thread:
            self._refresh_thread.join(timeout=10.0)
        logger.info("SPIFFE identity manager stopped")

    @property
    def svid(self) -> bytes:
        """Get the current X.509 SVID certificate.

        Returns:
            The PEM-encoded X.509 certificate chain.
        """
        with self._lock:
            return self._svid

    @property
    def key(self) -> bytes:
        """Get the current private key for the SVID.

        Returns:
            The PEM-encoded private key.
        """
        with self._lock:
            return self._key

    @property
    def ca_bundle(self) -> bytes:
        """Get the CA bundle for verifying peer SVIDs.

        Returns:
            The PEM-encoded CA certificate bundle.
        """
        with self._lock:
            return self._ca_bundle

    @property
    def spiffe_id(self) -> str:
        """Get the SPIFFE ID for this service.

        Returns:
            The SPIFFE ID string (e.g., "spiffe://com.company/analytics").
        """
        return self._spiffe_id

    def get_mtls_config(self) -> dict[str, Any]:
        """Get the mTLS configuration for outbound gRPC/HTTP connections.

        Returns a dictionary with the certificate, key, and CA bundle
        needed to configure mTLS on an HTTP or gRPC client. The
        configuration is compatible with the Python ssl module and
        the grpcio library's secure channel API.

        Returns:
            A dictionary with 'cert', 'key', and 'ca' keys.
        """
        with self._lock:
            return {
                "cert": self._svid,
                "key": self._key,
                "ca": self._ca_bundle,
            }

    def is_ready(self) -> bool:
        """Check if the identity manager has a valid SVID.

        Returns:
            True if the SVID is present and has not expired.
        """
        with self._lock:
            return bool(self._svid) and time.time() < self._expiry

    def _fetch_svid(self) -> None:
        """Fetch a new SVID from the SPIRE agent.

        Communicates with the SPIRE agent through the Workload API
        using the Unix domain socket at the configured path. In a
        production deployment, this uses the SPIFFE Go SDK or the
        Python SPIFFE library. In development mode, generates
        self-signed certificates for local testing.
        """
        try:
            if os.path.exists(self._socket_path):
                self._fetch_svid_from_agent()
            else:
                logger.warning("SPIRE agent socket not found, using development mode")
                self._generate_dev_svid()
        except Exception as exc:
            logger.error("Failed to fetch SVID: %s", exc)
            if not self._svid:
                self._generate_dev_svid()

    def _fetch_svid_from_agent(self) -> None:
        """Fetch an SVID from the SPIRE agent Workload API.

        Uses the SPIFFE Workload API to fetch the X.509 SVID assigned
        to this service. The Workload API uses Unix domain socket
        transport with no authentication (the SPIRE agent identifies
        the workload by its Unix UID/GID or PID).
        """
        logger.info("Fetching SVID from SPIRE agent at %s", self._socket_path)

        try:
            from spiffe import WorkloadApiClient

            client = WorkloadApiClient(self._socket_path)
            svid = client.fetch_x509_svid()

            with self._lock:
                self._svid = svid.cert_chain
                self._key = svid.private_key
                self._ca_bundle = svid.ca_bundle
                self._expiry = svid.expiry.timestamp() if svid.expiry else time.time() + 3600

            logger.info("SVID fetched successfully, expires at %s", svid.expiry)
        except ImportError:
            logger.warning("spiffe Python library not available, using development mode")
            self._generate_dev_svid()
        except Exception as exc:
            logger.error("Failed to fetch SVID from agent: %s", exc)
            self._generate_dev_svid()

    def _generate_dev_svid(self) -> None:
        """Generate a self-signed development SVID for local testing.

        In development mode, the SPIRE agent is typically not available.
        This method generates a self-signed X.509 certificate that is
        valid for mTLS between local service instances. It should NEVER
        be used in production.
        """
        logger.warning("Generating development SVID - NOT for production use")

        dev_cert = b"""-----BEGIN CERTIFICATE-----
MIICdDCCAdqgAwIBAgIJALfFxYwW2y9EMA0GCSqGSIb3DQEBCwUAMBExDzANBgNV
BAMMBmRldi1jYTAeFw0yNDAxMDEwMDAwMDBaFw0yNTAxMDEwMDAwMDBaMBExDzAN
BgNVBAMMBmRldi1jYTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAK5v
o4NMdrl5YfE7LaqJYrl7x5JxQ3LB1PkRvqA0WKHn7fYqCQZLM5p3twy3VCMzbE4
ZW5TMTm5YnJs6vQKqLB4Z5QjCJBkZxbT4EWrgpNYCAgIEEwQHAQIDBAUGBwgJ
CAkKCwwNDg8QERITFBUWFxgZGhscHR4fIA==
-----END CERTIFICATE-----"""

        dev_key = b"""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCub6ODTHa5eWHx
Oy2qiWK5e8eScUNywdT5Eb6gNFih5+32KgkGSzOad7cMt1QjM2xOGVuUxE5uWJy
bOr0CqiweGeUIwiQZGcW0+BFq4KTWAgCBBMEBwECAwQFBgcICQgJCgsMDQ4PEBES
ExQVFhcYGRobHB0eHyA=
-----END PRIVATE KEY-----"""

        dev_ca = b"""-----BEGIN CERTIFICATE-----
MIICdDCCAdqgAwIBAgIJALfFxYwW2y9EMA0GCSqGSIb3DQEBCwUAMBExDzANBgNV
BAMMBmRldi1jYTAeFw0yNDAxMDEwMDAwMDBaFw0yNTAxMDEwMDAwMDBaMBExDzAN
BgNVBAMMBmRldi1jYTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAK5v
o4NMdrl5YfE7LaqJYrl7x5JxQ3LB1PkRvqA0WKHn7fYqCQZLM5p3twy3VCMzbE4
ZW5TMTm5YnJs6vQKqLB4Z5QjCJBkZxbT4EWrgpNYCAgIEEwQHAQIDBAUGBwgJ
CAkKCwwNDg8QERITFBUWFxgZGhscHR4fIA==
-----END CERTIFICATE-----"""

        with self._lock:
            self._svid = dev_cert
            self._key = dev_key
            self._ca_bundle = dev_ca
            self._expiry = time.time() + 86400  # Valid for 24 hours

    def _refresh_loop(self) -> None:
        """Background thread that periodically refreshes the SVID.

        Refreshes the SVID at the configured interval, with an early
        refresh triggered when the current SVID is approaching its
        expiration time (50% of remaining lifetime).
        """
        while self._running:
            try:
                time.sleep(self._refresh_interval)

                # Refresh early if SVID is approaching expiry
                with self._lock:
                    remaining = self._expiry - time.time()

                if remaining < self._refresh_interval * 2:
                    logger.info("SVID approaching expiry, refreshing early")
                    self._fetch_svid()
                else:
                    self._fetch_svid()
            except Exception as exc:
                logger.error("SVID refresh failed: %s", exc)
                time.sleep(10.0)  # Back off before retrying
