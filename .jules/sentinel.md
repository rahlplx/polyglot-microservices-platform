## 2024-06-12 - [Secure SVID Serial Number Generation]
**Vulnerability:** Predictable X.509 serial numbers based on nanosecond timestamps.
**Learning:** Using timestamps for serial numbers violates RFC 5280 §4.1.2.2 and allows attackers to predict or spoof certificates if other validation layers are weak.
**Prevention:** Always use cryptographically secure random number generators (like `ring::rand::SystemRandom`) to generate at least 20 bytes for certificate serial numbers.

## 2024-06-22 - [Meilisearch Filter Injection]
**Vulnerability:** Filter injection in Meilisearch due to unescaped user input in filter strings.
**Learning:** Meilisearch filters are constructed as strings where double quotes and backslashes have special meanings. If user input (like categories or tags) is directly interpolated, an attacker can break out of the string literal (e.g., `"electronics" OR status = "INACTIVE"`) to bypass security constraints or access unauthorized data.
**Prevention:** Always escape backslashes first, then double quotes in all user-provided strings before including them in Meilisearch filter expressions. Use a robust escaping helper: `value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')`.
