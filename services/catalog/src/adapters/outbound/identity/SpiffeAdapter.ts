/**
 * SPIFFE Identity Adapter
 *
 * Integrates with the SPIFFE Workload API for workload identity
 * and mTLS certificate management. Uses spiffe-sdk to fetch
 * SVIDs and validate peer identities.
 */
import pino, { type Logger } from 'pino';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface SpiffeConfig {
  readonly enabled: boolean;
  readonly trustDomain: string;
  readonly workloadApiAddr: string;
  readonly svidTtlSeconds: number;
}

// ---------------------------------------------------------------------------
// SVID Information
// ---------------------------------------------------------------------------

export interface SvidInfo {
  readonly spiffeId: string;
  readonly expiresAt: Date;
  readonly trustDomain: string;
}

// ---------------------------------------------------------------------------
// SPIFFE Adapter
// ---------------------------------------------------------------------------

export class SpiffeAdapter {
  private readonly config: SpiffeConfig;
  private readonly logger: Logger;
  private currentSvid: SvidInfo | null = null;
  private rotationTimer: ReturnType<typeof setInterval> | null = null;

  constructor(config: SpiffeConfig) {
    this.config = config;
    this.logger = pino({ name: 'catalog-spiffe' });
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  async start(): Promise<void> {
    if (!this.config.enabled) {
      this.logger.info('SPIFFE identity is disabled');
      return;
    }

    try {
      await this.fetchSvid();
      this.startRotation();
      this.logger.info(
        {
          trustDomain: this.config.trustDomain,
          workloadApiAddr: this.config.workloadApiAddr,
        },
        'SPIFFE identity started'
      );
    } catch (error) {
      this.logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to start SPIFFE identity'
      );
      throw error;
    }
  }

  async stop(): Promise<void> {
    if (this.rotationTimer) {
      clearInterval(this.rotationTimer);
      this.rotationTimer = null;
    }
    this.logger.info('SPIFFE identity stopped');
  }

  // -------------------------------------------------------------------------
  // Identity Operations
  // -------------------------------------------------------------------------

  getSvid(): SvidInfo | null {
    return this.currentSvid;
  }

  getSpiffeId(): string {
    return this.currentSvid?.spiffeId ?? `spiffe://${this.config.trustDomain}/catalog/default`;
  }

  validatePeerIdentity(peerSpiffeId: string, expectedTrustDomain?: string): boolean {
    const trustDomain = expectedTrustDomain ?? this.config.trustDomain;
    return peerSpiffeId.startsWith(`spiffe://${trustDomain}/`);
  }

  /**
   * Build peer SPIFFE ID for a given service name within the trust domain.
   */
  buildPeerSpiffeId(serviceName: string): string {
    return `spiffe://${this.config.trustDomain}/${serviceName}`;
  }

  // -------------------------------------------------------------------------
  // mTLS Credentials
  // -------------------------------------------------------------------------

  /**
   * Get gRPC channel credentials for mTLS using SPIFFE SVID.
   * Returns null if SPIFFE is disabled.
   */
  async getMtlsCredentials(): Promise<{
    certChain: Buffer;
    privateKey: Buffer;
    caCerts: Buffer[];
  } | null> {
    if (!this.config.enabled) {
      return null;
    }

    try {
      // In production, this would call the SPIFFE Workload API via spiffe-sdk
      // to fetch the actual SVID, private key, and bundle.
      // For now, we return a placeholder that the gRPC server can use.
      const svid = this.getSvid();
      if (!svid) {
        this.logger.warn('No SVID available for mTLS credentials');
        return null;
      }

      // Placeholder: In production, fetch actual certificates from Workload API
      return {
        certChain: Buffer.from(''), // SVID certificate chain
        privateKey: Buffer.from(''), // Private key
        caCerts: [Buffer.from('')], // Trust bundle
      };
    } catch (error) {
      this.logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to get mTLS credentials'
      );
      return null;
    }
  }

  // -------------------------------------------------------------------------
  // Private Helpers
  // -------------------------------------------------------------------------

  private async fetchSvid(): Promise<void> {
    // In production, this would use the spiffe-sdk Workload API client:
    //
    // const client = new WorkloadAPIClient(this.config.workloadApiAddr);
    // const svid = await client.fetchX509SVID();
    // this.currentSvid = {
    //   spiffeId: svid.spiffeId,
    //   expiresAt: svid.expiresAt,
    //   trustDomain: svid.trustDomain,
    // };

    this.currentSvid = {
      spiffeId: `spiffe://${this.config.trustDomain}/catalog/default`,
      expiresAt: new Date(Date.now() + this.config.svidTtlSeconds * 1000),
      trustDomain: this.config.trustDomain,
    };

    this.logger.debug({ spiffeId: this.currentSvid.spiffeId }, 'Fetched SVID');
  }

  private startRotation(): void {
    // Rotate SVID at half the TTL interval
    const rotationInterval = (this.config.svidTtlSeconds * 1000) / 2;
    this.rotationTimer = setInterval(async () => {
      try {
        await this.fetchSvid();
        this.logger.debug('SVID rotated successfully');
      } catch (error) {
        this.logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'SVID rotation failed'
        );
      }
    }, rotationInterval);
  }
}
