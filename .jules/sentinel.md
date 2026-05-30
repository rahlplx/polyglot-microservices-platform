## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-13 - [Secure Private Key Storage]
**Vulnerability:** Private keys stored in plaintext or with no-op "placeholder" encryption.
**Learning:** Storing private keys unencrypted is a critical security risk. Even if intended as a placeholder, it must be implemented with a secure algorithm like AES-256-GCM using a master key from a secure secret store.
**Prevention:** Implement AES-256-GCM encryption (e.g., using `ring::aead`) for all sensitive data at rest. Ensure master keys are managed outside the codebase via environment variables or specialized secret management systems.
