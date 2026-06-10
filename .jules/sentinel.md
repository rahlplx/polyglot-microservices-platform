## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-12 - [SSRF Protection in Webhook Delivery]
**Vulnerability:** Unvalidated webhook URLs allowing Server-Side Request Forgery (SSRF) and DNS rebinding attacks.
**Learning:** Simply checking the hostname is insufficient; attackers can use DNS rebinding or point hostnames to internal IP ranges. Robust protection requires resolving hostnames to IP addresses and validating them against private/loopback/reserved ranges.
**Prevention:** In Python, use  to resolve hostnames and  to check if the resulting IPs are safe (, , etc.) before initiating any outbound HTTP requests.

## 2024-06-12 - [SSRF Protection in Webhook Delivery]
**Vulnerability:** Unvalidated webhook URLs allowing Server-Side Request Forgery (SSRF) and DNS rebinding attacks.
**Learning:** Simply checking the hostname is insufficient; attackers can use DNS rebinding or point hostnames to internal IP ranges. Robust protection requires resolving hostnames to IP addresses and validating them against private/loopback/reserved ranges.
**Prevention:** In Python, use `asyncio.get_event_loop().getaddrinfo()` to resolve hostnames and `ipaddress.ip_address()` to check if the resulting IPs are safe (`is_private`, `is_loopback`, etc.) before initiating any outbound HTTP requests.
