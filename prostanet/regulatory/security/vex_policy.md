# ProstaMed VEX Addendum Procedure

Document ID: SEC-VEX-001
Status: Active internal procedure
Owner: Security Owner
Applies to: SBOM, CVE audit reports, dependency remediation, release evidence, and autonomous-improvement security cycles.

## Purpose

This procedure defines how ProstaMed records Vulnerability Exploitability eXchange (VEX) status for dependency findings. VEX is used to explain whether a vulnerability in a component is exploitable in the ProstaMed product context, not to hide or dismiss scanner findings.

## Standards Alignment

The machine-readable addendum is `prostanet/regulatory/security/vex.json` and follows a CycloneDX-style VEX contract:

- Product reference: `prostamed`
- SBOM reference: `prostanet/regulatory/security/sbom-cyclonedx.json`
- Audit reference: `prostanet/regulatory/security/cve-audit-last.json`
- Status vocabulary: `affected`, `not_affected`, `fixed`, `under_investigation`
- Required justification for `not_affected`
- Required remediation or mitigation evidence for `affected`

## Current Baseline

The current `cve-audit-last.json` report lists no open vulnerabilities for the audited runtime dependency set. Therefore the current VEX addendum contains an empty `vulnerabilities` list rather than fabricated CVE statements.

If a future audit reports vulnerabilities, the VEX addendum must be updated with one statement per vulnerability and component.

## Required VEX Statement Fields

Each non-empty VEX statement must include:

1. Vulnerability ID, preferably CVE.
2. Affected component reference from the SBOM.
3. Analysis state.
4. Justification when state is `not_affected`.
5. Mitigation or remediation action when state is `affected`.
6. Timestamp and reviewer/provenance.
7. Link to CVE audit evidence.

## Clinical Safety Boundary

VEX never changes clinical recommendations. It only affects security prioritization and remediation routing. A vulnerability marked `not_affected` must have an auditable reason such as code not present, code not reachable, protected by mitigating control, vulnerable code not in execution path, or vulnerable functionality disabled.

The following remain prohibited:

- Marking a vulnerability `not_affected` without justification.
- Suppressing CVEs from the audit report.
- Using VEX to delay patching an exploitable vulnerability.
- Logging PHI in VEX, scan reports, or PR artifacts.

## Acceptance Criteria

- `vex.json` exists and is valid JSON.
- The VEX addendum references the SBOM and latest CVE audit report.
- If there are no CVEs, `vulnerabilities` is empty and no CVE IDs are fabricated.
- If CVEs exist, each statement has product/component, analysis state, and required justification/mitigation.
- Pillar 6 no longer reports `vex_addendum_missing`.
