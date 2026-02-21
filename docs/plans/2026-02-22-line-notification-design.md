# LINE Transaction Notification — Design

## Goal

Send a LINE Flex Message whenever the worker Lambda successfully extracts transactions from a bank email. Transactions from a single email are grouped into one message.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LINE API | Messaging API (Bot) with push messages | Supports Flex Messages for rich card-style formatting |
| Recipient model | Configurable per registered address | `line_recipient_id` column on `registered_addresses`; NULL = no notification |
| Recipient lookup | Worker queries DB | Keeps SQS message contract unchanged; notification sender is self-contained |
| Message format | Flex Message (bubble) | Card layout with header (bank name), body (transaction rows), footer (total) |
| HTTP client | `urllib.request` (stdlib) | Simple POST with JSON; no SDK dependency needed |
| Credentials | SSM Parameter Store | `/spend-tracking/line-channel-access-token`; consistent with existing DB connection pattern |
| Error handling | Log and continue | Notification failure never blocks email processing |
| Integration point | Inline in `ProcessEmail` | Optional `NotificationSender` injected via constructor; follows existing DI patterns |

## Data Model

### Migration: add `line_recipient_id` to `registered_addresses`

```sql
ALTER TABLE registered_addresses ADD COLUMN line_recipient_id TEXT;
```

### Updated `RegisteredAddress` dataclass

```python
@dataclass
class RegisteredAddress:
    id: int
    address: str
    prefix: str
    label: str | None
    is_active: bool
    created_at: datetime
    line_recipient_id: str | None  # LINE user or group ID
```

## Architecture

### Data Flow

```
SQS → Worker Lambda → Parse Email → Save Email → Save Transactions → Send LINE Notification
                                                                         ↓
                                                              (log & continue on failure)
```

### New Components

- **`NotificationSender`** ABC in `shared/interfaces/` — method: `send_transaction_notification(address, transactions)`
- **`LineNotificationSender`** in `shared/adapters/` — implements the interface using LINE Messaging API push message endpoint
- **`ProcessEmail`** receives an optional `NotificationSender` via constructor injection

### LINE API

- Endpoint: `POST https://api.line.me/v2/bot/message/push`
- Auth: `Authorization: Bearer {channel_access_token}`
- Body: `{"to": "<recipient_id>", "messages": [{"type": "flex", "altText": "...", "contents": {...}}]}`

### Flex Message Template

Single bubble with header (bank + count), body (transaction rows with separator), footer (total).

```json
{
  "type": "bubble",
  "size": "mega",
  "header": {
    "type": "box",
    "layout": "vertical",
    "contents": [
      {
        "type": "text",
        "text": "🏦 國泰世華銀行",
        "weight": "bold",
        "size": "lg",
        "color": "#FFFFFF"
      },
      {
        "type": "text",
        "text": "💳 2 筆交易 · 2026/02/22",
        "size": "xs",
        "color": "#FFFFFFAA",
        "margin": "sm"
      }
    ],
    "backgroundColor": "#4A6B8A",
    "paddingAll": "18px",
    "paddingStart": "20px"
  },
  "body": {
    "type": "box",
    "layout": "vertical",
    "spacing": "lg",
    "paddingAll": "20px",
    "contents": [
      {
        "type": "box",
        "layout": "horizontal",
        "contents": [
          {
            "type": "box",
            "layout": "vertical",
            "contents": [
              {
                "type": "text",
                "text": "星巴克",
                "weight": "bold",
                "size": "md",
                "color": "#2C3E50"
              },
              {
                "type": "text",
                "text": "餐飲 · 02/22",
                "size": "xs",
                "color": "#A0A0A0",
                "margin": "xs"
              }
            ],
            "flex": 3
          },
          {
            "type": "text",
            "text": "NT$1,250",
            "weight": "bold",
            "size": "md",
            "color": "#2C3E50",
            "align": "end",
            "gravity": "center",
            "flex": 2
          }
        ]
      },
      {
        "type": "separator",
        "color": "#F0F0F0"
      },
      {
        "type": "box",
        "layout": "horizontal",
        "contents": [
          {
            "type": "box",
            "layout": "vertical",
            "contents": [
              {
                "type": "text",
                "text": "全聯福利中心",
                "weight": "bold",
                "size": "md",
                "color": "#2C3E50"
              },
              {
                "type": "text",
                "text": "購物 · 02/22",
                "size": "xs",
                "color": "#A0A0A0",
                "margin": "xs"
              }
            ],
            "flex": 3
          },
          {
            "type": "text",
            "text": "NT$3,500",
            "weight": "bold",
            "size": "md",
            "color": "#2C3E50",
            "align": "end",
            "gravity": "center",
            "flex": 2
          }
        ]
      }
    ]
  },
  "footer": {
    "type": "box",
    "layout": "horizontal",
    "contents": [
      {
        "type": "text",
        "text": "合計",
        "size": "sm",
        "color": "#8C8C8C",
        "gravity": "center"
      },
      {
        "type": "text",
        "text": "NT$4,750",
        "weight": "bold",
        "size": "lg",
        "color": "#2C3E50",
        "align": "end"
      }
    ],
    "backgroundColor": "#F4F6F9",
    "paddingAll": "18px",
    "paddingStart": "20px",
    "paddingEnd": "20px"
  }
}
```

Each transaction row: merchant name (bold) left, amount (bold) right, category + date as subtle metadata below merchant. Separator between rows.

Message content per transaction: amount, merchant, date, category.

## Testing

- **`LineNotificationSender` unit tests**: Mock `urllib.request`, verify JSON payload structure, endpoint, and headers
- **Flex Message builder unit tests**: Given `Transaction` list + bank name → assert generated JSON matches expected structure
- **`ProcessEmail` integration**: Mock `NotificationSender`, verify called after transactions saved, NOT called when no transactions parsed
- **Error isolation**: Mock sender to raise, verify `ProcessEmail` still completes (log and continue)
- **No integration tests against real LINE API** — manual verification only

## Infrastructure

- **SSM Parameter**: `/spend-tracking/line-channel-access-token`
- **Terraform**: Add SSM parameter resource in `ssm.tf`, add IAM read permission for worker Lambda
- **DB Migration**: `ALTER TABLE registered_addresses ADD COLUMN line_recipient_id TEXT`