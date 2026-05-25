// ---------------------------------------------------------------------------
// Infrastructure Module
// ---------------------------------------------------------------------------
// The infrastructure module contains configuration, server setup,
// and dependency injection wiring. It is the outermost layer of
// the hexagonal architecture.
// ---------------------------------------------------------------------------

pub mod config;
pub mod di;
pub mod server;

pub use config::Config;
pub use di::{AppContainer, DIError};
pub use server::{IdentityServer, ServerError};
