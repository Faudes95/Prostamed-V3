# Security Policy — ProstaMed/ProstaNet

## Reporting a Vulnerability

If you discover a security vulnerability in ProstaMed, please report it
responsibly via:

- **Email**: security@prostamed.example (TBD — pending contact assignment)
- **Encrypted**: PGP key fingerprint TBD

**DO NOT open public GitHub issues for security vulnerabilities.**

## SLA for response

| Severity | First response | Patch ETA |
|----------|----------------|-----------|
| **Critical** (PHI exposure, RCE, auth bypass) | 24h | 7 days |
| **High** (privilege escalation, DoS) | 72h | 30 days |
| **Medium** (info leak non-PHI, CSRF) | 7 days | 60 days |
| **Low** (rate-limit bypass, etc.) | 14 days | 90 days |

## Coordinated disclosure

We follow a 90-day coordinated disclosure timeline. After patch deployment,
we publish a CVE advisory in [SECURITY-ADVISORIES.md](./SECURITY-ADVISORIES.md).

## Scope

In scope:
- ProstaMed Flask web application
- 89 pivotal gates clinical logic
- Faubot Agentic Loop (`prostanet/agentic/`)
- decision_audit endpoints
- Patient profile UI v2

Out of scope:
- Third-party CDN dependencies (Tailwind, Chart.js) — report upstream
- macOS / Linux OS-level vulnerabilities — report Apple / distro

## Cybersecurity Framework

- **STRIDE threat model**: `prostanet/regulatory/security/STRIDE-threat-model.md`
- **SBOM**: `prostanet/regulatory/security/sbom-cyclonedx.json`
- **VEX**: `prostanet/regulatory/security/vex.json` (TBD)
- **AAMI TIR57 addendum**: `prostanet/regulatory/risk/tir57_addendum.md`

## Compliance

- FDA Premarket Cybersecurity Guidance Sept 2023
- HIPAA (US) + LFPDPPP (Mexico) for PHI
- 21 CFR Part 11 for electronic signatures (in progress)

---

**Updated**: 2026-04-27 (Faubot LXXXVIII bootstrap)
