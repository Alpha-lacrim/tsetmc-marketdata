# Public baseline verification

Verification performed on 2026-10-19 with Windows, PowerShell and Python 3.12.7.
These results describe publication checks, separately from the original historical
live investigation in [pilot-verification.md](pilot-verification.md).

| Check | Passed | Failed/errors | Skipped / not executed |
|---|---:|---:|---|
| Owner checkout offline pytest, with original private captures | 139 | 0 | 3 opt-in live tests skipped |
| Publication snapshot offline pytest, without private captures | 132 | 0 | 7 private-capture and 3 opt-in live tests skipped |
| Ruff lint / formatting | both passed | 0 | none |
| Strict mypy | 19 source/script files | 0 | tests not type-checked |
| uv sync --locked | passed | 0 | none |
| Wheel and source distribution builds | both passed | 0 | none |
| Archive inspection for excluded/private artifacts | both passed | 0 | none |
| Independent wheel install and offline ChartData export | passed | 0 | none |
| Canonical and legacy synthetic ChartData checks | both passed | 0 | none |
| TSETMC live tests during publication | — | — | 3 not executed; no source access needed for publication |
| Local Linux execution | — | — | not executed on this Windows host |

The public and owner suites both collect 142 tests. Their difference is entirely
the seven genuine-capture regressions, which require the unchanged private inputs.
There are no test failures concealed by converting them to skips. The dated CLI
smoke test now uses a clearly labeled synthetic fixture so it remains independently
reproducible in the public tree. No source capture was replaced or relabeled.

The original three live tests passed in the earlier Milestone 1 qualification;
they were not rerun for this publication task. Public CI requires no TSETMC network
access, secrets, PostgreSQL or live credentials. The minimal GitHub Actions workflow
checks Windows and Linux using immutable action revisions. Its actual remote result
must be inspected after publication, rather than inferred from this local report.

The package audit initially found a backed-up `.env.example` inside the source
archive. It contained safe defaults, but an audit backup is still inappropriate
distribution content. The Git exception was anchored to the root `.env.example`,
and explicit build exclusions were added for private/local directories. Rebuilt
wheel/source archives passed inspection before publication. No problematic archive
was uploaded or published as an artifact.

Runtime files under `src/` and `scripts/` are byte-for-byte unchanged from the
original local Milestone 1 backup. Genuine local capture/evidence files are also
unchanged. Pure adapter checks confirmed equal aligned arrays, chronological order,
official-close mapping, f=count, g=volume, h=value, numeric JSON and legacy i:null.
The wheel smoke test imports the installed package from a fresh virtual environment.

Reproduce from the repository root after dependency installation:

```powershell
uv sync --locked
uv run --offline pytest
uv run --offline ruff check .
uv run --offline ruff format --check .
uv run --offline mypy
uv build --offline
uv run --offline python -m tsetmc_marketdata.cli export-chartdata --input tests/fixtures/synthetic-history.json --output output/chartdata.json
```

An offline build requires the build dependencies to have been cached; otherwise
run `uv build` once with package-index access. The tests themselves require no
internet. The public fixture/publication decisions are documented in
[publication-audit.md](publication-audit.md).
