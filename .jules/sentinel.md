## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-15 - [Workload Private Key Encryption]
**Vulnerability:** Workload private keys were stored unencrypted in the database.
**Learning:** Placeholders for security critical features (like encryption) in initial implementations can easily be forgotten and lead to critical vulnerabilities if they reach production.
**Prevention:** Implement "Fail Secure" defaults. If encryption is not yet implemented, the service should refuse to issue keys or store them in a way that is clearly identified as insecure and blocked in production environments. Use standard libraries like `ring` for AES-256-GCM and HKDF for key management.
