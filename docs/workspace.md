# Workspace and recovery checkpoints

The active checkout is `tsetmc-marketdata` on `main`. The companion company API
uses `tradingview-marketdata/main`; its current destination schema is `0011`.
Follow [company-delivery.md](company-delivery.md), and read root `HANDOFF.md` for
current validation and remaining limits.

Annotated tag `checkpoint/unified-dashboard-2026-10-21` preserves the verified
implementation before cleanup. Inspect it with `git show` or a detached worktree.
This source-code checkpoint is separate from a database backup or deployment.
`checkpoint/workspace-clean-2026-10-21` preserves the subsequent organized
workspace. Completed delivery/integration branches were removed after confirming
their commits are ancestors of `main`.

- `.local/`: private captures, backups, test evidence and local tools; preserved.
- `.local/notes/conversation-history/`: earlier conversation/handoff documents.
- `output/`: private exports; preserved.
- `.venv/`: the project's Python environment.
- `graphify-out/`: local generated navigation, excluded from release source.
- `docs/history/`: earlier agent context; current rules are in `AGENTS.md`/`CODEX.md`.

The private `LOCAL_WORKSPACE.md` identifies the external cleanup archive, which
holds the verified source snapshot and previous build outputs. Rebuild packages
from the intended commit instead of installing an old wheel by accident.

The original Foolad pilot, genuine captures, database backups and published
milestones remain preserved. This cleanup does not migrate, activate or deploy them.
