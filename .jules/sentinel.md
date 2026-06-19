## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-13 - [Meilisearch Filter Injection Mitigation]
**Vulnerability:** Meilisearch filter injection via unescaped double quotes in filter expressions.
**Learning:** Meilisearch filter expressions are string-based; simple concatenation of user input into these strings allows attackers to break out of quoted values and inject arbitrary logic (e.g., ORing with other fields to bypass visibility filters).
**Prevention:** Implement a robust `escapeFilterValue` helper that escapes backslashes first, then double quotes, before embedding user input into filter strings.
