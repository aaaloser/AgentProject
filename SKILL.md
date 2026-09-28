---
name: mokioclaw-design-gate
description: Use for every task involving this MokioClaw repository until the user explicitly declares the project finished; read the full authoritative dashboard design before acting.
---

# MokioClaw project design gate

This is the project-root skill requested by the user. It applies to every new task involving this repository, including planning, read-only inspection, implementation, tests, review, and documentation. A new task starts when the user gives a new objective; multiple steps within one task do not require repeated reads.

## Required first step

Before taking any task action, read the entire file:

docs/superpowers/specs/2026-09-26-mokioclaw-local-repository-review-dashboard-design.md

Then also read the entire current Stage B design, which is a draft until the user approves it:

docs/superpowers/specs/2026-09-28-mokioclaw-local-codeagent-dashboard-design.md

Read both complete files, not search hits, heading lists, excerpts, prior summaries, or memory of an earlier task. On Windows, a full Get-Content -LiteralPath ... -Raw read is suitable. If either file is missing or cannot be read in full, report that condition and stop work that depends on this repository.

After reading, check the current request against the design's scope, data contracts, safety boundaries, acceptance criteria, and phase gates. State any material conflict before acting. A newer explicit user instruction takes precedence; update the design when the approved product direction changes so the next task receives accurate guidance.

The design is context, not permission to start provider calls, real Agent experiments, modify frozen Rich/Click evidence, commit, push, alter remotes, or publish. Those actions retain their separate authorization boundaries.

This requirement remains active until the user explicitly says the MokioClaw project has ended. Completing one stage or one task does not end it.
