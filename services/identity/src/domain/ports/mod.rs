// ---------------------------------------------------------------------------
// Domain Ports Module
// ---------------------------------------------------------------------------
// Ports are the boundary interfaces of the hexagonal architecture.
// Inbound ports define use case interfaces (called by adapters).
// Outbound ports define infrastructure interfaces (implemented by adapters).
// All ports are traits with ZERO external dependencies.
// ---------------------------------------------------------------------------

pub mod inbound;
pub mod outbound;
