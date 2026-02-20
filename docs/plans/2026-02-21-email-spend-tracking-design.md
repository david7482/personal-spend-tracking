# Email Spend Tracking Service — Design

## Summary

Inbound email automation service for personal spend tracking. Receives bank/credit card emails via AWS SES, stores raw emails in S3, and writes structured data to Neon PostgreSQL. V1 stores raw emails without bank-specific parsing.

## Decisions

| Decision | Choice |
|----------|--------|
| IaC | Terraform (single config, all AWS resources) |
| TF State | S3 backend (`david74-terraform-remote-state-storage`, us-west-2, no DynamoDB lock) |
| Region | `us-east-1` (SES inbound requirement) |
| Email domain | `mail.david74.dev` (Cloudflare DNS, MX → SES) |
| Database | Neon PostgreSQL (us-east-1, free tier) |
| Lambda runtime | Python 3.12 |
| Package manager | Poetry monorepo |
| Lambda deploy | Makefile + `aws lambda update-function-code` |
| Secrets | AWS SSM Parameter Store (DB connection string) |
| Code architecture | Clean architecture (domain, interfaces, adapters, services) |
| V1 parsing | Raw storage only, no bank-specific parsers |

## Project Structure

```
personal-spend-tracking/
├── doc/
│   └── prd.md
├── docs/plans/
├── infra/
│   ├── backend.tf
│   ├── provider.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── ses.tf
│   ├── s3.tf
│   ├── sqs.tf
│   ├── lambda.tf
│   ├── iam.tf
│   └── ssm.tf
├── src/
│   └── spend_tracking/
│       ├── __init__.py
│       ├── router/
│       │   ├── __init__.py
│       │   ├── handler.py
│       │   └── services/
│       │       ├── __init__.py
│       │       └── validate_and_enqueue.py
│       ├── worker/
│       │   ├── __init__.py
│       │   ├── handler.py
│       │   └── services/
│       │       ├── __init__.py
│       │       └── process_email.py
│       └── shared/
│           ├── __init__.py
│           ├── interfaces/
│           │   ├── __init__.py
│           │   ├── email_repository.py
│           │   ├── email_storage.py
│           │   └── email_queue.py
│           ├── adapters/
│           │   ├── __init__.py
│           │   ├── email_storage_s3.py
│           │   ├── email_queue_sqs.py
│           │   └── email_repository_db.py
│           └── domain/
│               ├── __init__.py
│               └── models.py
├── tests/
│   ├── __init__.py
│   ├── router/
│   │   ├── __init__.py
│   │   └── test_validate_and_enqueue.py
│   ├── worker/
│   │   ├── __init__.py
│   │   └── test_process_email.py
│   └── shared/
│       ├── __init__.py
│       └── test_models.py
├── pyproject.toml
├── Makefile
└── README.md
```

## Terraform Resources

**backend.tf** — S3 backend (`david74-terraform-remote-state-storage` in us-west-2).

**provider.tf** — AWS provider, `us-east-1`.

**ses.tf** — `aws_ses_domain_identity` for `mail.david74.dev`, receipt rule set (active), catch-all receipt rule with S3 Put action.

**s3.tf** — Raw email bucket, S3 event notification to Router Lambda on `s3:ObjectCreated:*`, bucket policy allowing SES to write.

**sqs.tf** — Processing queue, DLQ (maxReceiveCount = 3), visibility timeout = 5 minutes.

**lambda.tf** — Router Lambda (128MB, 30s timeout, S3 trigger) and Worker Lambda (256MB, 60s timeout, SQS trigger, batch size 1). Both start with a placeholder zip.

**iam.tf** — Router role (read S3, send SQS, read SSM, CloudWatch Logs), Worker role (read S3, read SSM, CloudWatch Logs).

**ssm.tf** — SSM parameter for Neon PG connection string (SecureString, value set manually).

## Clean Architecture

**Domain** (`shared/domain/`) — Pure Python dataclasses (`RegisteredAddress`, `Email`). No AWS SDK, no DB drivers.

**Interfaces** (`shared/interfaces/`) — ABCs defining contracts: `EmailRepository`, `EmailStorage`, `EmailQueue`.

**Adapters** (`shared/adapters/`) — Concrete implementations: `email_storage_s3.py`, `email_queue_sqs.py`, `email_repository_db.py`.

**Services** (`router/services/`, `worker/services/`) — Business logic depending only on interfaces and domain. Receive adapter instances via constructor injection.

**Handler** (`handler.py`) — Thin entry point. Wires up adapters, calls service. Only place aware of Lambda event structure.

## Data Flow

1. Sender → `bank-xxx@mail.david74.dev`
2. Cloudflare MX → SES inbound SMTP (us-east-1)
3. SES receipt rule → raw MIME to S3

**Router Lambda** (S3 trigger):
1. Extract S3 key from event
2. Read email headers from S3
3. Extract recipient address
4. Query `registered_addresses` — active?
5. Yes → SQS message: `{ s3_key, address, sender, received_at }`
6. No → log warning, return

**Worker Lambda** (SQS trigger):
1. Read full raw email from S3
2. Parse MIME with Python `email` stdlib
3. Extract sender, subject, body_text, body_html
4. `parsed_data` = null (V1)
5. Insert into `emails` table

**Errors:** SQS visibility timeout 5 min, max receives 3, then DLQ.

## Makefile & Deployment

**Build:** `poetry export` deps → pip install into `.build/<lambda>/` → copy source → zip.

**Deploy:** `aws lambda update-function-code --function-name <name> --zip-file fileb://.build/<lambda>.zip`

**Targets:** `build-router`, `build-worker`, `build`, `deploy-router`, `deploy-worker`, `deploy`, `clean`.

**First-time:** `terraform apply` creates Lambdas with placeholder zip, then `make deploy` pushes real code.

## Testing (V1)

Unit tests only. Mock all adapters via interfaces.

- **Services** — inject mocks, test business logic in isolation
- **Domain models** — test dataclass construction
- **Adapters/Handlers** — not unit tested in V1
- **Runner:** pytest
