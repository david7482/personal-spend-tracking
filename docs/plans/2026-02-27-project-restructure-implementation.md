# Project Restructure — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Flatten the project structure — eliminate `shared/`, merge `router/`+`worker/` into `lambda/`, colocate tests with `_test.py` suffix, remove `tests/` dir.

**Architecture:** Move files to new paths, update all imports, update config files (Makefile, pyproject.toml, Terraform, CLAUDE.md). No logic changes.

**Tech Stack:** Python 3.12, Poetry, Ruff, MyPy, Pytest, Terraform

---

### Task 1: Create new directory structure and move domain/interfaces/adapters

Create the new top-level directories under `spend_tracking/` and move files out of `shared/`.

**Files:**
- Create: `src/spend_tracking/domains/__init__.py`
- Move: `src/spend_tracking/shared/domain/models.py` → `src/spend_tracking/domains/models.py`
- Create: `src/spend_tracking/interfaces/__init__.py`
- Move: `src/spend_tracking/shared/interfaces/*.py` → `src/spend_tracking/interfaces/`
- Create: `src/spend_tracking/adapters/__init__.py`
- Move: `src/spend_tracking/shared/adapters/*.py` → `src/spend_tracking/adapters/`

**Step 1: Create directories and move files**

```bash
mkdir -p src/spend_tracking/domains src/spend_tracking/interfaces src/spend_tracking/adapters

# domains
cp src/spend_tracking/shared/domain/__init__.py src/spend_tracking/domains/__init__.py
mv src/spend_tracking/shared/domain/models.py src/spend_tracking/domains/models.py

# interfaces
cp src/spend_tracking/shared/interfaces/__init__.py src/spend_tracking/interfaces/__init__.py
mv src/spend_tracking/shared/interfaces/email_parser.py src/spend_tracking/interfaces/
mv src/spend_tracking/shared/interfaces/email_repository.py src/spend_tracking/interfaces/
mv src/spend_tracking/shared/interfaces/email_storage.py src/spend_tracking/interfaces/
mv src/spend_tracking/shared/interfaces/email_queue.py src/spend_tracking/interfaces/
mv src/spend_tracking/shared/interfaces/transaction_repository.py src/spend_tracking/interfaces/
mv src/spend_tracking/shared/interfaces/notification_sender.py src/spend_tracking/interfaces/

# adapters
cp src/spend_tracking/shared/adapters/__init__.py src/spend_tracking/adapters/__init__.py
mv src/spend_tracking/shared/adapters/email_repository_db.py src/spend_tracking/adapters/
mv src/spend_tracking/shared/adapters/email_storage_s3.py src/spend_tracking/adapters/
mv src/spend_tracking/shared/adapters/email_queue_sqs.py src/spend_tracking/adapters/
mv src/spend_tracking/shared/adapters/transaction_repository_db.py src/spend_tracking/adapters/
mv src/spend_tracking/shared/adapters/notification_sender_line.py src/spend_tracking/adapters/
```

**Step 2: Remove the old `shared/` directory**

```bash
rm -rf src/spend_tracking/shared
```

**Step 3: Commit**

```bash
git add -A
git commit -m "refactor: move shared/ contents to top-level domains/, interfaces/, adapters/"
```

---

### Task 2: Create `lambda/` and merge router + worker

Merge `router/` and `worker/` into a single `lambda/` package with one `handler.py`.

**Files:**
- Create: `src/spend_tracking/lambda/__init__.py`
- Create: `src/spend_tracking/lambda/handler.py` (merged from router + worker handlers)
- Create: `src/spend_tracking/lambda/services/__init__.py`
- Move: `src/spend_tracking/router/services/validate_and_enqueue.py` → `src/spend_tracking/lambda/services/`
- Move: `src/spend_tracking/worker/services/process_email.py` → `src/spend_tracking/lambda/services/`
- Move: `src/spend_tracking/worker/services/flex_message.py` → `src/spend_tracking/lambda/services/`
- Move: `src/spend_tracking/worker/services/parsers/` → `src/spend_tracking/lambda/services/parsers/`

**Step 1: Create directories and move service files**

```bash
mkdir -p src/spend_tracking/lambda/services/parsers

# Create __init__.py files
touch src/spend_tracking/lambda/__init__.py
touch src/spend_tracking/lambda/services/__init__.py

# Move service files
mv src/spend_tracking/router/services/validate_and_enqueue.py src/spend_tracking/lambda/services/
mv src/spend_tracking/worker/services/process_email.py src/spend_tracking/lambda/services/
mv src/spend_tracking/worker/services/flex_message.py src/spend_tracking/lambda/services/
mv src/spend_tracking/worker/services/parsers/__init__.py src/spend_tracking/lambda/services/parsers/
mv src/spend_tracking/worker/services/parsers/cathay.py src/spend_tracking/lambda/services/parsers/
```

**Step 2: Create the merged `handler.py`**

Write `src/spend_tracking/lambda/handler.py`:

```python
import json
import logging
import os

import boto3

from spend_tracking.adapters.email_queue_sqs import SQSEmailQueue
from spend_tracking.adapters.email_repository_db import DbEmailRepository
from spend_tracking.adapters.email_storage_s3 import S3EmailStorage
from spend_tracking.adapters.notification_sender_line import LineNotificationSender
from spend_tracking.adapters.transaction_repository_db import DbTransactionRepository
from spend_tracking.lambda.services.process_email import ProcessEmail
from spend_tracking.lambda.services.validate_and_enqueue import ValidateAndEnqueue

logger = logging.getLogger()

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])

# Router dependencies
_queue = SQSEmailQueue(os.environ.get("SQS_QUEUE_URL", ""))
_router_service = ValidateAndEnqueue(_storage, _repository, _queue)

# Worker dependencies
_transaction_repository = DbTransactionRepository(
    os.environ["SSM_DB_CONNECTION_STRING"]
)

_notification_sender = None
_line_token_param = os.environ.get("SSM_LINE_CHANNEL_ACCESS_TOKEN")
if _line_token_param:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=_line_token_param, WithDecryption=True)
    _notification_sender = LineNotificationSender(
        channel_access_token=response["Parameter"]["Value"]
    )

_worker_service = ProcessEmail(
    _storage, _repository, _transaction_repository, _notification_sender
)


def email_router_handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        s3_key = record["s3"]["object"]["key"]
        logger.info("Processing S3 object", extra={"s3_key": s3_key})
        _router_service.execute(s3_key)


def email_worker_handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        extra = {
            "s3_key": body["s3_key"],
            "address": body["address"],
            "sender": body["sender"],
        }
        logger.info("Processing email", extra=extra)
        _worker_service.execute(
            s3_key=body["s3_key"],
            address=body["address"],
            sender=body["sender"],
            received_at=body["received_at"],
        )
```

**Step 3: Remove old router/ and worker/ directories**

```bash
rm -rf src/spend_tracking/router src/spend_tracking/worker
```

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: merge router/ and worker/ into lambda/ package"
```

---

### Task 3: Update all import paths

Fix every import that still references old paths (`shared.domain`, `shared.interfaces`, `shared.adapters`, `router.services`, `worker.services`).

**Files to modify:**
- `src/spend_tracking/interfaces/email_parser.py`
- `src/spend_tracking/interfaces/email_repository.py`
- `src/spend_tracking/interfaces/transaction_repository.py`
- `src/spend_tracking/interfaces/notification_sender.py`
- `src/spend_tracking/adapters/email_repository_db.py`
- `src/spend_tracking/adapters/email_storage_s3.py`
- `src/spend_tracking/adapters/email_queue_sqs.py`
- `src/spend_tracking/adapters/transaction_repository_db.py`
- `src/spend_tracking/adapters/notification_sender_line.py`
- `src/spend_tracking/lambda/services/validate_and_enqueue.py`
- `src/spend_tracking/lambda/services/process_email.py`
- `src/spend_tracking/lambda/services/flex_message.py`
- `src/spend_tracking/lambda/services/parsers/__init__.py`
- `src/spend_tracking/lambda/services/parsers/cathay.py`

**Step 1: Update imports in interfaces/**

In `src/spend_tracking/interfaces/email_parser.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/interfaces/email_repository.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/interfaces/transaction_repository.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/interfaces/notification_sender.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

**Step 2: Update imports in adapters/**

In `src/spend_tracking/adapters/email_repository_db.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
spend_tracking.shared.interfaces.email_repository → spend_tracking.interfaces.email_repository
```

In `src/spend_tracking/adapters/email_storage_s3.py`, change:
```
spend_tracking.shared.interfaces.email_storage → spend_tracking.interfaces.email_storage
```

In `src/spend_tracking/adapters/email_queue_sqs.py`, change:
```
spend_tracking.shared.interfaces.email_queue → spend_tracking.interfaces.email_queue
```

In `src/spend_tracking/adapters/transaction_repository_db.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
spend_tracking.shared.interfaces.transaction_repository → spend_tracking.interfaces.transaction_repository
```

In `src/spend_tracking/adapters/notification_sender_line.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
spend_tracking.shared.interfaces.notification_sender → spend_tracking.interfaces.notification_sender
spend_tracking.worker.services.flex_message → spend_tracking.lambda.services.flex_message
```

**Step 3: Update imports in lambda/services/**

In `src/spend_tracking/lambda/services/validate_and_enqueue.py`, change:
```
spend_tracking.shared.interfaces.email_queue → spend_tracking.interfaces.email_queue
spend_tracking.shared.interfaces.email_repository → spend_tracking.interfaces.email_repository
spend_tracking.shared.interfaces.email_storage → spend_tracking.interfaces.email_storage
```

In `src/spend_tracking/lambda/services/process_email.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
spend_tracking.shared.interfaces.email_repository → spend_tracking.interfaces.email_repository
spend_tracking.shared.interfaces.email_storage → spend_tracking.interfaces.email_storage
spend_tracking.shared.interfaces.notification_sender → spend_tracking.interfaces.notification_sender
spend_tracking.shared.interfaces.transaction_repository → spend_tracking.interfaces.transaction_repository
spend_tracking.worker.services.parsers → spend_tracking.lambda.services.parsers
```

In `src/spend_tracking/lambda/services/flex_message.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/lambda/services/parsers/__init__.py`, change:
```
spend_tracking.shared.interfaces.email_parser → spend_tracking.interfaces.email_parser
spend_tracking.worker.services.parsers.cathay → spend_tracking.lambda.services.parsers.cathay
```

In `src/spend_tracking/lambda/services/parsers/cathay.py`, change:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
spend_tracking.shared.interfaces.email_parser → spend_tracking.interfaces.email_parser
```

**Step 4: Verify no old imports remain**

```bash
grep -r "spend_tracking.shared" src/ && echo "FAIL: old imports remain" || echo "OK"
grep -r "spend_tracking.router" src/ && echo "FAIL: old imports remain" || echo "OK"
grep -r "spend_tracking.worker" src/ && echo "FAIL: old imports remain" || echo "OK"
```

Expected: all three print "OK"

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: update all import paths to new structure"
```

---

### Task 4: Colocate tests with implementation files

Move all test files from `tests/` to sit next to their implementation, renaming from `test_*.py` to `*_test.py`.

**File moves:**
- `tests/shared/test_models.py` → `src/spend_tracking/domains/models_test.py`
- `tests/router/test_validate_and_enqueue.py` → `src/spend_tracking/lambda/services/validate_and_enqueue_test.py`
- `tests/worker/test_process_email.py` → `src/spend_tracking/lambda/services/process_email_test.py`
- `tests/worker/test_cathay_parser.py` → `src/spend_tracking/lambda/services/parsers/cathay_test.py`
- `tests/worker/test_flex_message.py` → `src/spend_tracking/lambda/services/flex_message_test.py`
- `tests/worker/test_line_notification_sender.py` → `src/spend_tracking/adapters/notification_sender_line_test.py`

**Step 1: Move and rename test files**

```bash
mv tests/shared/test_models.py src/spend_tracking/domains/models_test.py
mv tests/router/test_validate_and_enqueue.py src/spend_tracking/lambda/services/validate_and_enqueue_test.py
mv tests/worker/test_process_email.py src/spend_tracking/lambda/services/process_email_test.py
mv tests/worker/test_cathay_parser.py src/spend_tracking/lambda/services/parsers/cathay_test.py
mv tests/worker/test_flex_message.py src/spend_tracking/lambda/services/flex_message_test.py
mv tests/worker/test_line_notification_sender.py src/spend_tracking/adapters/notification_sender_line_test.py
```

**Step 2: Remove old tests/ directory**

```bash
rm -rf tests
```

**Step 3: Update imports inside test files**

In `src/spend_tracking/domains/models_test.py`, change all:
```
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/lambda/services/validate_and_enqueue_test.py`, change:
```
spend_tracking.router.services.validate_and_enqueue → spend_tracking.lambda.services.validate_and_enqueue
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/lambda/services/process_email_test.py`, change:
```
spend_tracking.worker.services.process_email → spend_tracking.lambda.services.process_email
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/lambda/services/parsers/cathay_test.py`, change:
```
spend_tracking.worker.services.parsers.cathay → spend_tracking.lambda.services.parsers.cathay
```

In `src/spend_tracking/lambda/services/flex_message_test.py`, change:
```
spend_tracking.worker.services.flex_message → spend_tracking.lambda.services.flex_message
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

In `src/spend_tracking/adapters/notification_sender_line_test.py`, change:
```
spend_tracking.shared.adapters.notification_sender_line → spend_tracking.adapters.notification_sender_line
spend_tracking.shared.domain.models → spend_tracking.domains.models
```

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: colocate tests with implementation using _test.py suffix"
```

---

### Task 5: Update config files

Update Makefile, pyproject.toml, and Terraform to reflect the new structure.

**Files:**
- Modify: `Makefile`
- Modify: `pyproject.toml`
- Modify: `infra/lambda.tf`

**Step 1: Update `pyproject.toml`**

Change `[tool.pytest.ini_options]`:
```toml
[tool.pytest.ini_options]
testpaths = ["src"]
```

Change `[tool.ruff]`:
```toml
[tool.ruff]
target-version = "py312"
src = ["src"]
```

Change `[tool.mypy]` — remove `"tests"` from packages and update override:
```toml
[tool.mypy]
python_version = "3.12"
mypy_path = "src"
packages = ["spend_tracking"]
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
check_untyped_defs = true

[[tool.mypy.overrides]]
module = "spend_tracking.*_test"
disallow_untyped_defs = false
```

**Step 2: Update `Makefile`**

Change the `test` target:
```makefile
test:
	PYTHONPATH=src poetry run pytest src/ -v
```

Change `lint` target (remove `tests/`):
```makefile
lint:
	poetry run ruff check src/
```

Change `lint-fix` target:
```makefile
lint-fix:
	poetry run ruff check --fix src/
```

Change `format-check` target:
```makefile
format-check:
	poetry run ruff format --check src/
```

Change `format` target:
```makefile
format:
	poetry run ruff format src/
```

**Step 3: Update `infra/lambda.tf`**

Change the router handler line:
```
handler = "spend_tracking.lambda.handler.email_router_handler"
```

Change the worker handler line:
```
handler = "spend_tracking.lambda.handler.email_worker_handler"
```

Update the placeholder archive source filename:
```
filename = "spend_tracking/lambda/handler.py"
```

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: update config files for new project structure"
```

---

### Task 6: Update CLAUDE.md

Update the architecture docs and test commands to reflect the new structure.

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Update **Build & Development Commands** section — change single test examples:
```
Run a single test file: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambda/services/parsers/cathay_test.py -v`
Run a single test: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambda/services/parsers/cathay_test.py::test_name -v`
```

Update **Architecture** section to replace the two-Lambda and `shared/` references:

Replace the subsections:
- **Two Lambda functions** → describe single `lambda/` package with two handler entry points (`email_router_handler`, `email_worker_handler`)
- **Clean architecture layers** → update paths: `domains/models.py`, `interfaces/`, `adapters/`, `lambda/services/`, `lambda/handler.py`
- **Parser plugin system** → update path to `lambda/services/parsers/`

Update **Adding a New Bank Parser** — update paths:
```
1. Create `src/spend_tracking/lambda/services/parsers/bank_name.py` implementing `EmailParser`
2. Register in `lambda/services/parsers/__init__.py` `_PARSERS` list
3. Add tests in `src/spend_tracking/lambda/services/parsers/bank_name_test.py`
```

Update **Code Conventions** — add test file naming convention:
```
- **Test files:** Colocated with implementation, `_test.py` suffix (e.g., `handler.py` → `handler_test.py`)
```

**Step 2: Commit**

```bash
git add -A
git commit -m "docs: update CLAUDE.md for new project structure"
```

---

### Task 7: Run CI and fix issues

Run the full CI pipeline and fix any remaining issues.

**Step 1: Run lint and auto-fix**

```bash
make lint-fix
make format
```

**Step 2: Run typecheck**

```bash
make typecheck
```

Fix any mypy errors (likely from changed import paths missed earlier).

**Step 3: Run tests**

```bash
make test
```

All tests should pass. Fix any import errors.

**Step 4: Run full CI**

```bash
make ci
```

Expected: all green — lint, format, typecheck, test, build.

**Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve CI issues from restructure"
```

(Skip this commit if no fixes were needed.)