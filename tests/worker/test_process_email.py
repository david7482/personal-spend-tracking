from unittest.mock import MagicMock


def _make_multipart_email(
    from_addr: str = "sender@example.com",
    subject: str = "Test Subject",
    body_text: str = "Plain text body",
    body_html: str = "<p>HTML body</p>",
) -> bytes:
    boundary = "boundary123"
    return (
        f"From: {from_addr}\r\n"
        f"To: bank-abc@mail.david74.dev\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f'Content-Type: multipart/alternative; boundary="{boundary}"\r\n'
        f"\r\n"
        f"--{boundary}\r\n"
        f'Content-Type: text/plain; charset="utf-8"\r\n'
        f"\r\n"
        f"{body_text}\r\n"
        f"--{boundary}\r\n"
        f'Content-Type: text/html; charset="utf-8"\r\n'
        f"\r\n"
        f"{body_html}\r\n"
        f"--{boundary}--\r\n"
    ).encode()


def _make_plain_email(
    from_addr: str = "sender@example.com",
    subject: str = "Plain Email",
    body: str = "Just plain text",
) -> bytes:
    return (
        f"From: {from_addr}\r\n"
        f"To: bank-abc@mail.david74.dev\r\n"
        f"Subject: {subject}\r\n"
        f"Content-Type: text/plain\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode()


def test_processes_multipart_email():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()

    storage.get_email_raw.return_value = _make_multipart_email()

    service = ProcessEmail(storage, repository)
    service.execute(
        s3_key="some-key",
        address="bank-abc@mail.david74.dev",
        sender="sender@example.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    repository.save_email.assert_called_once()
    saved = repository.save_email.call_args[0][0]
    assert saved.subject == "Test Subject"
    assert saved.body_text == "Plain text body"
    assert saved.body_html == "<p>HTML body</p>"
    assert saved.raw_s3_key == "some-key"
    assert saved.address == "bank-abc@mail.david74.dev"
    assert saved.parsed_data is None


def test_processes_plain_text_only_email():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()

    storage.get_email_raw.return_value = _make_plain_email()

    service = ProcessEmail(storage, repository)
    service.execute(
        s3_key="key-2",
        address="bank-abc@mail.david74.dev",
        sender="sender@example.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    saved = repository.save_email.call_args[0][0]
    assert saved.body_text == "Just plain text\r\n"
    assert saved.body_html is None
    assert saved.subject == "Plain Email"


def test_email_has_correct_metadata():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()

    storage.get_email_raw.return_value = _make_plain_email()

    service = ProcessEmail(storage, repository)
    service.execute(
        s3_key="key-3",
        address="card-xyz@mail.david74.dev",
        sender="bank@example.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    saved = repository.save_email.call_args[0][0]
    assert saved.sender == "bank@example.com"
    assert saved.address == "card-xyz@mail.david74.dev"
    assert saved.id is None
    assert saved.created_at is not None


def test_decodes_mime_encoded_subject():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()

    encoded_subject = "=?UTF-8?B?5ris6Kmm5Li76aGM?="
    storage.get_email_raw.return_value = _make_plain_email(subject=encoded_subject)

    service = ProcessEmail(storage, repository)
    service.execute(
        s3_key="key-4",
        address="bank-abc@mail.david74.dev",
        sender="sender@example.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    saved = repository.save_email.call_args[0][0]
    assert saved.subject == "\u6e2c\u8a66\u4e3b\u984c"
