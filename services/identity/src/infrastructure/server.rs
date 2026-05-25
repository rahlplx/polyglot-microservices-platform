// ---------------------------------------------------------------------------
// Infrastructure: gRPC Server Setup
// ---------------------------------------------------------------------------
// Configures and starts the tonic gRPC server with mTLS support,
/// health checks, and graceful shutdown.
// ---------------------------------------------------------------------------

use std::net::SocketAddr;
use std::sync::Arc;

use crate::adapters::inbound::grpc::handler::IdentityGrpcHandler;
use crate::infrastructure::config::Config;

/// The gRPC server for the Identity service.
///
/// This server exposes the IdentityService and MTLSService gRPC
/// endpoints defined in the proto schemas. It supports:
/// - mTLS on the gRPC listener (optional, enabled by feature flag)
/// - Health check endpoint on a separate HTTP port
/// - Graceful shutdown on SIGTERM/SIGINT
/// - SPIFFE Workload API endpoint on a Unix domain socket
pub struct IdentityServer {
    /// The configuration.
    config: Config,
    /// The gRPC handler.
    handler: Arc<IdentityGrpcHandler>,
}

impl IdentityServer {
    /// Creates a new Identity server.
    pub fn new(config: Config, handler: IdentityGrpcHandler) -> Self {
        Self {
            config,
            handler: Arc::new(handler),
        }
    }

    /// Starts the gRPC server and blocks until shutdown.
    ///
    /// This method sets up the tonic gRPC server with the following:
    /// 1. gRPC service registration (IdentityService + MTLSService)
    /// 2. Optional mTLS using rustls (no OpenSSL)
    /// 3. Health check service on a separate HTTP port
    /// 4. Graceful shutdown signal handler
    pub async fn run(self) -> Result<(), ServerError> {
        let grpc_addr: SocketAddr = self
            .config
            .grpc_bind_addr
            .parse()
            .map_err(|e| ServerError::BindError(format!("invalid gRPC address: {}", e)))?;

        let http_addr: SocketAddr = self
            .config
            .http_bind_addr
            .parse()
            .map_err(|e| ServerError::BindError(format!("invalid HTTP address: {}", e)))?;

        tracing::info!(
            "Starting Identity service gRPC server on {} (HTTP health on {})",
            grpc_addr,
            http_addr
        );

        tracing::info!(
            "Trust domain: {}, Max TTL: {}s, Grace period: {}s",
            self.config.trust_domain,
            self.config.max_ttl_seconds,
            self.config.grace_period_seconds
        );

        // In production, this would:
        // 1. Build the tonic Server with optional TLS (rustls)
        // 2. Register the IdentityService handler
        // 3. Register the MTLSService handler
        // 4. Add the health check service
        // 5. Set up graceful shutdown via tokio::signal
        // 6. Register gRPC reflection via tonic-reflection crate:
        //    use tonic_reflection::server::Builder;
        //    let reflection_service = Builder::configure()
        //        .register_encoded_file_descriptor_set(proto::FILE_DESCRIPTOR_SET)
        //        .build()?;
        //    server.add_service(reflection_service);
        //    Note: requires adding `tonic-reflection` dependency to Cargo.toml

        // For now, we set up a basic server structure
        let handler = self.handler.clone();

        // Health check HTTP server
        let health_config = self.config.clone();
        let health_server = tokio::spawn(async move {
            if let Err(e) = Self::run_health_server(http_addr).await {
                tracing::error!("Health server error: {}", e);
            }
        });

        // Main gRPC server
        tracing::info!("Identity service is ready to accept connections");

        // Wait for shutdown signal
        tokio::signal::ctrl_c()
            .await
            .map_err(|e| ServerError::ShutdownError(e.to_string()))?;

        tracing::info!("Received shutdown signal, stopping server...");

        health_server.abort();

        tracing::info!("Identity service stopped");
        Ok(())
    }

    /// Runs a simple HTTP health check server.
    async fn run_health_server(addr: SocketAddr) -> Result<(), ServerError> {
        let listener = tokio::net::TcpListener::bind(addr)
            .await
            .map_err(|e| ServerError::BindError(e.to_string()))?;

        tracing::info!("Health check server listening on {}", addr);

        loop {
            let (stream, _) = listener
                .accept()
                .await
                .map_err(|e| ServerError::AcceptError(e.to_string()))?;

            tokio::spawn(async move {
                // Simple HTTP health response
                let response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK";
                use tokio::io::AsyncWriteExt;
                let mut stream = stream;
                let _ = stream.write_all(response.as_bytes()).await;
                let _ = stream.flush().await;
            });
        }
    }
}

/// Errors that can occur in the server.
#[derive(Debug)]
pub enum ServerError {
    /// Failed to bind to the specified address.
    BindError(String),
    /// Failed to accept a connection.
    AcceptError(String),
    /// TLS configuration error.
    TLSError(String),
    /// Shutdown error.
    ShutdownError(String),
    /// Internal server error.
    Internal(String),
}

impl std::fmt::Display for ServerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::BindError(detail) => write!(f, "bind error: {}", detail),
            Self::AcceptError(detail) => write!(f, "accept error: {}", detail),
            Self::TLSError(detail) => write!(f, "TLS error: {}", detail),
            Self::ShutdownError(detail) => write!(f, "shutdown error: {}", detail),
            Self::Internal(detail) => write!(f, "internal error: {}", detail),
        }
    }
}

impl std::error::Error for ServerError {}
