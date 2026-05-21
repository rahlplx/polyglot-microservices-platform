// ---------------------------------------------------------------------------
// Domain Module
// ---------------------------------------------------------------------------
// The domain module is the core of the hexagonal architecture.
// It contains the business logic, models, and port definitions.
// The domain has ZERO external dependencies — it depends only on
// the Rust standard library.
// ---------------------------------------------------------------------------

pub mod models;
pub mod ports;
pub mod services;
