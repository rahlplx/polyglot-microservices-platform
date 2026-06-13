## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-13 - [SSRF Protection in Webhook Delivery]
**Vulnerability:** Webhook delivery was vulnerable to Server-Side Request Forgery (SSRF) as it allowed sending requests to any URL, including internal and private network addresses.
**Learning:** Preventing SSRF requires resolving hostnames to IP addresses asynchronously and validating them against restricted ranges (loopback, private, etc.) before the request is initiated. Simply blocking "localhost" or specific IPs in the URL string is insufficient due to DNS-based bypasses.
**Prevention:** Implement a central URL validation helper that performs DNS resolution and IP range checks. Use the `ipaddress` module for robust range validation and ensure that all outbound adapters (Webhooks, External APIs) utilize this check.
