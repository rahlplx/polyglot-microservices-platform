## 2025-05-15 - Meilisearch Filter Injection
**Vulnerability:** User-provided filter values (categories, tags) were concatenated directly into Meilisearch filter strings without escaping. This allowed an attacker to inject additional filter conditions (e.g., `electronics" OR status = "INACTIVE`) to bypass business logic or access hidden data.
**Learning:** Meilisearch filters use a domain-specific language where string literals are enclosed in double quotes. Within these quotes, both double quotes (`"`) and backslashes (`\`) must be escaped.
**Prevention:** Always use a sanitization helper like `escapeFilterValue` when building filter strings from untrusted input.
