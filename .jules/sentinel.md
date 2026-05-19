## 2024-05-19 - Meilisearch Filter Injection
**Vulnerability:** User-provided category and tag values were directly concatenated into Meilisearch filter strings, allowing for filter injection.
**Learning:** Meilisearch filters require explicit escaping of double quotes and backslashes in values to prevent injection, similar to SQL.
**Prevention:** Use a dedicated escaping helper for all search filter construction.
