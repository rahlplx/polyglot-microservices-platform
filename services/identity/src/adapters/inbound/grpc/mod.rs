// ---------------------------------------------------------------------------
// gRPC Inbound Adapter Module
// ---------------------------------------------------------------------------
// The gRPC adapter translates between tonic/protobuf messages and
// domain model types. It is the primary inbound adapter for the
// Identity service, exposing the SPIFFE Workload API and the
// IdentityService/MTLSService gRPC endpoints.
// ---------------------------------------------------------------------------

pub mod handler;

