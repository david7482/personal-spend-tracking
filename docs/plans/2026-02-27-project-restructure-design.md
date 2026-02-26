# Project Restructure — Design

## Goal

Flatten the project structure: eliminate `shared/` indirection, merge `router/` and `worker/` into a single `lambda/` package, colocate tests with implementation files (Go-style `_test.py` suffix), and remove the top-level `tests/` directory.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Router + Worker merge | Single `lambda/` package with one `handler.py` | Both handlers share the same deployment package already; reduces directory nesting |
| Services organization | `lambda/services/` folder | Keeps service files grouped without re-introducing router/worker subdirs |
| `shared/` removal | Promote `adapters/`, `interfaces/`, `domains/` to `spend_tracking/` top-level | Removes unnecessary nesting; these are true top-level concerns |
| `domain` → `domains` | Rename | User preference |
| Test file convention | `_test.py` suffix, colocated | Go-style: `handler.py` → `handler_test.py`, same directory |
| `tests/` directory | Remove entirely | All tests move next to their implementation files |

## Structure

### Before

```
src/spend_tracking/
├── shared/
│   ├── domain/models.py
│   ├── interfaces/(...).py
│   └── adapters/(...).py
├── router/
│   ├── handler.py
│   └── services/validate_and_enqueue.py
└── worker/
    ├── handler.py
    └── services/
        ├── process_email.py
        ├── flex_message.py
        └── parsers/(...)
tests/
├── shared/test_models.py
├── router/test_validate_and_enqueue.py
└── worker/(...)
```

### After

```
src/spend_tracking/
├── domains/
│   ├── models.py
│   └── models_test.py
├── interfaces/
│   ├── email_parser.py
│   ├── email_repository.py
│   ├── email_storage.py
│   ├── email_queue.py
│   ├── transaction_repository.py
│   └── notification_sender.py
├── adapters/
│   ├── email_repository_db.py
│   ├── email_repository_db_test.py
│   ├── email_storage_s3.py
│   ├── email_queue_sqs.py
│   ├── transaction_repository_db.py
│   └── notification_sender_line.py
│   └── notification_sender_line_test.py
└── lambda/
    ├── handler.py              # email_router_handler() + email_worker_handler()
    ├── handler_test.py
    └── services/
        ├── validate_and_enqueue.py
        ├── validate_and_enqueue_test.py
        ├── process_email.py
        ├── process_email_test.py
        ├── flex_message.py
        ├── flex_message_test.py
        └── parsers/
            ├── __init__.py
            ├── cathay.py
            └── cathay_test.py
```

## Import Path Changes

| Old import | New import |
|------------|-----------|
| `spend_tracking.shared.domain.models` | `spend_tracking.domains.models` |
| `spend_tracking.shared.interfaces.*` | `spend_tracking.interfaces.*` |
| `spend_tracking.shared.adapters.*` | `spend_tracking.adapters.*` |
| `spend_tracking.router.handler.handler` | `spend_tracking.lambda.handler.email_router_handler` |
| `spend_tracking.worker.handler.handler` | `spend_tracking.lambda.handler.email_worker_handler` |
| `spend_tracking.router.services.*` | `spend_tracking.lambda.services.*` |
| `spend_tracking.worker.services.*` | `spend_tracking.lambda.services.*` |

## Config File Changes

### Terraform (`infra/lambda.tf`)
- Router handler: `spend_tracking.lambda.handler.email_router_handler`
- Worker handler: `spend_tracking.lambda.handler.email_worker_handler`

### Makefile
- `make test`: change `pytest tests/ -v` → `pytest src/ -v`
- `make lint` / `make format`: remove `tests/` from paths (tests are now in `src/`)
- Build targets: no change (they already copy all of `src/spend_tracking`)

### pyproject.toml
- `[tool.pytest.ini_options]`: `testpaths = ["src"]`
- `[tool.ruff]`: `src = ["src"]` (remove `"tests"`)
- `[tool.mypy]`: remove `"tests"` from `packages`, remove `[[tool.mypy.overrides]]` for `tests.*` — replace with override for `*_test` modules

### CLAUDE.md
- Update architecture section to reflect new structure
- Update test commands (paths and examples)

## Testing

After restructure, `make ci` must pass with all existing tests green under the new layout.