from datetime import datetime, timedelta
import pytest
from flights_watcher.domain.models import FlightDeal, RouteConfig
from flights_watcher.storage.repository import FlightRepository


@pytest.fixture
def temp_repo(tmp_path):
    db_file = tmp_path / "test_flights.db"
    return FlightRepository(db_file)


@pytest.fixture
def sample_deal():
    return FlightDeal(
        route_id="gru-gig-test",
        origin="GRU",
        destination="GIG",
        departure_date="2026-11-10",
        return_date="2026-11-17",
        price=750.0,
        currency="BRL",
        airline="Gol",
        stops=0,
        outbound_departure="2026-11-10T10:00:00",
        outbound_arrival="2026-11-10T11:00:00",
        return_departure="2026-11-17T15:00:00",
        return_arrival="2026-11-17T16:00:00",
        total_duration_minutes=120,
        google_flights_url="https://google.com",
    )


def test_route_config_creation():
    route = RouteConfig(
        id="test-1",
        origin="GRU",
        destination="MIA",
        departure_date="2026-11-10",
        return_date="2026-11-20",
        target_price=3000.0,
    )
    assert route.origin == "GRU"
    assert route.destination == "MIA"
    assert route.target_price == 3000.0
    assert route.active is True


def test_flight_deal_round_trip(sample_deal):
    assert sample_deal.is_round_trip is True
    sample_deal.return_date = None
    assert sample_deal.is_round_trip is False


def test_repository_save_and_history(temp_repo, sample_deal):
    temp_repo.save_deal(sample_deal)
    lowest = temp_repo.get_lowest_historical_price(sample_deal.route_id)
    assert lowest == 750.0


def test_should_notify_logic(temp_repo, sample_deal):
    # 1. Preço acima da meta -> Não notifica
    assert temp_repo.should_notify(sample_deal, target_price=700.0) is False

    # 2. Preço abaixo da meta e nunca notificado -> Notifica!
    assert temp_repo.should_notify(sample_deal, target_price=800.0) is True

    # Registra que foi notificado a 750.0
    temp_repo.record_notification(sample_deal)

    # 3. Imediatamente depois com o mesmo preço -> Suprime (cooldown ativo)
    assert temp_repo.should_notify(sample_deal, target_price=800.0) is False

    # 4. Preço caiu ainda mais (ex: 699.0) -> Notifica imediatamente!
    cheaper_deal = sample_deal.model_copy(update={"price": 699.0})
    assert temp_repo.should_notify(cheaper_deal, target_price=800.0) is True
