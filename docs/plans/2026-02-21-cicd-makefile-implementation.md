# CI/CD with GitHub Workflows + Makefile — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add CI/CD pipelines using GitHub Actions and a Makefile so that all checks (lint, format, typecheck, test, build) run on PRs, and merged code auto-deploys with migrations.

**Architecture:** Makefile targets reusable locally and in CI. Two GitHub workflows: CI on pull requests, CD on push to master.

**Tech Stack:** Ruff (lint + format), MyPy (type checking), pytest, GitHub Actions, Makefile

---

### Decisions

| Topic | Decision |
|-------|----------|
| CI trigger | On pull request to `main` |
| CD trigger | On push (merge) to `main` |
| Linting | `ruff` (lint + format) + `mypy` (type checking) |
| Terraform | Manual — not in pipeline |
| DB migrations | Auto — run **before** Lambda deploy in CD |

---

### Task 1: Add Dev Dependencies to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependencies and tool config**

Add `ruff` and `mypy` to `[tool.poetry.group.dev.dependencies]`, and add
`[tool.ruff]` and `[tool.mypy]` configuration sections.

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
ruff = "^0.11"
mypy = "^1.15"
boto3-stubs = {version = "^1.35", extras = ["boto3"]}

[tool.ruff]
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
mypy_path = "src"
packages = ["spend_tracking", "tests"]
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
check_untyped_defs = true
```

**Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add ruff, mypy, boto3-stubs dev dependencies"
```

---

### Task 2: Add Makefile Targets

**Files:**
- Modify: `Makefile`

**Step 1: Add lint, format, typecheck, and ci targets**

```makefile
lint:            ## Run ruff linter
	poetry run ruff check src/ tests/

lint-fix:        ## Run ruff linter with auto-fix
	poetry run ruff check --fix src/ tests/

format-check:    ## Check formatting (CI)
	poetry run ruff format --check src/ tests/

format:          ## Auto-format code (local)
	poetry run ruff format src/ tests/

typecheck:       ## Run mypy type checking
	poetry run mypy

ci:              ## Run all CI checks (lint, format, typecheck, test, build)
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) build
```

**Step 2: Commit**

```bash
git add Makefile
git commit -m "chore: add lint, format, typecheck, ci Makefile targets"
```

---

### Task 3: Create CI Workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Create the workflow**

Triggers on **pull requests** to `main`.

```yaml
name: CI
on:
  pull_request:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install Poetry
        run: pipx install poetry
      - name: Install dependencies
        run: poetry install
      - name: Run CI checks
        run: make ci
```

Single job calling `make ci` — keeps the workflow thin and the logic in the
Makefile where it's reusable locally.

**Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add CI workflow for pull requests"
```

---

### Task 4: Create CD Workflow

**Files:**
- Create: `.github/workflows/cd.yml`

**Step 1: Create the workflow**

Triggers on **push** to `main` (i.e. merged PRs).

```yaml
name: CD
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install Poetry
        run: pipx install poetry
      - name: Install dependencies
        run: poetry install
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      - name: Run migrations
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: make migrate
      - name: Build and deploy
        run: make deploy
```

**Order**: migrate → deploy (new schema first, then new code).

**Step 2: Commit**

```bash
git add .github/workflows/cd.yml
git commit -m "ci: add CD workflow for deploy on merge to main"
```

---

### Task 5: Configure GitHub Secrets

**Files:** None (manual configuration)

**Step 1: Set secrets in repo → Settings → Secrets and variables → Actions**

| Secret | Purpose |
|--------|---------|
| `AWS_ACCESS_KEY_ID` | AWS credentials for Lambda deploy |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials for Lambda deploy |
| `DATABASE_URL` | Neon PostgreSQL connection string for Alembic |

---

### Task 6: Verify Local Developer Workflow

**Files:** None (manual verification)

**Step 1: Run full CI locally**

```bash
make ci
```

**Step 2: Verify auto-fix commands work**

```bash
make lint-fix
make format
```