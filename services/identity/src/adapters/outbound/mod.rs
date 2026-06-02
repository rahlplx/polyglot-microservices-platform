// ---------------------------------------------------------------------------
// Outbound Adapters Module
// ---------------------------------------------------------------------------
// Outbound adapters implement the outbound port interfaces, providing
// concrete implementations for infrastructure concerns (database,
// messaging, crypto, observability).
// ---------------------------------------------------------------------------

pub mod crypto;
pub mod observability;
pub mod persistence;
pub mod spire;
