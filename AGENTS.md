# Agents Behavior Guide

This file defines the expected behavior and usage model for AI agents working in this repository.

## Purpose

- Provide a standard set of guidelines for agent interactions.
- Ensure consistent behavior when using AI tooling in this workspace.

## General Agent Behavior

- Always be polite and concise.
- Prefer short, actionable responses.
- Respect workspace context and avoid guessing when information is missing.
- When making code changes, clearly describe what was changed and why.
- When editing files, include exact context around replacements to avoid ambiguity.

## Rules

- Don't assume. Don't hide confusion. Surface tradeoffs and ask the user when unclear.
- Write the minimum code that solves the problem. Avoid speculative or unneeded changes.
- Touch only what you must. Clean up only your own mess and leave the workspace cleaner than you found it.
- Define success criteria before making changes. Verify against those criteria and iterate until satisfied.
- Keep code complexity <= 10 for any new function, class, or method.
- Avoid code duplication and apply SOLID principles where practical.
- Document assumptions, constraints, and design intent in comments or commit notes when they matter.
- Prefer explicit, maintainable solutions over clever shortcuts.
- Propose business/design patterns and DDD only when they improve clarity or structure.
- ALWAYS record review findings in `TODO.md` — never report them only in chat. Any time you
  scan, review, audit, or "look for issues" (not just major changes), add each finding to the
  matching category table in `TODO.md` before/while reporting it.
- When making major changes, rescan the whole project and create or update `TODO.md` with one table per relevant review category.
  Each table should use the format: `id | status | effort | description`.
  - security
  - code complexity
  - code duplication
  - reliability/correctness
  - performance
  - scalability
  - concurrency
  - robustness/recovery — interrupted writes, partial output files, resume safety, and cleanup after failed generation.
  - architecture/modularity/SOLID
  - decoupling
  - business/design patterns/DDD
  - plugin extensibility — public generator extension points, entry-point loading, and registry behavior.
  - CLI / option integrity — CLI declarations, help text, defaults, exit codes, and library behavior stay aligned.
  - configuration discoverability — config schema, defaults, examples, and validation errors are documented and tested.
  - data governance — no secrets, private absolute paths, or sensitive generated datasets are committed.
  - dependency — optional or future dependencies are declared intentionally and degrade gracefully.
  - platform — path, encoding, multiprocessing, and shell behavior stays portable across supported Python platforms.
  - observability when the application has it
  - documentation — README, examples, CLI help, and public API docs stay truthful.

## File Editing

- Avoid overwriting existing files unless the user explicitly asks or the file is missing.
- For text edits, preserve surrounding context and keep modifications minimal.
- Use repository-specific structure and conventions when adding or updating files.

## Communications

- Use headings and bullets for readability.
- Highlight changed files and key points.
- Keep final answers brief and professional.

## References

- This workspace contains a small dependency-free Python package, examples, and tests, so agent actions should remain lightweight and focused.
