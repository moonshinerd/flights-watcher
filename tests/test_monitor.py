from unittest.mock import MagicMock
import pytest
from flights_watcher.clients.notifier import NotifierPort
from flights_watcher.domain.models import FlightDeal, RouteConfig
from flights_watcher.services.monitor import MonitorService
from flights_watcher.storage.repository import FlightRepository


class MockNotifier(NotifierPort):
    def __init__(self):
        self.sent_alerts = []
        self.sent_errors = []

    def send_deal_alert(self, route: RouteConfig, deal: FlightDeal) -> bool:
        self.sent_alerts.append((route, deal))
        return True

    def send_error_alert(self, error_message: str, context: str | None = None) -> bool:
        self.sent_errors.append((error_message, context))
        return True


@pytest.fixture
def mock_search_client():
    client = MagicMock()
    return client


def test_monitor_service_check_route_triggers_notification(tmp_path, mock_search_client):
    db_file = tmp_path / "test_flights.db"
    repo = FlightRepository(db_file)
    notifier = MockNotifier()

    route = RouteConfig(
        id="test-route",
        origin="GRU",
        destination="GIG",
        departure_date="2026-11-10",
        return_date="2026-11-17",
        target_price=900.0,
    )

    found_deal = FlightDeal(
        route_id=route.id,
        origin="GRU",
        destination="GIG",
        departure_date="2026-11-10",
        return_date="2026-11-17",
        price=820.0,
        currency="BRL",
        airline="Azul",
        stops=0,
        outbound_departure="2026-11-10T10:00:00",
        outbound_arrival="2026-11-10T11:00:00",
        return_departure="2026-11-17T15:00:00",
        return_arrival="2026-11-17T16:00:00",
        total_duration_minutes=120,
    )

    mock_search_client.search_route.return_value = [found_deal]

    service = MonitorService(
        search_client=mock_search_client,
        repository=repo,
        notifier=notifier,
    )

    result = service.check_route(route)

    assert result == found_deal
    assert len(notifier.sent_alerts) == 1
    assert notifier.sent_alerts[0][1].price == 820.0
    assert repo.get_lowest_historical_price(route.id) == 820.0


def test_monitor_service_ignores_deal_above_target(tmp_path, mock_search_client):
    db_file = tmp_path / "test_flights.db"
    repo = FlightRepository(db_file)
    notifier = MockNotifier()

    route = RouteConfig(
        id="test-route",
        origin="GRU",
        destination="GIG",
        departure_date="2026-11-10",
        target_price=500.0,
    )

    expensive_deal = FlightDeal(
        route_id=route.id,
        origin="GRU",
        destination="GIG",
        departure_date="2026-11-10",
        price=750.0,
        currency="BRL",
        airline="LATAM",
        stops=0,
        outbound_departure="2026-11-10T10:00:00",
        outbound_arrival="2026-11-10T11:00:00",
        total_duration_minutes=60,
    )

    mock_search_client.search_route.return_value = [expensive_deal]

    service = MonitorService(
        search_client=mock_search_client,
        repository=repo,
        notifier=notifier,
    )

    result = service.check_route(route)

    assert result == expensive_deal
    # Preço 750 > Meta 500 -> Nenhum alerta enviado
    assert len(notifier.sent_alerts) == 0
    # Mas preço registrado no histórico
    assert repo.get_lowest_historical_price(route.id) == 750.0


def test_monitor_service_handles_error_and_triggers_alert(tmp_path, mock_search_client):
    db_file = tmp_path / "test_flights.db"
    repo = FlightRepository(db_file)
    notifier = MockNotifier()

    service = MonitorService(
        search_client=mock_search_client,
        repository=repo,
        notifier=notifier,
    )

    err = ConnectionError("Falha ao comunicar com o servidor")
    service._handle_error(err, context="Teste de Conectividade")

    assert len(notifier.sent_errors) == 1
    assert "ConnectionError" in notifier.sent_errors[0][0]
    assert "Teste de Conectividade" in notifier.sent_errors[0][1]
