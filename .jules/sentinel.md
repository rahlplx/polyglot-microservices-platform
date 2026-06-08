## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-13 - [Webhook SSRF Protection]
**Vulnerability:** Server-Side Request Forgery (SSRF) in webhook delivery, allowing requests to internal or reserved IP ranges.
**Learning:** Webhooks that accept user-provided URLs must be validated at the network layer. Simple hostname blacklisting is insufficient as it can be bypassed by DNS rebinding or IP-based URLs.
**Prevention:** Resolve the destination hostname to IP addresses and verify they do not belong to private (RFC 1918), loopback, link-local, multicast, or reserved ranges before initiating the connection.
