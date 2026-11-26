# Security Policy

## Supported Versions

The following versions of `scigraph` currently receive security updates:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in `creova-gif/scigraph`, please report it responsibly without opening a public GitHub issue.

- **Preferred channel:** Submit a private report via GitHub Security Advisories at <https://github.com/creova-gif/scigraph/security/advisories/new>.
- **What to include:** A clear description of the issue, affected component or endpoint, steps to reproduce (or proof-of-concept), and potential impact.
- **Response timeline:** We aim to acknowledge receipt within 48 hours, provide an initial triage assessment within 5 business days, and coordinate disclosure once a fix is released.

## Implemented Security Controls

`scigraph` enforces defense-in-depth controls across ingestion, API serving, workspace isolation, and provenance:

- **Verbatim DOI / Span Verification:** Claims and extracted evidence spans are validated against source document spans and DOI provenance before graph insertion, preventing ungrounded or fabricated citations.
- **PDF Decompression Bomb Guard:** PDF ingestion enforces a cumulative 50 MiB `/FlateDecode` decompression limit per document to mitigate memory-exhaustion and zip/PDF bomb attacks.
- **SSRF Protection:** Outbound fetches require `https://` URLs, resolve DNS and block private, loopback, link-local, multicast, reserved, and CGNAT (`100.64.0.0/10`) IP ranges, and disable HTTP redirects (`no-redirect` guard).
- **Bearer RBAC & Anti-Eviction Rate Limiting:** HTTP endpoints enforce Bearer token role-based access control alongside anti-eviction rate limiting to prevent brute-force and cache-eviction abuse.
- **Workspace `org_id` & Path-Traversal Isolation:** Tenant workspaces are strictly scoped by `org_id` with canonicalized path-traversal checks ensuring all file reads and writes remain confined to the tenant's workspace root.
- **HMAC-SHA256 Provenance:** Graph artifacts, audit records, and provenance manifests support HMAC-SHA256 integrity signing and verification.
