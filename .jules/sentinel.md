## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-12 - [SSRF Protection in Webhook Delivery]
**Vulnerability:** Unvalidated webhook URLs allowing access to private network resources and metadata services.
**Learning:** Simply checking for private IP strings in the URL is insufficient due to DNS rebinding and URL encoding tricks. Hostnames must be resolved to all associated IPs using `getaddrinfo` and validated against private/reserved ranges before any request is made.
**Prevention:** Use `asyncio.get_event_loop().getaddrinfo()` to resolve hostnames and the `ipaddress` module to robustly validate all resolved IPs against forbidden ranges (loopback, private, reserved, etc.).
