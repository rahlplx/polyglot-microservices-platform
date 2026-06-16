## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2026-06-16 - [SSRF Protection via Async Hostname Resolution]
**Vulnerability:** Server-Side Request Forgery (SSRF) in webhook dispatchers.
**Learning:** Webhook senders that don't validate resolved IP addresses can be used to scan internal networks or access metadata services (like AWS IMDS). Simple hostname blocklists are insufficient as they can be bypassed via DNS rebinding or custom domains pointing to private IPs.
**Prevention:** Always resolve the hostname to its IP addresses using `asyncio.get_event_loop().getaddrinfo()` and validate the resulting IPs against private, loopback, and reserved ranges using the `ipaddress` module BEFORE initiating any HTTP request.
