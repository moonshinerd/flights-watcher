from unittest.mock import MagicMock, patch
from flights_watcher.clients.notifier import EmailNotifier
from flights_watcher.domain.models import FlightDeal, RouteConfig


def test_email_notifier_not_configured():
    notifier = EmailNotifier(smtp_user=None, smtp_password=None, email_to=None)
    assert not notifier.is_configured
    route = RouteConfig(
        id="test",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        target_price=550.0,
    )
    deal = FlightDeal(
        route_id="test",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        price=450.0,
        airline="GOL",
        stops=0,
        outbound_departure="10:00",
        outbound_arrival="11:45",
        total_duration_minutes=105,
    )
    assert not notifier.send_deal_alert(route, deal)


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_success(mock_smtp_ssl):
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

    route = RouteConfig(
        id="bsb-cgh",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        target_price=550.0,
    )
    deal = FlightDeal(
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
        google_flights_url="https://www.google.com/travel/flights",
    )

    success = notifier.send_deal_alert(route, deal)
    assert success
    mock_server.login.assert_called_once_with("test@example.com", "password123")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_email_notifier_send_error_alert(mock_smtp_ssl):
    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__.return_value = mock_server

    notifier = EmailNotifier(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="test@example.com",
        smtp_password="password123",
        email_to="recipient@example.com",
    )

    success = notifier.send_error_alert("Timeout connecting to server", context="Test Error Context")
    assert success
    mock_server.login.assert_called_once_with("test@example.com", "password123")
    mock_server.send_message.assert_called_once()
