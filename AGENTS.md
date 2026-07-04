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
- Write minimum code that solve problem. No speculative or unneeded changes.
- Touch only what must. Clean own mess. Leave workspace cleaner than found.
- Define success criteria before changes. Verify against criteria, iterate until satisfied.
- Keep code complexity <= 10 for any new function, class, or method.
- Avoid duplication. Apply SOLID where practical.
- Document assumptions, constraints, design intent in comments or commit notes when matter.
- Prefer explicit, maintainable solutions over clever shortcuts.
- Propose business/design patterns + DDD only when improve clarity or structure.
- ALWAYS record review findings in `TODO.md` — never report only in chat. Any time
  scan, review, audit, or "look for issues" (not just major changes), add each finding to
  matching category table in `TODO.md` before/while reporting.
- Major changes: rescan whole project. Create or update `TODO.md` with one table per relevant review category.
  Table format: `id | status | effort | description`.
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