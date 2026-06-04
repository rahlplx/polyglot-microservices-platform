// ---------------------------------------------------------------------------
// Adapters Module
// ---------------------------------------------------------------------------
// Adapters form the outer ring of the hexagonal architecture.
// They translate between external protocols/formats and the domain.
// Inbound adapters drive the application; outbound adapters are
// driven by the application.
// ---------------------------------------------------------------------------

pub mod inbound;
pub mod outbound;

