## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.
## 2025-05-14 - [Identity Service Private Key Encryption]
**Vulnerability:** Private keys in the Identity service were being stored unencrypted (placeholder no-op).
**Learning:** The service required a master key for encryption, which was missing from the configuration. Implementing AES-256-GCM with ring required a custom `NonceSequence` implementation to use single random nonces.
**Prevention:** Always verify that cryptographic placeholders in boilerplate or generated code are replaced with real implementations before production.
