# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- Always run `make ci` and fix all issues before pushing commits.
- Never commit directly on master. Always create a feature branch first.

## Build & Development Commands

```bash
make ci                # Full CI: lint, format-check, typecheck, test, build
make test              # Run all tests (PYTHONPATH=src poetry run pytest tests/ -v)
make lint              # Ruff check (src/ tests/)
make lint-fix          # Auto-fix lint issues
make format            # Auto-format with ruff
make typecheck         # MyPy strict mode (PYTHONPATH=src poetry run mypy)
make build             # Package both Lambda zips into .build/
make deploy            # Build + upload to AWS Lambda via CLI
make migrate           # Run Alembic migrations (needs DATABASE_URL)
make migrate-new name="description"  # Create new migration
```

Run a single test file: `PYTHONPATH=src poetry run pytest tests/worker/test_cathay_parser.py -v`
Run a single test: `PYTHONPATH=src poetry run pytest tests/worker/test_cathay_parser.py::test_name -v`

## Architecture

Serverless email processing pipeline that receives bank notification emails and extracts structured transaction data.

**Data flow:** Email → SES → S3 (raw) → Router Lambda → SQS → Worker Lambda → PostgreSQL

### Two Lambda functions (Python 3.12):
- **Router** (`src/spend_tracking/router/`): Triggered by S3 ObjectCreated. Validates recipient against registered addresses in DB, enqueues valid emails to SQS.
- **Worker** (`src/spend_tracking/worker/`): Triggered by SQS. Parses MIME email, runs bank-specific parser to extract transactions, persists email + transactions to DB.

### Clean architecture layers:
- **Domain** (`shared/domain/models.py`): Dataclasses — `RegisteredAddress`, `Email`, `Transaction`
- **Interfaces** (`shared/interfaces/`): ABCs — `EmailRepository`, `EmailStorage`, `EmailQueue`, `EmailParser`, `TransactionRepository`
- **Adapters** (`shared/adapters/`): Concrete implementations — S3, SQS, PostgreSQL (psycopg2 direct, no ORM)
- **Services** (`router/services/`, `worker/services/`): Orchestration logic with dependency injection via constructor
- **Handlers** (`router/handler.py`, `worker/handler.py`): Lambda entry points; wire dependencies from env vars at module level

### Parser plugin system (`worker/services/parsers/`):
Registry in `__init__.py` with `find_parser(to_address, subject)`. Each parser implements `EmailParser.can_parse()` and `EmailParser.parse()`. Currently: `CathayParser` (matches `cathay-*` addresses, extracts transactions from HTML tables using fixed cell offsets).

## Code Conventions

- **Type hints required** on all functions (`disallow_untyped_defs = true`), relaxed in tests
- **Union syntax:** `X | None` (not `Optional[X]`)
- **Line length:** 88 (ruff default)
- **Ruff rules:** E, F, I, W, UP, B, SIM
- **Logging:** `logging.getLogger(__name__)` with structured JSON extras
- **DB pattern:** Direct psycopg2 with `RETURNING` clauses, explicit `conn.commit()`
- **Domain models:** Plain `@dataclass`, no methods; `id: int | None` for pre-persistence

## Infrastructure

- **Terraform** in `infra/` — split by resource type (`ses.tf`, `s3.tf`, `lambda.tf`, `sqs.tf`, `iam.tf`, `ssm.tf`, `cloudflare.tf`)
- **S3 backend** in us-west-2 (`david74-terraform-remote-state-storage`), no DynamoDB locking
- **Secrets** via SSM Parameter Store (`/spend-tracking/db-connection-string`)
- **Lambda deploy** via `aws lambda update-function-code` (not Terraform-managed code)
- **CI/CD:** GitHub Actions — CI on PRs (`make ci`), CD on push to master (migrate + deploy)

## Adding a New Bank Parser

1. Create `src/spend_tracking/worker/services/parsers/bank_name.py` implementing `EmailParser`
2. Register in `worker/services/parsers/__init__.py` `_PARSERS` list
3. Add tests in `tests/worker/test_bank_name_parser.py`

## Plan Files (`docs/plans/`)

Plan files document design decisions and implementation steps for features. All plans live in `docs/plans/`.

### Naming

`YYYY-MM-DD-kebab-case-name-{design|implementation}.md`

Examples:
- `2026-02-21-email-spend-tracking-design.md`
- `2026-02-21-email-spend-tracking-implementation.md`
- `2026-02-22-bank-email-parsers-design.md`

### Types

**Design docs** (`-design.md`): High-level decisions, data models, architecture.
- Title: `# {Feature Name} — Design`
- Sections: Goal, Decisions (table), Data Model, Architecture, Testing

**Implementation plans** (`-implementation.md`): Step-by-step build instructions.
- Title: `# {Feature Name} — Implementation Plan`
- Opens with: `> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.`
- Header block: **Goal**, **Architecture**, **Tech Stack** (one-liners)
- Body: `### Task N: Title` sections, each with **Files** (Modify/Create), numbered **Steps** (TDD: write test → fail → implement → pass → commit)

### Rules

- Every feature gets at least an implementation plan; add a design doc if there are non-trivial decisions.
- Plans are written **before** code. They are the source of truth for what to build.
- Use the date the plan was created, not the implementation date.
