# Agents Behavior Guide

File define expected behavior + usage model for AI agents in this repo.

## Purpose

- Give standard guidelines for agent interactions.
- Keep behavior consistent when use AI tooling in workspace.

## General Agent Behavior

- Be polite, concise.
- Prefer short, actionable responses.
- Respect workspace context. No guess when info missing.
- Code changes: describe what changed + why.
- Edit files: include exact context around replacements to avoid ambiguity.

## Rules

- No assume. No hide confusion. Surface tradeoffs, ask user when unclear.
- Report every contradiction encountered, of any kind, to the user and record each
  as a separate `blocked` item in `TODO.md`. Include the conflicting statements or
  behaviors, their sources, the impact, and the decision or change needed to resolve
  the contradiction. This applies to instructions, requirements, code, tests,
  configuration, documentation, and any other source. Never silently omit a contradiction.
- Write minimum code that solve problem. No speculative or unneeded changes.
- Compatibility is not a goal: we can freely change everything. Remove legacy layers,
  shims, deprecated paths, signature sniffing, and alternate spec forms instead of
  preserving them. Breaking changes to the public API, CLI, config schema, and file
  formats are acceptable when they make the architecture cleaner, leaner, more robust,
  or faster. Do not add deprecation periods, compatibility notes, or migration shims.
- Touch only what must. Clean own mess. Leave workspace cleaner than found.
- Define success criteria before changes. Verify against criteria, iterate until satisfied.
- Keep code complexity <= 10 for any new function, class, or method.
- Avoid duplication. Apply SOLID where practical.
- Document assumptions, constraints, design intent in comments or commit notes when matter.
- Prefer explicit, maintainable solutions over clever shortcuts.
- Treat TON as a batch-processing system: never impose hard CPU, memory,
  row-width, expansion, pool-size, precision, or workload caps, and do not
  reject otherwise valid jobs because they are large. Prefer streaming, lazy
  evaluation, chunking, spill-to-disk, backpressure, and explicit
  operator-controlled settings without restrictive defaults. Reject or
  rewrite review findings that propose hard resource caps.
- Unpack TODO findings into the smallest independently actionable items by default.
  Keep an item whole only when it is genuinely atomic or splitting it would create
  artificial work; record that reason in the item description when it is not obvious.
- Propose business/design patterns + DDD only when improve clarity or structure.
- ALWAYS record review findings in `TODO.md` — never report only in chat. Any time
  scan, review, audit, or "look for issues" (not just major changes), add each finding to
  the matching lifecycle table in `TODO.md` before/while reporting.
- Major changes: rescan whole project. Create or update `TODO.md` with one table per lifecycle
  section: `Open`, `Blocked / Deferred`, `Rejected / Won't fix`. Remove items once done.
  Table format: `id | status | severity | effort | description`. Ids carry a category prefix
  (e.g. `REL-021`, `CFG-004`); descriptions open with the review category. Categories:
  - security
  - code complexity
  - code duplication
  - reliability/correctness
  - performance
  - scalability
  - concurrency
  - robustness/recovery — interrupted writes, partial output files, resume safety, cleanup after failed generation.
  - architecture/modularity/SOLID
  - decoupling
  - business/design patterns/DDD
  - plugin extensibility — public generator extension points, entry-point loading, registry behavior.
  - CLI / option integrity — CLI declarations, help text, defaults, exit codes, library behavior stay aligned.
  - configuration discoverability — config schema, defaults, examples, validation errors documented + tested.
  - data governance — no secrets, private absolute paths, or sensitive generated datasets committed.
  - dependency — optional or future dependencies declared intentionally, degrade gracefully.
  - platform — path, encoding, multiprocessing, shell behavior stay portable across supported Python platforms.
  - observability when app has it
  - documentation — README, examples, CLI help, public API docs stay truthful.

## File Editing

- No overwrite existing files unless user explicit ask or file missing.
- Text edits: preserve surrounding context, keep modifications minimal.
- Use repo-specific structure + conventions when add or update files.

## Communications

- Use headings + bullets for readability.
- Highlight changed files + key points.
- Keep final answers brief, professional.

## References

- Workspace has small dependency-free Python package, examples, tests. Agent actions stay lightweight + focused.
