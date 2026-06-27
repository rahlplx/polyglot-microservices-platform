## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-13 - [SSRF Protection in Webhooks]
**Vulnerability:** Server-Side Request Forgery (SSRF) in webhook delivery allowing requests to internal/private IP ranges.
**Learning:** Standard HTTP clients resolve hostnames automatically, which can bypass simple URL string checks.
**Prevention:** Explicitly resolve hostnames to IP addresses using `getaddrinfo` and validate all resulting IPs against private/reserved ranges (e.g., using `ipaddress.is_global` in Python) before initiating the request.
