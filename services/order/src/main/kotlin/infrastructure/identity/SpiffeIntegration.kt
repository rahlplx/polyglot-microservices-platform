package com.company.order.infrastructure.identity

import io.spiffe.api.SpiffeClient
import io.spiffe.api.SpiffeClientSettings
import io.spiffe.core.DefaultSpiffeClient
import io.spiffe.svid.jvm.JvmSvid
import io.spiffe.svid.jvm.JvmSvidStore
import io.spiffe.tls.SpiffeTlsContext
import io.spiffe.workloadapi.DefaultWorkloadApiClient
import io.spiffe.workloadapi.WorkloadApiClient
import org.slf4j.LoggerFactory
import java.io.Closeable
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * SPIFFE/SPIRE integration for the Order service.
 *
 * Provides workload identity through SPIFFE SVIDs (Spiffe Verifiable Identity Documents)
 * for mTLS communication with other services in the mesh.
 *
 * Features:
 * - X509-SVID acquisition from the SPIRE Workload API
 * - mTLS context creation for gRPC channels
 * - SVID validation and peer verification
 * - Automatic SVID rotation (handled by the SPIRE Agent)
 *
 * Trust domain: spiffe://trust.example.org/ns/production/sa/order
 */
class SpiffeIntegration(
    private val trustDomain: String = "trust.example.org",
    private val socketPath: String = "/tmp/spire-agent/public/api.sock",
    private val enabled: Boolean = false
) : Closeable {

    private val logger = LoggerFactory.getLogger(SpiffeIntegration::class.java)

    private var workloadApiClient: WorkloadApiClient? = null
    private var spiffeClient: SpiffeClient? = null

    /**
     * The SPIFFE ID for this service.
     */
    val spiffeId: String = "spiffe://$trustDomain/ns/production/sa/order"

    /**
     * Initialize the SPIFFE client by connecting to the SPIRE Agent.
     */
    fun initialize() {
        if (!enabled) {
            logger.info("SPIFFE integration disabled, using insecure connections")
            return
        }

        try {
            val clientSettings = SpiffeClientSettings.builder()
                .setSpiffeSocketPath(socketPath)
                .build()

            workloadApiClient = DefaultWorkloadApiClient.newClient(socketPath)
            spiffeClient = DefaultSpiffeClient.newClient(clientSettings)

            logger.info("SPIFFE client initialized: spiffeId=$spiffeId, socketPath=$socketPath")
        } catch (e: Exception) {
            logger.error("Failed to initialize SPIFFE client", e)
            throw IllegalStateException("SPIFFE initialization failed", e)
        }
    }

    /**
     * Get the current X509-SVID for this workload.
     * The SVID is automatically rotated by the SPIRE Agent.
     */
    fun getX509Svid(): JvmSvid? {
        if (!enabled) return null

        return try {
            spiffeClient?.svid?.let { svids ->
                svids.firstOrNull { it.svid.spiffeId.toString().startsWith("spiffe://$trustDomain") }
            }
        } catch (e: Exception) {
            logger.error("Failed to fetch X509-SVID", e)
            null
        }
    }

    /**
     * Create an mTLS SSLContext for gRPC channels.
     * Uses SPIFFE SVID for client certificate and SPIFFE bundle for trust.
     */
    fun createMtlsContext(): SSLContext? {
        if (!enabled) return null

        return try {
            val svid = getX509Svid() ?: run {
                logger.warn("No SVID available, falling back to insecure connection")
                return null
            }

            val tlsContext = SpiffeTlsContext.builder()
                .trustDomain(io.spiffe.core.SpiffeTrustDomain.of(trustDomain))
                .workloadApiClient(workloadApiClient)
                .build()

            tlsContext.sslContext
        } catch (e: Exception) {
            logger.error("Failed to create mTLS context", e)
            null
        }
    }

    /**
     * Validate a peer's SPIFFE ID against the expected pattern.
     * Used for server-side authentication in gRPC interceptors.
     */
    fun validatePeerSpiffeId(
        peerCert: X509Certificate,
        expectedService: String
    ): Boolean {
        if (!enabled) return true

        return try {
            val uriSans = peerCert.subjectAlternativeNames
                ?.filter { it.first == 6 } // URI SAN type
                ?.map { it.second?.toString() }
                ?: return false

            val expectedId = "spiffe://$trustDomain/ns/production/sa/$expectedService"
            uriSans.any { it == expectedId }
        } catch (e: Exception) {
            logger.error("Failed to validate peer SPIFFE ID", e)
            false
        }
    }

    /**
     * Get the trust bundle (CA certificates) from the SPIRE Agent.
     */
    fun getTrustBundle(): List<X509Certificate> {
        if (!enabled) return emptyList()

        return try {
            spiffeClient?.bundle?.x509Authorities?.toList() ?: emptyList()
        } catch (e: Exception) {
            logger.error("Failed to fetch trust bundle", e)
            emptyList()
        }
    }

    override fun close() {
        try {
            spiffeClient?.close()
            workloadApiClient?.close()
            logger.info("SPIFFE client closed")
        } catch (e: Exception) {
            logger.warn("Error closing SPIFFE client", e)
        }
    }
}
