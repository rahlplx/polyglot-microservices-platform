## 2024-05-19 - Meilisearch Filter Injection & Information Leakage
**Vulnerability:** User-provided category and tag values were directly concatenated into Meilisearch filter strings, allowing for filter injection. Additionally, the Gateway service was leaking raw internal error messages.
**Learning:** Meilisearch filters require explicit escaping of double quotes and backslashes in values to prevent injection, similar to SQL. Error handling in edge services like Gateways must explicitly mask internal errors.
**Prevention:** Use a dedicated escaping helper for all search filter construction. Implement a "safe error" pattern in controllers that maps internal exceptions to generic user-facing messages.
