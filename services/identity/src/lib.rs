// ---------------------------------------------------------------------------
// Identity Service — Library Root
// Re-exports domain + adapters for integration/unit tests.
// Infrastructure layer (DI wiring, server) is excluded — it requires
// live PostgreSQL, SPIRE, and tonic, which are unavailable in unit tests.
// ---------------------------------------------------------------------------

pub mod domain;
pub mod adapters;
