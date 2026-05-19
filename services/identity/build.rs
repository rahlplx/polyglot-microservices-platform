// ---------------------------------------------------------------------------
// Build Script: Protobuf Code Generation
// ---------------------------------------------------------------------------
// Compiles the proto schemas into Rust code using tonic-build.
// This runs at compile time to generate the gRPC service stubs.
// ---------------------------------------------------------------------------

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Proto compilation is optional — the service can be built
    // without proto files present (using hand-defined message types).
    // When the proto files are available, uncomment the block below.

    /*
    let proto_dir = "../../schemas/proto/identity/v1";

    tonic_build::configure()
        .build_server(true)
        .build_client(false)
        .type_attribute(".", "#[derive(serde::Serialize, serde::Deserialize)]")
        .type_attribute("identity.v1.WorkloadEntry", "#[derive(Clone)]")
        .compile(
            &[
                format!("{}/identity.proto", proto_dir),
                format!("{}/mtls.proto", proto_dir),
            ],
            &[proto_dir],
        )?;
    */

    Ok(())
}
