from datetime import datetime, timedelta
import json
import time
from unittest.mock import MagicMock, patch
import pytest
from flights_watcher.clients.notifier import NotifierPort
from flights_watcher.domain.models import FlightDeal, RouteConfig
from flights_watcher.services.monitor import MonitorService
from flights_watcher.storage.repository import FlightRepository


class MockNotifier(NotifierPort):
    def __init__(self):
        self.sent_alerts = []
        self.sent_errors = []
        self.sent_heartbeats = []
        self.sent_shutdowns = []

    def send_deal_alert(self, route: RouteConfig, deal: FlightDeal) -> bool:
        self.sent_alerts.append((route, deal))
        return True

    def send_error_alert(self, error_message: str, context: str | None = None) -> bool:
        self.sent_errors.append((error_message, context))
        return True

    def send_heartbeat_alert(self, stats: dict) -> bool:
        self.sent_heartbeats.append(stats)
        return True

    def send_shutdown_alert(self, reason: str, uptime_str: str) -> bool:
        self.sent_shutdowns.append((reason, uptime_str))
        return True


@pytest.fixture
def mock_search_client():
    return MagicMock()


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
def sample_deal(sample_route):
    return FlightDeal(
        route_id=sample_route.id,
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
        return_departure="18:00",
        return_arrival="19:45",
        total_duration_minutes=105,
    )


def test_monitor_service_check_route_triggers_notification(tmp_path, mock_search_client, sample_route, sample_deal):
    db_file = tmp_path / "test_flights.db"
    repo = FlightRepository(db_file)
    notifier = MockNotifier()

    mock_search_client.search_route.return_value = [sample_deal]

    service = MonitorService(
        search_client=mock_search_client,
        repository=repo,
        notifier=notifier,
    )

    result = service.check_route(sample_route)
    assert result == sample_deal
    assert len(notifier.sent_alerts) == 1
    assert notifier.sent_alerts[0][1].price == 480.0
    assert repo.get_lowest_historical_price(sample_route.id) == 480.0


def test_monitor_service_ignores_deal_above_target(tmp_path, mock_search_client, sample_route, sample_deal):
    db_file = tmp_path / "test_flights.db"
    repo = FlightRepository(db_file)
    notifier = MockNotifier()

    expensive_deal = sample_deal.model_copy(update={"price": 600.0})
    mock_search_client.search_route.return_value = [expensive_deal]

    service = MonitorService(
        search_client=mock_search_client,
        repository=repo,
        notifier=notifier,
    )

    result = service.check_route(sample_route)
    assert result == expensive_deal
    assert len(notifier.sent_alerts) == 0
    assert repo.get_lowest_historical_price(sample_route.id) == 600.0


def test_monitor_service_check_route_no_deals(tmp_path, mock_search_client, sample_route):
    db_file = tmp_path / "test_flights.db"
    repo = FlightRepository(db_file)
    notifier = MockNotifier()

    mock_search_client.search_route.return_value = []

    service = MonitorService(
        search_client=mock_search_client,
        repository=repo,
        notifier=notifier,
    )

    result = service.check_route(sample_route)
    assert result is None
    assert len(notifier.sent_alerts) == 0


def test_load_routes_creates_example_when_not_exists(tmp_path, mock_search_client):
    routes_file = tmp_path / "routes.json"
    assert not routes_file.exists()

    service = MonitorService(
        search_client=mock_search_client,
        routes_file=routes_file,
    )

    routes = service.load_routes()
    assert routes_file.exists()
    assert len(routes) == 1
    assert routes[0].id == "gru-gig-novembro"


def test_load_routes_filters_inactive(tmp_path, mock_search_client):
    routes_file = tmp_path / "routes.json"
    routes_data = [
        {"id": "r1", "origin": "BSB", "destination": "CGH", "departure_date": "2027-09-03", "target_price": 500, "active": True},
        {"id": "r2", "origin": "BSB", "destination": "GRU", "departure_date": "2027-09-03", "target_price": 500, "active": False},
    ]
    with open(routes_file, "w", encoding="utf-8") as f:
        json.dump(routes_data, f)

    service = MonitorService(search_client=mock_search_client, routes_file=routes_file)
    routes = service.load_routes()
    assert len(routes) == 1
    assert routes[0].id == "r1"


def test_load_routes_handles_invalid_json(tmp_path, mock_search_client):
    routes_file = tmp_path / "routes.json"
    routes_file.write_text("{invalid json", encoding="utf-8")

    notifier = MockNotifier()
    service = MonitorService(search_client=mock_search_client, notifier=notifier, routes_file=routes_file)
    routes = service.load_routes()
    assert routes == []
    assert len(notifier.sent_errors) == 1


def test_run_once_with_exception_in_one_route(tmp_path, mock_search_client, sample_route, sample_deal):
    routes_file = tmp_path / "routes.json"
    routes_data = [
        {"id": "r-fail", "origin": "BSB", "destination": "CGH", "departure_date": "2027-09-03", "target_price": 500, "active": True},
        {"id": "r-ok", "origin": "BSB", "destination": "CGH", "departure_date": "2027-09-03", "target_price": 550, "active": True},
    ]
    with open(routes_file, "w", encoding="utf-8") as f:
        json.dump(routes_data, f)

    def search_side_effect(route):
        if route.id == "r-fail":
            raise RuntimeError("API Timeout")
        return [sample_deal]

    mock_search_client.search_route.side_effect = search_side_effect

    notifier = MockNotifier()
    service = MonitorService(
        search_client=mock_search_client,
        repository=FlightRepository(tmp_path / "test.db"),
        notifier=notifier,
        routes_file=routes_file,
    )

    with patch("time.sleep"):  # Skip 2s delay
        results = service.run_once()

    assert len(results) == 1
    assert results[0] == sample_deal
    assert service._consecutive_errors == 0


def test_handle_error_cooldown_throttling(tmp_path, mock_search_client):
    notifier = MockNotifier()
    service = MonitorService(search_client=mock_search_client, notifier=notifier)
    service._error_alert_cooldown_seconds = 100.0

    # 1. Primeiro erro -> Notifica!
    service._handle_error(RuntimeError("Erro 1"), context="Contexto 1")
    assert len(notifier.sent_errors) == 1
    assert service._consecutive_errors == 1

    # 2. Segundo erro logo em seguida -> Suprime notificação
    service._handle_error(RuntimeError("Erro 2"), context="Contexto 2")
    assert len(notifier.sent_errors) == 1
    assert service._consecutive_errors == 2

    # 3. Simula tempo passado além do cooldown -> Notifica novamente!
    service._last_error_alert_time -= 150.0
    service._handle_error(RuntimeError("Erro 3"), context="Contexto 3")
    assert len(notifier.sent_errors) == 2
    assert service._consecutive_errors == 3


def test_handle_error_notifier_exception_does_not_crash(tmp_path, mock_search_client):
    notifier = MagicMock()
    notifier.send_error_alert.side_effect = Exception("Notifier failure")

    service = MonitorService(search_client=mock_search_client, notifier=notifier)
    # Não deve levantar exceção
    service._handle_error(RuntimeError("Test"), context="Crash Test")
    assert service._consecutive_errors == 1


def test_run_forever_keyboard_interrupt(tmp_path, mock_search_client):
    notifier = MockNotifier()
    service = MonitorService(search_client=mock_search_client, notifier=notifier)
    service.run_once = MagicMock(side_effect=KeyboardInterrupt)

    # Executa sem travar ou explodir exceção
    service.run_forever()
    service.run_once.assert_called_once()
    assert len(notifier.sent_shutdowns) == 1


def test_run_forever_sleep_keyboard_interrupt(tmp_path, mock_search_client):
    notifier = MockNotifier()
    service = MonitorService(search_client=mock_search_client, notifier=notifier)
    service.run_once = MagicMock(return_value=[])

    with patch("time.sleep", side_effect=KeyboardInterrupt):
        service.run_forever()

    service.run_once.assert_called_once()
    assert len(notifier.sent_shutdowns) == 1


def test_run_forever_exception_handled(tmp_path, mock_search_client):
    notifier = MockNotifier()
    service = MonitorService(search_client=mock_search_client, notifier=notifier)
    # Primeiro loop levanta Exception, segundo loop levanta KeyboardInterrupt para parar
    service.run_once = MagicMock(side_effect=[RuntimeError("Erro de loop"), KeyboardInterrupt])

    with patch("time.sleep"):  # Evita atrasos
        service.run_forever()

    assert service.run_once.call_count == 2
    assert service._consecutive_errors == 1


def test_monitor_uptime_str(tmp_path, mock_search_client):
    service = MonitorService(search_client=mock_search_client)
    service._start_time = datetime.now() - timedelta(days=2, hours=3, minutes=15)
    uptime = service.uptime_str
    assert "2 dia(s)" in uptime
    assert "3 hora(s)" in uptime
    assert "15 minuto(s)" in uptime


def test_monitor_build_routes_matrix(tmp_path, mock_search_client, sample_deal):
    routes_file = tmp_path / "routes.json"
    routes_data = [
        {"id": "r-rt", "origin": "BSB", "destination": "CGH", "departure_date": "2027-09-03", "return_date": "2027-09-06", "target_price": 500, "active": True},
        {"id": "r-ow-out", "origin": "BSB", "destination": "GRU", "departure_date": "2027-09-03", "target_price": 275, "active": True},
        {"id": "r-ow-in", "origin": "GRU", "destination": "BSB", "departure_date": "2027-09-06", "target_price": 275, "active": True},
    ]
    with open(routes_file, "w", encoding="utf-8") as f:
        json.dump(routes_data, f)

    repo = FlightRepository(tmp_path / "test.db")
    service = MonitorService(search_client=mock_search_client, repository=repo, routes_file=routes_file)

    # 1. Sem dados salvos -> todos Aguardando Abertura
    matrix = service.build_routes_matrix()
    assert len(matrix) == 3
    assert matrix[0]["trip_type"] == "Ida e Volta"
    assert matrix[0]["status"] == "Aguardando Abertura"
    assert matrix[1]["trip_type"] == "Ida"
    assert matrix[2]["trip_type"] == "Volta"

    # 2. Salva preço abaixo da meta na rota 1
    deal_cheap = sample_deal.model_copy(update={"route_id": "r-rt", "price": 450.0})
    repo.save_deal(deal_cheap)

    # 3. Salva preço acima da meta na rota 2
    deal_expensive = sample_deal.model_copy(update={"route_id": "r-ow-out", "price": 350.0})
    repo.save_deal(deal_expensive)

    matrix = service.build_routes_matrix()
    assert matrix[0]["status"] == "Abaixo da Meta"
    assert matrix[0]["status_badge"] == "🟢"
    assert "Acima da Meta" in matrix[1]["status"]
    assert matrix[1]["status_badge"] == "🟡"


def test_monitor_send_heartbeat_if_due(tmp_path, mock_search_client):
    repo = FlightRepository(tmp_path / "test.db")
    notifier = MagicMock()
    notifier.send_heartbeat_alert.return_value = True

    service = MonitorService(search_client=mock_search_client, repository=repo, notifier=notifier)

    # 1. Primeira vez sem histórico prévio: envia!
    assert service.send_heartbeat_if_due() is True
    assert repo.get_metadata("last_heartbeat_at") is not None
    notifier.send_heartbeat_alert.assert_called_once()

    # 2. Chamada imediata subsequente: intervalo de 7 dias não expirou -> não envia
    notifier.send_heartbeat_alert.reset_mock()
    assert service.send_heartbeat_if_due() is False
    notifier.send_heartbeat_alert.assert_not_called()

    # 3. Forçado: envia mesmo antes do prazo
    assert service.send_heartbeat_if_due(force=True) is True
    notifier.send_heartbeat_alert.assert_called_once()


@patch("httpx.Client")
def test_monitor_ping_healthcheck_configured(mock_client_cls, tmp_path, mock_search_client):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_res = MagicMock()
    mock_res.raise_for_status.return_value = None
    mock_client.get.return_value = mock_res

    service = MonitorService(search_client=mock_search_client)
    with patch("flights_watcher.services.monitor.settings.HEALTHCHECK_PING_URL", "https://hc-ping.com/fake-uuid"):
        assert service.ping_healthcheck() is True

    # Teste de falha de conexão no ping
    mock_client.get.side_effect = RuntimeError("Network error")
    with patch("flights_watcher.services.monitor.settings.HEALTHCHECK_PING_URL", "https://hc-ping.com/fake-uuid"):
        assert service.ping_healthcheck() is False


def test_monitor_ping_healthcheck_not_configured(tmp_path, mock_search_client):
    service = MonitorService(search_client=mock_search_client)
    with patch("flights_watcher.services.monitor.settings.HEALTHCHECK_PING_URL", None):
        assert service.ping_healthcheck() is False


def test_monitor_send_shutdown_alert(tmp_path, mock_search_client):
    notifier = MagicMock()
    notifier.send_shutdown_alert.return_value = True

    service = MonitorService(search_client=mock_search_client, notifier=notifier)
    assert service.send_shutdown_alert("SIGTERM teste") is True
    notifier.send_shutdown_alert.assert_called_once()


def test_monitor_run_forever_fatal_crash_sends_shutdown(tmp_path, mock_search_client):
    notifier = MagicMock()
    service = MonitorService(search_client=mock_search_client, notifier=notifier)
    service.run_once = MagicMock(return_value=[])

    with patch("time.sleep", side_effect=RuntimeError("Fatal sleep error")):
        with pytest.raises(RuntimeError):
            service.run_forever()

    notifier.send_shutdown_alert.assert_called_once()
