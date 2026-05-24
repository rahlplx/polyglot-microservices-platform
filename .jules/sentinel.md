# Sentinel Journal - Security Learnings

## 2024-12-16 - Meilisearch Filter Injection
**Vulnerability:** Search filter injection in `MeilisearchAdapter` through string interpolation of user-provided categories and tags.
**Learning:** Even NoSQL search engines like Meilisearch are vulnerable to injection attacks if filter expressions are built using unsanitized string interpolation. A malicious user can use double quotes to break out of the intended filter value and inject arbitrary filter logic. Furthermore, simply escaping double quotes is insufficient if backslashes are also used as escape characters; an attacker can use a backslash to escape the added escape character.
**Prevention:** Always escape both backslashes and double quotes in user-provided values before interpolating them into filter strings. The order is critical: escape backslashes FIRST, then double quotes.
