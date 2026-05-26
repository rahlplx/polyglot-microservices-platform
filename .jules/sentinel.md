# Sentinel's Journal - Critical Security Learnings

## 2025-05-22 - Meilisearch Filter Injection
**Vulnerability:** User-provided filter values (like categories or tags) were concatenated directly into Meilisearch filter strings without escaping. This allowed attackers to break out of the intended filter attribute using double quotes and inject additional filter logic (e.g., `electronics" OR status = "deleted`).
**Learning:** Meilisearch filters are not automatically sanitized when passed as strings. Quoted values within filters must have backslashes and double quotes escaped to prevent injection.
**Prevention:** Always use a dedicated escaping helper for string values in Meilisearch filters. The correct escaping sequence is to replace `\` with `\\` and then `"` with `\"`.
