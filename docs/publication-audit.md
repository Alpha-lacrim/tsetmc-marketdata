# Public Milestone 1 baseline audit

The owner authorized publication to `Alpha-lacrim/tsetmc-marketdata` and the
annotated development tag `v0.1.0-milestone1`. No software license, GitHub Release,
deployment or Milestone 2 implementation is part of this publication.

## Included and excluded files

Publishable material consists of the complete Python implementation, project
configuration/lockfile, tests, synthetic fixtures/examples, documentation and a
minimal offline CI workflow. All runtime Python source and the qualification
script retain their original Milestone 1 behavior.

Excluded but preserved locally:

- `docs/evidence/`: genuine raw TSETMC responses, metadata/receipt manifests,
  derived chart exports and diagnostic/qualification reports.
- `.local/`: original Milestone 1 file backup, audit details, verification logs and
  publication-only packaging/test environments or snapshots.
- `.git/`, virtual environments, caches, `.env` files other than `.env.example`,
  build artifacts, IDE state and `output/` are not publication content.

No files had been committed before the audit, so no sensitive Git history needed
remediation. The exact staged tree is reviewed before the first commit. Package
archives are also checked for excluded paths; `.gitignore` alone is not treated
as evidence that an already tracked or packaged file is safe.

## Sensitive-data review

All candidate files are reviewed as text; JSON captures are parsed and their keys
and content inspected separately. No actual passwords, API/GitHub tokens, private
keys/certificates, authenticated database URLs, sensitive response headers,
personal contact information or confidential company documents were found.
Credential-looking literals in HTTP-client tests are deliberately fake values on
reserved example domains. Loopback addresses support the offline Windows asyncio
test guard and are not company infrastructure. Local developer paths were removed
from public documentation. Git commit identity uses the owner's GitHub noreply
address. No local authentication configuration or Git internal metadata is included.

The reviewed captures contain public-instrument metadata and price/activity
measurements, not authentication headers or personal-account data. They are still
excluded for the separate redistribution concern below. No binary files are
needed in the published tree; generated archives/environments stay ignored.

## Source data and software licensing

Public HTTP accessibility was not accepted as permission to redistribute data.
A search for source-published redistribution terms on TSETMC's official domain
did not establish an explicit license; retrieval of the official homepage also
timed out during this audit. This is an unresolved permission question, not a
legal determination that redistribution is prohibited. Following the owner's
instruction, genuine captures and derived exports remain private locally.

The public docs retain aggregate historical findings, instrument identifiers and
the specific reported 2025-07-29 opening-price discrepancy. They do not distribute
the underlying archive. Synthetic fixtures/examples remain labeled as invented;
they are not replacements for, or proof of, the original live qualification.

The owner has not selected a software license. Public visibility does not itself
grant a reuse license for code or data. No third-party TSETMC client implementation
or fixture was copied. Reference links in the research document are attribution
and research context, not incorporation of GPL or other third-party source code.
An owner decision is needed before adding a software license, and explicit source
permission would be needed before reconsidering capture redistribution.

## Reproducibility boundary

Public-clone tests need no TSETMC internet access. Seven `private_capture` tests
skip explicitly when the original complete capture set is absent, and three live
tests skip unless `--live` is supplied. The private capture regressions remain
available to the owner without modifying or relabeling original inputs. The CLI's
dated offline smoke test uses the new clearly labeled synthetic daily fixture.

See [verification results](publication-verification.md),
[historical pilot report](pilot-verification.md), [file inventory](file-inventory.md)
and [future milestone proposal](next-milestones.md).
