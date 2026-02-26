# LINE Webhook Receiver Pipeline — Design

## Goal

Receive LINE messages via webhook, persist them to the database, and forward to an SQS queue that triggers a worker Lambda (no-op for now, ready for future logic).

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Lambda exposure | Function URL | Single endpoint, no extra infra, free |
| Pipeline shape | Webhook Lambda -> SQS -> Worker Lambda | Matches existing email pipeline pattern |
| Packaging | Same `lambdas/` package, shared zip | All handlers share code; one build target |
| Webhook security | HMAC-SHA256 signature verification | Prevents spoofed webhook calls |
| IAM | Single shared role for all Lambdas | Simplifies infra; all Lambdas in same trust boundary |
| DB storage | Parsed fields + raw JSON event | Queryable columns with full event for flexibility |

## Data Model

New `line_messages` table:

```sql
CREATE TABLE line_messages (
    id            BIGSERIAL PRIMARY KEY,
    line_user_id  TEXT NOT NULL,
    message_type  TEXT NOT NULL,
    message       TEXT,
    reply_token   TEXT,
    raw_event     JSONB NOT NULL,
    timestamp     TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);
```

New `LineMessage` domain dataclass matching this schema.

## Architecture

### Data Flow

```
LINE Platform --POST--> Lambda Function URL (line_webhook_router_handler)
  --> Verify X-Line-Signature (HMAC-SHA256 with channel secret)
  --> Parse webhook events, filter for message events
  --> Save each message to line_messages table
  --> Enqueue message ID to SQS (line-message-processing queue)
  --> Return 200 OK

SQS --> Lambda (line_message_worker_handler)
  --> Read message ID from queue
  --> No-op (log + return)
```

### Code Components

| Layer | Component | Location |
|-------|-----------|----------|
| Domain | `LineMessage` dataclass | `domains/models.py` |
| Interface | `LineMessageRepository` ABC | `interfaces/line_message_repository.py` |
| Interface | `LineMessageQueue` ABC | `interfaces/line_message_queue.py` |
| Adapter | `DbLineMessageRepository` | `adapters/line_message_repository_db.py` |
| Adapter | `SQSLineMessageQueue` | `adapters/line_message_queue_sqs.py` |
| Service | `ReceiveLineWebhook` | `lambdas/services/receive_line_webhook.py` |
| Service | `ProcessLineMessage` (no-op) | `lambdas/services/process_line_message.py` |
| Handler | `line_webhook_router_handler` | `lambdas/handler.py` |
| Handler | `line_message_worker_handler` | `lambdas/handler.py` |

### Lambda Inventory (after)

| Lambda | Trigger | Handler |
|--------|---------|---------|
| `spend-tracking-email-router` | S3 ObjectCreated | `email_router_handler` |
| `spend-tracking-email-worker` | SQS (email-processing) | `email_worker_handler` |
| `spend-tracking-line-webhook-router` | Function URL (POST) | `line_webhook_router_handler` |
| `spend-tracking-line-message-worker` | SQS (line-message-processing) | `line_message_worker_handler` |

### Infrastructure Changes

- **IAM:** Merge existing 2 roles into 1 shared `spend-tracking-lambda` role with union of all permissions (S3, SQS send+receive on both queues, SSM for all params, CloudWatch Logs)
- **SQS:** New `line-message-processing` queue + `line-message-dlq`
- **SSM:** New `line-channel-secret` parameter (for HMAC verification)
- **Lambda:** Two new functions (`line-webhook-router` with Function URL, `line-message-worker` with SQS trigger)
- **Makefile:** Single `build` target producing one zip; rename `deploy-router` -> `deploy-email-router`, `deploy-worker` -> `deploy-email-worker`; add `deploy-line-webhook-router`, `deploy-line-message-worker`

## Testing

- Unit tests for `ReceiveLineWebhook` service (signature verification, event parsing, DB save, SQS enqueue)
- Unit tests for `ProcessLineMessage` service (no-op behavior)
- Unit tests for `DbLineMessageRepository` adapter
- Handler tests for both new entry points
