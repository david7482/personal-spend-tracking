import json

import boto3
import psycopg2

from spend_tracking.shared.domain.models import Transaction
from spend_tracking.shared.interfaces.transaction_repository import TransactionRepository


class DbTransactionRepository(TransactionRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def save_transactions(self, transactions: list[Transaction]) -> None:
        if not transactions:
            return
        with psycopg2.connect(self._connection_string) as conn:
            with conn.cursor() as cur:
                for txn in transactions:
                    cur.execute(
                        "INSERT INTO transactions "
                        "(source_type, source_id, bank, transaction_at, region, "
                        "amount, currency, merchant, category, notes, raw_data, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "RETURNING id",
                        (
                            txn.source_type,
                            txn.source_id,
                            txn.bank,
                            txn.transaction_at,
                            txn.region,
                            txn.amount,
                            txn.currency,
                            txn.merchant,
                            txn.category,
                            txn.notes,
                            json.dumps(txn.raw_data) if txn.raw_data else None,
                            txn.created_at,
                        ),
                    )
                    txn.id = cur.fetchone()[0]
            conn.commit()
