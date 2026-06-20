## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2026-06-20 - [Asynchronous SSRF Protection in Webhook Sender]
**Vulnerability:** SSRF vulnerability in Notification service allowing requests to internal/private IP ranges and cloud metadata services.
**Learning:** Standard URL validation that only checks the hostname string can be bypassed by DNS rebinding or by using domain names that resolve to internal IPs. Asynchronous hostname resolution must be used to validate all potential IP addresses.
**Prevention:** Resolve hostnames to IP addresses using `asyncio.get_event_loop().getaddrinfo()` and validate every resolved IP against private and reserved ranges using the `ipaddress` module before initiating any request.
