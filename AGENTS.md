# Repository instructions

## Current scope and boundaries

This independent repository implements TSETMC collection, PostgreSQL storage and
opt-in HTTPS synchronization to the shared company API. The owner authorized
integration, review fixes, Git checkpoints and workspace cleanup. No unattended
service or expanded live coverage has been activated.

Read CODEX.md, HANDOFF.md, relevant source/tests and Git status before substantive
work. Preserve unrelated changes. Detailed operations belong in docs/; HANDOFF.md
records current state, not policy. Historical milestone instructions are archived
under docs/history/ and do not override current authorization.

## Data and ownership invariants

- Only insCode `46348559193224090` (فولاد) is approved for live collection. Use invented
  instruments for isolation tests; do not expand live instruments without authorization.
- Preserve raw payloads and source uncertainty. Use Decimal for source measurements,
  aware UTC instants and Gregorian trading dates. Never conflate last trade and
  official close, or ChartData volume and value. Default exports select finalized data.
- Scope storage, locks, keys and provenance by instrument. Keep collector and delivery
  ownership fences intact; HTTPS must hold no SQL transaction or publication lock.
- Use Python3.12+, async httpx and additive migrations. Do not edit applied migrations
  or frozen schema metadata. Startup verifies the schema; it never migrates implicitly.
- Preserve the original persistent Foolad pilot as read-only. Do not migrate, enroll,
  seed, restore into or test-write that pilot. Never delete a persistent DB or volume.
- Keep TradingView databases, volumes, runtime settings and credentials independent.
  Company DB credentials do not belong on the source worker.
- Never commit secrets, genuine captures or database backups. Keep those in ignored
  `.local/`, `output/` or `docs/evidence/`. Public examples must be clearly synthetic.
- Preserve published milestones, including v0.1.0-milestone1 and commits
  87690cb1f03f2b3deecb122c58eb48c06dff4e06 and 01a827be39bb48864d0b76c8e952f176a4904556.
  No software license has been selected; do not add one without instruction.

## Validation and handoff

Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and
`uv run pytest` for relevant changes. Tests are offline by default. PostgreSQL
checks use `--postgres` and uniquely created `tsetmc_test_<hex>` databases on a
positively identified disposable endpoint. Live probes are explicit, paced,
read-only and bounded. Do not claim a check passed unless it actually ran.

Update HANDOFF.md and affected docs before ending meaningful work. Keep current
instructions concise and move obsolete context to docs/history/.

## graphify


This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
