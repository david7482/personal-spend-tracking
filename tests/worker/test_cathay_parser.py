from decimal import Decimal
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))

CATHAY_HTML_FIXTURE = """
<html>
<body>
<table>
  <tr><td>消費彙整通知</td></tr>
  <tr><td>通知日期：2026/02/20</td></tr>
  <tr><td>親愛的客戶，您好</td></tr>
  <tr><td>感謝您使用國泰世華銀行信用卡/簽帳金融卡消費，您最新的消費授權紀錄如下：</td></tr>
  <tr><td>卡號後4碼： 6903</td></tr>
</table>
<table>
  <tbody>
    <tr>
      <td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td>
    </tr>
    <tr>
      <td>正卡</td><td>4623</td><td>2026/02/19</td><td>15:40</td><td>TW</td>
    </tr>
    <tr>
      <td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td>
    </tr>
    <tr>
      <td colspan="2">NT$330</td><td>國立臺灣科學教育館</td><td>線上繳費</td><td>&nbsp;</td>
    </tr>
  </tbody>
</table>
<table>
  <tbody>
    <tr>
      <td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td>
    </tr>
    <tr>
      <td>正卡</td><td>6012</td><td>2026/02/19</td><td>00:27</td><td>NL</td>
    </tr>
    <tr>
      <td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td>
    </tr>
    <tr>
      <td colspan="2">NT$1,040</td><td>PRAGMATICENGINEER.COM</td><td>其他</td><td>&nbsp;</td>
    </tr>
  </tbody>
</table>
</body>
</html>
"""


def test_can_parse_matches_cathay_address():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    assert parser.can_parse("cathay-cc@mail.david74.dev", "國泰世華銀行消費彙整通知") is True


def test_can_parse_rejects_other_address():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    assert parser.can_parse("ctbc-cc@mail.david74.dev", "something") is False


def test_parses_two_transactions():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    result = parser.parse(CATHAY_HTML_FIXTURE, {"received_at": "2026-02-20T06:23:16+00:00"})

    assert len(result.transactions) == 2

    txn1 = result.transactions[0]
    assert txn1.amount == Decimal("330")
    assert txn1.merchant == "國立臺灣科學教育館"
    assert txn1.category == "線上繳費"
    assert txn1.region == "TW"
    assert txn1.transaction_at == datetime(2026, 2, 19, 15, 40, tzinfo=TAIPEI_TZ)
    assert txn1.bank == "cathay"
    assert txn1.raw_data["card_type"] == "正卡"
    assert txn1.raw_data["mobile_card_last_four"] == "4623"

    txn2 = result.transactions[1]
    assert txn2.amount == Decimal("1040")
    assert txn2.merchant == "PRAGMATICENGINEER.COM"
    assert txn2.region == "NL"


def test_parsed_data_has_email_metadata():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    result = parser.parse(CATHAY_HTML_FIXTURE, {"received_at": "2026-02-20T06:23:16+00:00"})

    assert result.parsed_data["bank"] == "cathay"
    assert result.parsed_data["email_type"] == "daily_transaction_summary"
    assert result.parsed_data["notification_date"] == "2026/02/20"
    assert result.parsed_data["card_last_four"] == "6903"
    assert result.parsed_data["transaction_count"] == 2


def test_malformed_html_returns_empty_result():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    result = parser.parse("<html><body>no tables</body></html>", {"received_at": "2026-02-20T06:23:16+00:00"})

    assert len(result.transactions) == 0
    assert result.parsed_data["bank"] == "cathay"
    assert result.parsed_data["transaction_count"] == 0
