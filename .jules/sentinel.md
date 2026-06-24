## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2025-05-15 - [Secure Private Key Storage]
**Vulnerability:** Private keys for SVIDs were stored in plaintext due to a placeholder no-op `encrypt_private_key` implementation.
**Learning:** Even with "memory-safe" crypto libraries like `ring`, security depends on correct implementation of storage protection. Plaintext key exposure is a critical failure that negates all other cryptographic protections.
**Prevention:** Implement authenticated encryption (AES-256-GCM) with HKDF-derived keys and unique random nonces for all persistent secrets. Never commit code where security-critical TODOs (especially those marked "FIXME: SECURITY") remain in the implementation.
