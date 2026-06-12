## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-12 - [Information Leakage in REST Handlers]
**Vulnerability:** Internal error strings (e.g. from service layer) leaked directly to clients via HTTP responses.
**Learning:** Returning raw errors in API responses violates "Fail Securely" and provides attackers with reconnaissance data about internal service states or failures.
**Prevention:** Mask all client-facing error messages with generic, non-informative text. Ensure detailed errors are preserved only in server-side logs.
