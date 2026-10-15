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


def test_console_notifier_heartbeat_and_shutdown():
    c = ConsoleNotifier()
    assert c.send_heartbeat_alert({"uptime": "1d", "total_prices": 5}) is True
    assert c.send_shutdown_alert("SIGTERM", "1d") is True


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_heartbeat_alert_success(mock_smtp_ssl_cls):
    mock_server = MagicMock()
    mock_smtp_ssl_cls.return_value.__enter__.return_value = mock_server

    email_notif = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@gmail.com",
        smtp_password="app-password",
        email_to="dest@gmail.com",
    )

    stats = {
        "uptime": "7 dia(s)",
        "total_prices": 100,
        "total_notifications": 2,
        "lowest_prices": [
            {
                "origin": "BSB",
                "destination": "CGH",
                "departure_date": "2027-09-03",
                "return_date": "2027-09-06",
                "currency": "BRL",
                "min_price": 480.0,
                "airline": "LATAM",
            }
        ],
    }

    success = email_notif.send_heartbeat_alert(stats)
    assert success is True
    mock_server.send_message.assert_called_once()
    sent_msg = mock_server.send_message.call_args[0][0]
    assert "Relatório Semanal de Saúde" in sent_msg["Subject"]


def test_email_notifier_send_heartbeat_not_configured():
    email_notif = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user=None,
        smtp_password=None,
        email_to=None,
    )
    assert email_notif.send_heartbeat_alert({}) is False


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_shutdown_alert_success(mock_smtp_ssl_cls):
    mock_server = MagicMock()
    mock_smtp_ssl_cls.return_value.__enter__.return_value = mock_server

    email_notif = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@gmail.com",
        smtp_password="app-password",
        email_to="dest@gmail.com",
    )

    success = email_notif.send_shutdown_alert("SIGTERM", "7 dia(s)")
    assert success is True
    mock_server.send_message.assert_called_once()
    sent_msg = mock_server.send_message.call_args[0][0]
    assert "Processo Encerrando" in sent_msg["Subject"]


def test_email_notifier_send_shutdown_not_configured():
    email_notif = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user=None,
        smtp_password=None,
        email_to=None,
    )
    assert email_notif.send_shutdown_alert("SIGTERM", "1h") is False


@patch("httpx.Client")
def test_telegram_notifier_send_heartbeat_and_shutdown(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_res = MagicMock()
    mock_res.raise_for_status.return_value = None
    mock_client.post.return_value = mock_res

    notifier = TelegramNotifier(bot_token="1234:TOKEN", chat_id="999888")
    assert (
        notifier.send_heartbeat_alert(
            {
                "uptime": "7d",
                "total_prices": 10,
                "lowest_prices": [
                    {
                        "origin": "BSB",
                        "destination": "CGH",
                        "departure_date": "2027-09-03",
                        "min_price": 500.0,
                        "currency": "BRL",
                    }
                ],
            }
        )
        is True
    )
    assert notifier.send_shutdown_alert("SIGINT", "7d") is True


def test_telegram_notifier_heartbeat_and_shutdown_unconfigured():
    notifier = TelegramNotifier(bot_token=None, chat_id=None)
    assert notifier.send_heartbeat_alert({}) is False
    assert notifier.send_shutdown_alert("test", "0s") is False


def test_composite_notifier_heartbeat_and_shutdown():
    n1 = MagicMock()
    n1.send_heartbeat_alert.return_value = True
    n1.send_shutdown_alert.return_value = True

    n2 = MagicMock()
    n2.send_heartbeat_alert.side_effect = RuntimeError("n2 err")
    n2.send_shutdown_alert.side_effect = RuntimeError("n2 err")

    composite = CompositeNotifier([n1, n2])
    assert composite.send_heartbeat_alert({}) is True
    assert composite.send_shutdown_alert("SIGTERM", "1d") is True


@pytest.fixture
def sample_combo():
    return {
        "id": "combo:bsb-gru-ida+gru-bsb-volta",
        "departure_date": "2027-09-02",
        "return_date": "2027-09-05",
        "outbound_id": "bsb-gru-ida-02set27",
        "inbound_id": "gru-bsb-volta-05set27",
        "outbound_origin": "BSB",
        "outbound_destination": "GRU",
        "outbound_price": 280.0,
        "outbound_airline": "LATAM Airlines",
        "outbound_url": "https://www.google.com/travel/flights?q=ida",
        "inbound_origin": "GRU",
        "inbound_destination": "BSB",
        "inbound_price": 290.0,
        "inbound_airline": "Gol Transportes Aéreos",
        "inbound_url": "https://www.google.com/travel/flights?q=volta",
        "total_price": 570.0,
        "target_price": 600.0,
        "currency": "BRL",
        "round_trip_min_price": 817.0,
        "savings": 247.0,
        "status": "Abaixo da Meta",
        "status_badge": "🟢",
    }


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_split_deal_alert(mock_smtp_ssl, sample_combo):
    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__.return_value = mock_server

    notifier = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@example.com",
        smtp_password="password123",
        email_to="dest@example.com",
    )

    success = notifier.send_split_deal_alert(sample_combo)
    assert success is True
    mock_server.send_message.assert_called_once()
    msg = mock_server.send_message.call_args[0][0]
    assert "Ida e Volta Avulsas por BRL 570.00" in msg["Subject"]


def test_email_notifier_send_split_deal_not_configured(sample_combo):
    notifier = EmailNotifier(smtp_user=None, smtp_password=None, email_to=None)
    assert notifier.send_split_deal_alert(sample_combo) is False


@patch("httpx.Client")
def test_telegram_notifier_send_split_deal_alert(mock_client_cls, sample_combo):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_res = MagicMock()
    mock_res.raise_for_status.return_value = None
    mock_client.post.return_value = mock_res

    notifier = TelegramNotifier(bot_token="1234:TOKEN", chat_id="999888")
    assert notifier.send_split_deal_alert(sample_combo) is True
    mock_client.post.assert_called_once()
    body = mock_client.post.call_args[1]["json"]["text"]
    assert "VIAGEM COMBINADA" in body
    assert "BRL 570.00" in body


def test_telegram_notifier_send_split_deal_not_configured(sample_combo):
    notifier = TelegramNotifier(bot_token=None, chat_id=None)
    assert notifier.send_split_deal_alert(sample_combo) is False


def test_composite_notifier_send_split_deal(sample_combo):
    n1 = MagicMock()
    n1.send_split_deal_alert.return_value = True
    n2 = MagicMock()
    n2.send_split_deal_alert.side_effect = RuntimeError("fail")

    composite = CompositeNotifier([n1, n2])
    assert composite.send_split_deal_alert(sample_combo) is True
    n1.send_split_deal_alert.assert_called_once_with(sample_combo)


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_heartbeat_with_split_and_links(mock_smtp_ssl, sample_combo):
    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__.return_value = mock_server

    email_notif = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@gmail.com",
        smtp_password="app-password",
        email_to="dest@gmail.com",
    )

    stats = {
        "uptime": "7 dia(s)",
        "total_prices": 100,
        "total_notifications": 2,
        "routes_matrix": [
            {
                "id": "bsb-cgh",
                "origin": "BSB",
                "destination": "CGH",
                "trip_type": "Ida e Volta",
                "departure_date": "2027-09-03",
                "return_date": "2027-09-06",
                "target_price": 600.0,
                "min_price": 855.0,
                "currency": "BRL",
                "airline": "LATAM",
                "status": "Acima da Meta (BRL 855.00)",
                "status_badge": "🟡",
                "checks_count": 10,
                "url": "https://google.com/flights/bsb-cgh",
            }
        ],
        "split_combinations": [sample_combo],
    }

    assert email_notif.send_heartbeat_alert(stats) is True
    sent_msg = mock_server.send_message.call_args[0][0]
    html_part = sent_msg.get_payload(1).get_payload(decode=True).decode("utf-8")
    assert "Melhores Combinações Ida + Volta Avulsas" in html_part
    assert "Ver no Google Flights ↗" in html_part
    assert "https://google.com/flights/bsb-cgh" in html_part
    assert "https://www.google.com/travel/flights?q=ida" in html_part
    assert "https://www.google.com/travel/flights?q=volta" in html_part

