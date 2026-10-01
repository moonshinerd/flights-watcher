import smtplib
from unittest.mock import MagicMock, patch
import httpx
import pytest
from flights_watcher.clients.notifier import (
    CompositeNotifier,
    ConsoleNotifier,
    EmailNotifier,
    TelegramNotifier,
)
from flights_watcher.domain.models import FlightDeal, RouteConfig


@pytest.fixture
def sample_route():
    return RouteConfig(
        id="bsb-cgh",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        target_price=550.0,
    )


@pytest.fixture
def sample_deal():
    return FlightDeal(
        route_id="bsb-cgh",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        price=480.0,
        currency="BRL",
        airline="LATAM",
        stops=0,
        outbound_departure="08:00",
        outbound_arrival="09:45",
        return_departure="17:00",
        return_arrival="18:45",
        total_duration_minutes=105,
        google_flights_url="https://www.google.com/travel/flights/search?tfs=test",
    )


# ---------------------------------------------------------
# ConsoleNotifier Tests
# ---------------------------------------------------------
def test_console_notifier_send_deal_alert(sample_route, sample_deal):
    notifier = ConsoleNotifier()
    assert notifier.send_deal_alert(sample_route, sample_deal) is True

    # One way
    one_way_deal = sample_deal.model_copy(update={"return_date": None})
    assert notifier.send_deal_alert(sample_route, one_way_deal) is True


def test_console_notifier_send_error_alert():
    notifier = ConsoleNotifier()
    assert notifier.send_error_alert("Test Error", context="Unit Test") is True
    assert notifier.send_error_alert("Test Error Without Context") is True


# ---------------------------------------------------------
# EmailNotifier Tests
# ---------------------------------------------------------
def test_email_notifier_not_configured(sample_route, sample_deal):
    notifier = EmailNotifier(smtp_user=None, smtp_password=None, email_to=None)
    assert not notifier.is_configured
    assert notifier.send_deal_alert(sample_route, sample_deal) is False
    assert notifier.send_error_alert("Some error") is False


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_deal_alert_ssl_465(mock_smtp_ssl, sample_route, sample_deal):
    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__.return_value = mock_server

    notifier = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@example.com",
        smtp_password="password123",
        email_to="recipient@example.com",
    )
    assert notifier.is_configured

    success = notifier.send_deal_alert(sample_route, sample_deal)
    assert success is True
    mock_server.login.assert_called_once_with("test@example.com", "password123")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP")
def test_email_notifier_send_deal_alert_tls_587(mock_smtp, sample_route, sample_deal):
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    notifier = EmailNotifier(
        smtp_host="smtp.other.com",
        smtp_port=587,
        smtp_user="test@example.com",
        smtp_password="password123",
        email_to="recipient@example.com",
    )

    success = notifier.send_deal_alert(sample_route, sample_deal)
    assert success is True
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("test@example.com", "password123")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_deal_alert_exception(mock_smtp_ssl, sample_route, sample_deal):
    mock_smtp_ssl.side_effect = smtplib.SMTPException("Auth failed")

    notifier = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@example.com",
        smtp_password="password123",
        email_to="recipient@example.com",
    )

    success = notifier.send_deal_alert(sample_route, sample_deal)
    assert success is False


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_error_alert_success(mock_smtp_ssl):
    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__.return_value = mock_server

    notifier = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@example.com",
        smtp_password="password123",
        email_to="recipient@example.com",
    )

    success = notifier.send_error_alert("Database locked", context="SQLite Repository")
    assert success is True
    mock_server.login.assert_called_once_with("test@example.com", "password123")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_error_alert_exception(mock_smtp_ssl):
    mock_smtp_ssl.side_effect = ConnectionRefusedError("Connection refused")

    notifier = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@example.com",
        smtp_password="password123",
        email_to="recipient@example.com",
    )

    success = notifier.send_error_alert("Timeout error")
    assert success is False


# ---------------------------------------------------------
# TelegramNotifier Tests
# ---------------------------------------------------------
def test_telegram_notifier_not_configured(sample_route, sample_deal):
    notifier = TelegramNotifier(bot_token=None, chat_id=None)
    assert not notifier.is_configured
    assert notifier.send_deal_alert(sample_route, sample_deal) is False
    assert notifier.send_error_alert("Telegram error") is False


@patch("httpx.Client")
def test_telegram_notifier_send_deal_alert_success(mock_client_cls, sample_route, sample_deal):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_res = MagicMock()
    mock_res.raise_for_status.return_value = None
    mock_client.post.return_value = mock_res

    notifier = TelegramNotifier(bot_token="1234:TOKEN", chat_id="999888")
    assert notifier.is_configured

    success = notifier.send_deal_alert(sample_route, sample_deal)
    assert success is True
    mock_client.post.assert_called_once()
    assert "https://api.telegram.org/bot1234:TOKEN/sendMessage" in mock_client.post.call_args[0][0]


@patch("httpx.Client")
def test_telegram_notifier_send_deal_alert_failure(mock_client_cls, sample_route, sample_deal):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.post.side_effect = httpx.HTTPStatusError("400 Bad Request", request=MagicMock(), response=MagicMock())

    notifier = TelegramNotifier(bot_token="1234:TOKEN", chat_id="999888")
    success = notifier.send_deal_alert(sample_route, sample_deal)
    assert success is False


@patch("httpx.Client")
def test_telegram_notifier_send_error_alert_success(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_res = MagicMock()
    mock_res.raise_for_status.return_value = None
    mock_client.post.return_value = mock_res

    notifier = TelegramNotifier(bot_token="1234:TOKEN", chat_id="999888")
    success = notifier.send_error_alert("Fatal process crash", context="Worker #1")
    assert success is True


@patch("httpx.Client")
def test_telegram_notifier_send_error_alert_failure(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.post.side_effect = RuntimeError("Network unreachable")

    notifier = TelegramNotifier(bot_token="1234:TOKEN", chat_id="999888")
    success = notifier.send_error_alert("Crash")
    assert success is False


# ---------------------------------------------------------
# CompositeNotifier Tests
# ---------------------------------------------------------
def test_composite_notifier(sample_route, sample_deal):
    n1 = MagicMock()
    n1.send_deal_alert.return_value = True
    n1.send_error_alert.return_value = True

    n2 = MagicMock()
    n2.send_deal_alert.side_effect = RuntimeError("n2 failed")
    n2.send_error_alert.side_effect = RuntimeError("n2 error failed")

    composite = CompositeNotifier([n1, n2])

    assert composite.send_deal_alert(sample_route, sample_deal) is True
    assert composite.send_error_alert("Global crash", context="Main") is True

    n1.send_deal_alert.assert_called_once_with(sample_route, sample_deal)
    n1.send_error_alert.assert_called_once_with("Global crash", "Main")
