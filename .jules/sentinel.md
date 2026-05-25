## 2025-05-15 - [Predictable Certificate Serial Numbers]
**Vulnerability:** Identity service was using predictable, timestamp-based serial numbers for issued SVIDs, which is not cryptographically random and violates RFC 5280.
**Learning:** Found an explicit FIXME: SECURITY comment in rustls.rs indicating this gap. Using ring::rand is the standard fix in this codebase for Rust.
**Prevention:** Always use cryptographically secure random number generators (CSPRNG) for security-sensitive unique identifiers.
