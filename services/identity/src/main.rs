// ---------------------------------------------------------------------------
// Identity Service - Entry Point
// ---------------------------------------------------------------------------
// This is the main entry point for the Identity service. It initializes
// configuration, wires dependencies, sets up observability, and starts
// the gRPC server.
// ---------------------------------------------------------------------------

mod adapters;
mod domain;
mod infrastructure;

use infrastructure::{AppContainer, Config, IdentityServer};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load environment variables from .env file if present
    dotenvy::dotenv().ok();

    // Load configuration from environment variables
    let config = Config::from_env();

    // Initialize the tracing subscriber
    init_tracing(&config.log_level, &config.otlp_endpoint);

    tracing::info!(
        "Identity Service starting (version={})",
        env!("CARGO_PKG_VERSION")
    );
    tracing::info!("{}", config.summary());

    // Validate configuration
    if let Err(errors) = config.validate() {
        for error in &errors {
            tracing::error!("Configuration error: {}", error);
        }
        anyhow::bail!("Invalid configuration: {} errors", errors.len());
    }

    // Wire application dependencies
    let container = AppContainer::wire(&config).await?;

    // Initialize observability
    container
        .observability
        .init()
        .await
        .map_err(|e| anyhow::anyhow!("Failed to initialize observability: {}", e))?;

    // Create and run the server
    let server = IdentityServer::new(config, container.grpc_handler);
    server.run().await?;

    // Shutdown observability
    container.observability.shutdown().await;

    tracing::info!("Identity Service shutdown complete");
    Ok(())
}

/// Initializes the tracing subscriber with OTel and stdout output.
fn init_tracing(log_level: &str, otlp_endpoint: &str) {
    use tracing_subscriber::EnvFilter;

    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(log_level));

    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(true)
        .with_thread_ids(true)
        .with_file(true)
        .with_line_number(true)
        .json()
        .init();

    tracing::info!(
        "Tracing initialized (level={}, otlp={})",
        log_level,
        otlp_endpoint
    );
}
