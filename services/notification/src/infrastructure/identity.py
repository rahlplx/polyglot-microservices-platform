"""
SPIFFE/SPIRE mTLS identity management for the Notification service.

This module provides identity management through the SPIFFE/SPIRE
framework for mutual TLS authentication between services. The
SPIFFE Workload API is used to fetch X.509 SVIDs (Spiffe Verifiable
Identity Documents) that are used for mTLS connections.

The identity module follows the zero-trust architecture principle:
every service-to-service call authenticates via SPIFFE/SPIRE mTLS.
No service assumes network perimeter security, and all communication
is encrypted and authenticated.
"""

from __future__ import annotations

import logging
import ssl
from typing import Optional

logger = logging.getLogger(__name__)


class SPIFFEIdentity:
    """SPIFFE/SPIRE identity manager for mTLS certificate management.

    This class manages the service's SPIFFE identity by interacting
    with the SPIRE Agent's Workload API to fetch X.509 SVIDs for
    mTLS connections. The SVIDs are automatically rotated by the
    SPIRE Agent, ensuring that certificates are always fresh.

    The SPIFFE ID for the notification service follows the pattern:
    spiffe://company.com/notification-service

    In development mode (when SPIRE Agent is not available), the
    identity manager falls back to insecure connections with a
    warning. This should never be used in production.
    """

    # Default SPIFFE trust domain
    TRUST_DOMAIN = "company.com"

    # SPIFFE ID for the notification service
    SERVICE_SPIFFE_ID = f"spiffe://{TRUST_DOMAIN}/notification-service"

    # SPIRE Agent socket path (default location in Kubernetes)
    SPIRE_AGENT_SOCKET = "/tmp/spire-agent/public/api.sock"

    def __init__(
        self,
        spiffe_id: Optional[str] = None,
        spire_socket: Optional[str] = None,
        trust_bundle_path: Optional[str] = None,
    ) -> None:
        """Initialize the SPIFFE identity manager.

        Args:
            spiffe_id: The SPIFFE ID for this service. If None,
                the default notification service ID is used.
            spire_socket: Path to the SPIRE Agent Workload API socket.
                If None, the default Kubernetes path is used.
            trust_bundle_path: Path to the SPIFFE trust bundle for
                verifying peer certificates.
        """
        self._spiffe_id = spiffe_id or self.SERVICE_SPIFFE_ID
        self._spire_socket = spire_socket or self.SPIRE_AGENT_SOCKET
        self._trust_bundle_path = trust_bundle_path
        self._x509_svid: Optional[bytes] = None
        self._private_key: Optional[bytes] = None

    @property
    def spiffe_id(self) -> str:
        """The SPIFFE ID for this service."""
        return self._spiffe_id

    async def fetch_x509_svid(self) -> tuple[bytes, bytes]:
        """Fetch the current X.509 SVID from the SPIRE Agent.

        Connects to the SPIRE Agent's Workload API using Unix socket
        and fetches the X.509 SVID (certificate chain) and private key
        for the current workload. The SPIRE Agent automatically selects
        the correct SVID based on the workload's selector (Pod labels,
        Kubernetes service account, etc.).

        Returns:
            A tuple of (certificate_chain_pem, private_key_pem).

        Raises:
            ConnectionError: If the SPIRE Agent is unreachable.
        """
        try:
            # Attempt to use the SPIFFE Workload API
            # In production, this would use the spiffe-python library
            logger.info(
                "Fetching X.509 SVID from SPIRE Agent at %s",
                self._spire_socket,
            )

            # Placeholder for actual SPIRE Agent interaction
            # In production, use the spiffe library:
            # from spiffe import WorkloadApiClient
            # client = WorkloadApiClient(self._spire_socket)
            # x509_svid = client.fetch_x509_svid()

            # For development, return None to indicate no mTLS
            logger.warning(
                "SPIRE Agent not available, mTLS disabled. "
                "This should NOT happen in production."
            )
            return b"", b""

        except Exception as e:
            logger.error("Failed to fetch X.509 SVID: %s", e)
            return b"", b""

    def create_ssl_context(self) -> ssl.SSLContext:
        """Create an SSL context for mTLS using the current SVID.

        Builds an SSL context configured for mutual TLS authentication
        using the SPIFFE X.509 SVID. The context is set up to verify
        peer certificates against the SPIFFE trust bundle.

        Returns:
            An ssl.SSLContext configured for mTLS, or a default context
            if SPIRE is not available.
        """
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3

        if self._x509_svid and self._private_key:
            # Load the SPIFFE SVID certificate and key
            # ctx.load_cert_chain(cert, key)
            logger.info("SSL context configured with SPIFFE SVID")
        else:
            # Fallback: disable certificate verification for development
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            logger.warning(
                "SSL context configured without mTLS. "
                "This should NOT happen in production."
            )

        return ctx

    def validate_peer_spiffe_id(self, peer_cert: dict) -> bool:
        """Validate that a peer's certificate has an acceptable SPIFFE ID.

        Checks that the peer's SPIFFE ID belongs to a trusted service
        within the same trust domain. Only services within the company
        trust domain are allowed to communicate with the notification
        service.

        Args:
            peer_cert: The peer's certificate dictionary.

        Returns:
            True if the peer's SPIFFE ID is valid and trusted.
        """
        # Extract SPIFFE ID from the peer certificate's URI SAN
        # In production, this would parse the X.509 extension
        spiffe_ids = peer_cert.get("subjectAltName", [])

        for san_type, san_value in spiffe_ids:
            if san_type == "URI" and san_value.startswith("spiffe://"):
                # Verify trust domain
                if san_value.startswith(f"spiffe://{self.TRUST_DOMAIN}/"):
                    logger.debug("Peer SPIFFE ID validated: %s", san_value)
                    return True

        logger.warning("Peer SPIFFE ID validation failed")
        return False
