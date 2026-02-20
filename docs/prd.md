# Email 流水號服務 — High Level PRD

## Overview

個人用的 inbound email 自動化處理服務。透過產生一次性 / 用途專屬的 email 地址（流水號），自動接收並解析銀行、信用卡等機構寄來的信件，將結構化資料存入資料庫供後續查詢使用。

## Goals

- **自動化收信**：不需手動登入信箱整理，信件進來即自動處理
- **結構化儲存**：將非結構化的 email 內容解析為可查詢的資料（金額、日期、帳單明細等）
- **低成本運行**：個人 side project，月成本控制在 $1 以內
- **簡單維護**：盡量 serverless，不需管 server

## Non-Goals

- 不需要自動回信功能
- 不需要 web UI（初期透過直接查 DB 或之後再加）
- 不需要即時處理，秒級延遲可接受
- 不處理超大附件（銀行信件通常不會有）

## Architecture

```
┌─────────┐    ┌──────────────┐    ┌────┐    ┌───────────────┐    ┌─────┐    ┌───────────────┐    ┌────────────┐
│ 寄件者   │───▶│ SES Inbound  │───▶│ S3 │───▶│ Lambda:Router │───▶│ SQS │───▶│ Lambda:Worker │───▶│ PostgreSQL │
└─────────┘    └──────────────┘    └────┘    └───────────────┘    └─────┘    └───────────────┘    └────────────┘
                                                   │                                                   ▲
                                                   │  查詢地址是否合法                                  │
                                                   └──────────────────────────────────────────────────────┘
```

### 元件說明

| 元件 | 服務 | 用途 |
|------|------|------|
| Email 接收 | AWS SES Inbound (catch-all) | 接收所有寄到指定 domain 的信件 |
| Raw Email 儲存 | AWS S3 | 儲存完整 MIME 格式原始信件，作為 source of truth |
| Router Lambda | AWS Lambda | 收到 S3 event 後，驗證收件地址是否為合法流水號，合法則發送 SQS message |
| 任務佇列 | AWS SQS | 解耦收信與處理，提供 retry / DLQ 機制 |
| Worker Lambda | AWS Lambda | 從 S3 取得原始信件，解析 MIME，抽取結構化資料，寫入 DB |
| 資料庫 | Neon PostgreSQL (free tier) | 儲存流水號地址 registry、解析後的信件資料 |

### SES Inbound 注意事項

- SES Inbound 僅在部分 region 可用：`us-east-1`、`us-west-2`、`eu-west-1`
- 需設定 domain 的 MX record 指向 SES（`inbound-smtp.<region>.amazonaws.com`）
- 使用 Receipt Rule 設定：Action = S3 Put
- Catch-all 模式：不需為每個流水號地址單獨設定 rule

## Email 地址產生策略

### 格式

```
{prefix}-{random_token}@{domain}
```

- **prefix**：用途標籤，例如 `bank`、`card`
- **random_token**：12 bytes 經 base64url 編碼，產生 16 字元亂碼
- **domain**：自有 domain

### 範例

```
bank-a1B2c3D4e5F6g7H8@mail.example.com
card-xYz9AbCdEfGhIjKl@mail.example.com
```

### 產生方式

```python
import secrets
import base64

def generate_email(prefix: str, domain: str) -> str:
    token = base64.urlsafe_b64encode(secrets.token_bytes(12)).decode().rstrip("=")
    return f"{prefix}-{token}@{domain}"
```

碰撞機率：12 bytes = 96 bits entropy，實際使用上不可能碰撞。

### 地址註冊

產生後寫入 `registered_addresses` 表，收信時 Router Lambda 查此表驗證。可透過 CLI script 或未來的 API 註冊新地址。

## Database Schema

使用 Neon PostgreSQL (free tier: 0.5 GB storage, 190 compute hours/月, auto-suspend)。

```sql
-- 已註冊的流水號地址
CREATE TABLE registered_addresses (
    id          BIGSERIAL PRIMARY KEY,
    address     TEXT UNIQUE NOT NULL,   -- 完整 email 地址
    prefix      TEXT NOT NULL,          -- 前綴分類 (bank, card, etc.)
    label       TEXT,                   -- 人類可讀標籤，例如 "玉山信用卡帳單"
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 收到的信件
CREATE TABLE emails (
    id          BIGSERIAL PRIMARY KEY,
    address     TEXT NOT NULL REFERENCES registered_addresses(address),
    sender      TEXT NOT NULL,
    subject     TEXT,
    body_html   TEXT,
    body_text   TEXT,
    raw_s3_key  TEXT NOT NULL,          -- S3 key for raw MIME email
    received_at TIMESTAMPTZ NOT NULL,   -- SES 收到的時間
    parsed_data JSONB,                  -- 解析出的結構化資料
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_emails_address ON emails(address);
CREATE INDEX idx_emails_received_at ON emails(received_at DESC);
CREATE INDEX idx_emails_parsed_data ON emails USING GIN(parsed_data);
```

### `parsed_data` JSONB 用途

每家銀行 / 信用卡的信件格式不同，使用 JSONB 彈性欄位儲存解析結果。例如：

```json
{
  "type": "credit_card_statement",
  "bank": "玉山銀行",
  "amount": 12345,
  "currency": "TWD",
  "billing_period": "2026-01",
  "due_date": "2026-02-15",
  "transactions": [
    {"date": "2026-01-03", "merchant": "全聯", "amount": 580}
  ]
}
```

Parser 可以逐步擴充，初期先存 raw，後續再加各銀行的 parser。

## Lambda 設計

### Router Lambda

- **觸發**：S3 Put Event（SES 存入 raw email 時）
- **職責**：
  1. 從 S3 event 取得 key，讀取信件 header（不需讀全文）
  2. 解析收件地址（`To` / `Delivered-To`）
  3. 查 DB `registered_addresses` 確認地址合法且 active
  4. 合法 → 發送 SQS message（payload: `{ s3_key, address, sender, received_at }`）
  5. 不合法 → log warning，不處理
- **Runtime**：Python 3.12
- **Timeout**：30 秒
- **Memory**：128 MB

### Worker Lambda

- **觸發**：SQS event
- **職責**：
  1. 從 S3 讀取完整 raw email
  2. 用 Python `email` 標準庫解析 MIME
  3. 抽取 sender、subject、body (HTML/text)
  4. 執行對應的 parser（依 sender domain 或 prefix 分派）
  5. 寫入 `emails` 表
- **Runtime**：Python 3.12
- **Timeout**：60 秒
- **Memory**：256 MB
- **SQS batch size**：1（簡化錯誤處理）

### 錯誤處理

- SQS visibility timeout = 5 分鐘
- Max receive count = 3，超過進 Dead Letter Queue
- DLQ 訊息可手動檢查後重新處理

## Cost Estimate

以一天 100 封、一個月 3,000 封估算：

| 項目 | 月成本 |
|------|--------|
| SES Inbound | $0（前 1,000 封免費，超過 $0.10/1000 封）→ ~$0.20 |
| S3 | ~$0（幾 MB 等級） |
| Lambda (Router + Worker) | ~$0（free tier: 1M requests + 400K GB-sec） |
| SQS | ~$0（free tier: 1M requests） |
| Neon PostgreSQL | $0（free tier） |
| Route53 Hosted Zone | $0.50 |
| **Total** | **~$0.70/月** |

## IaC & Deployment

- **IaC 工具**：待定（CDK / Terraform / SST）
- **部署 region**：SES Inbound 可用的 region（建議 `us-east-1`）
- **CI/CD**：初期手動部署，後續可加 GitHub Actions

## Future Enhancements (Out of Scope for V1)

- [ ] 簡易 Web UI / API 查詢已收信件
- [ ] 各銀行 email parser plugins（玉山、國泰、中信等）
- [ ] 定期報表產生（月支出摘要）
- [ ] 地址到期自動停用
- [ ] Telegram / LINE 通知
```