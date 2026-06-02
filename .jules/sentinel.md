## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-13 - [At-Rest Encryption for Private Keys]
**Vulnerability:** Private keys were stored unencrypted or with no-op "placeholders", exposing them to anyone with database access.
**Learning:** Placeholders like `FIXME` or `TODO` for security features can easily be forgotten. Architectural documentation must be matched by actual implementation. Direct use of master keys for AES is discouraged; HKDF should be used to derive specific-purpose keys.
**Prevention:** Implement AES-256-GCM encryption with random nonces for all sensitive data at rest. Use HKDF-SHA256 for key derivation from a master secret. Enforce mandatory environment variables for secrets in production instead of hardcoded defaults.
