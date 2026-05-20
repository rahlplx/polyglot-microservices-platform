# Sentinel's Journal - Critical Security Learnings

## 2024-12-16 - Meilisearch Filter Injection
**Vulnerability:** User-provided filter values were directly interpolated into Meilisearch filter strings without escaping double quotes, allowing filter bypass.
**Learning:** Even NoSQL or search engines like Meilisearch are vulnerable to injection-style attacks if they use string-based query languages for filtering.
**Prevention:** Always escape user-controllable input before embedding it in query strings, specifically escaping double quotes and backslashes for Meilisearch filters.
