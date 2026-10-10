# Security

## Report a problem

- **A listed integration is malicious, steals credentials or has a vulnerability:** report it privately through [security advisories](https://github.com/TableProApp/integrations/security/advisories/new). A confirmed report removes the entry at once, as section 10 of the [listing policy](POLICY.md) says.
- **This repository's workflows, scripts or data:** report it the same way, or email hello@tablepro.app.
- **TablePro itself:** see [TablePro's security policy](https://github.com/TableProApp/TablePro/security/policy).

Do not open a public issue for any of these.

## What this repository protects

- Pull request checks run with a read-only token and never see secrets. Labeling runs on `pull_request_target` and never checks out pull request code.
- Every action is pinned to a full commit SHA.
- Entries are pinned to numeric repository and account IDs, so a renamed or re-created repository is caught.
- Entry data is only parsed, never run. Images are decoded only in CI. SVG is not accepted.
