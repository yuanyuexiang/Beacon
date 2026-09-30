# Repository Guidelines

## Project Structure & Module Organization

Beacon is a planning-stage restaurant menu sales intelligence project. No application source, automated tests, or build configuration exists yet.

- `欧洲餐厅菜单设计与印刷获客系统方案.md`: primary product proposal.
- `plan/roadmap.md`: validation-first phases and implementation boundaries.
- `plan/validation.md`: sampling, evidence, channel eligibility, metrics, and decision gates.
- `plan/archive/`: historical plans, not current instructions.
- `plan/tasks.md` and `plan/decisions.md`: task status and decision records.
- `reports/`: synthesized research reports.
- `research_notes/`: supporting research grouped by report topic.
- `汇报/`: presentation assets (`.pptx`).

Future code may use `backend/` (FastAPI), `frontend/` (Next.js), `templates/`, `infra/`, and `scripts/`; these directories are not implemented.

## Build, Test, and Development Commands

No build, test, or server commands exist. For documentation, run:

- `rg --files`: inspect available documents.
- `git diff --check`: detect whitespace errors in tracked changes.
- `git diff --stat` and `git status --short`: review scope, including newly created files.

When scaffolding lands, document verified commands here and in `CLAUDE.md`. The draft roadmap selects uv, pnpm, and Docker Compose; do not assume they are configured.

## Coding Style & Naming Conventions

Write project documentation in Chinese. Use descriptive headings, relative links, and comparison tables. Preserve topic-based filenames and list indentation. Cite research sources; distinguish proposals from decisions.

No formatter or linter is installed. The planned code toolchain uses Ruff and mypy; establish indentation and naming conventions when adding source code.

## Testing Guidelines

For document changes, check links, paths, and consistency across the proposal, roadmap, and tasks. Preview changed Markdown and slides.

Planned testing includes pytest, Vitest/Testing Library, and Playwright. Prioritize eligibility, approval, suppression, and retry rules with success/failure paths; global coverage targets are deferred. Future fixtures belong in `backend/tests/fixtures/`; ordinary tests should use local fixtures and `FakeProvider`. Test naming conventions and executable commands remain to be established.

## Commit & Pull Request Guidelines

Use imperative English commit subjects, matching history: “Add proposal …” or “Refactor code structure …”. No prefix is required.

Keep changes focused. PRs should describe the purpose, affected documents or milestones, related issues/tasks, and validation performed. Include screenshots for presentation or future UI changes.

## Contributor Workflow

Read `CLAUDE.md`, the proposal, and roadmap before feature work. Update task checkboxes and progress when starting or completing tracked tasks; record resolved design choices in `plan/decisions.md`. Sample sourcing is deferred by user request. Do not treat process approval as authorization to contact prospects. Preserve unrelated working-tree changes.
