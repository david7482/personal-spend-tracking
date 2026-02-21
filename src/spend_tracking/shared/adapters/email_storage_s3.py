import boto3

from spend_tracking.shared.interfaces.email_storage import EmailStorage


class S3EmailStorage(EmailStorage):
    def __init__(self, bucket: str) -> None:
        self._s3 = boto3.client("s3")
        self._bucket = bucket

    def get_email_headers(self, s3_key: str) -> bytes:
        response = self._s3.get_object(
            Bucket=self._bucket,
            Key=s3_key,
            Range="bytes=0-8191",
        )
        return bytes(response["Body"].read())

    def get_email_raw(self, s3_key: str) -> bytes:
        response = self._s3.get_object(
            Bucket=self._bucket,
            Key=s3_key,
        )
        return bytes(response["Body"].read())
