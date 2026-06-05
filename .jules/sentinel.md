## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2025-05-22 - [Webhook SSRF Protection in Python]
**Vulnerability:** Server-Side Request Forgery (SSRF) via unsanitized webhook recipient addresses.
**Learning:** Webhook adapters that make outbound HTTP requests must validate that the target IP does not resolve to internal network ranges (RFC 1918), loopback, or cloud metadata services.
**Prevention:** Implement a `_is_safe_url` check that parses the URL, resolves the hostname using `socket.getaddrinfo`, and validates the resulting IPs against private/reserved ranges using the `ipaddress` module.
