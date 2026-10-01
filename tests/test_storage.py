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


def test_repository_get_lowest_non_existent(temp_repo):
    assert temp_repo.get_lowest_historical_price("non-existent-route") is None


def test_repository_save_and_history_multiple(temp_repo, sample_deal):
    # Save first deal
    temp_repo.save_deal(sample_deal)
    assert temp_repo.get_lowest_historical_price(sample_deal.route_id) == 750.0

    # Save higher deal -> lowest remains 750.0
    higher_deal = sample_deal.model_copy(update={"price": 890.0})
    temp_repo.save_deal(higher_deal)
    assert temp_repo.get_lowest_historical_price(sample_deal.route_id) == 750.0

    # Save cheaper deal -> lowest becomes 620.0
    cheaper_deal = sample_deal.model_copy(update={"price": 620.0})
    temp_repo.save_deal(cheaper_deal)
    assert temp_repo.get_lowest_historical_price(sample_deal.route_id) == 620.0

    # Different route does not mix
    other_route_deal = sample_deal.model_copy(update={"route_id": "other-route", "price": 400.0})
    temp_repo.save_deal(other_route_deal)
    assert temp_repo.get_lowest_historical_price("other-route") == 400.0
    assert temp_repo.get_lowest_historical_price(sample_deal.route_id) == 620.0


def test_should_notify_logic(temp_repo, sample_deal):
    # 1. Preço acima da meta -> Não notifica
    assert temp_repo.should_notify(sample_deal, target_price=700.0) is False

    # 2. Preço abaixo da meta e nunca notificado -> Notifica!
    assert temp_repo.should_notify(sample_deal, target_price=800.0) is True

    # Registra que foi notificado a 750.0
    temp_repo.record_notification(sample_deal)

    # 3. Imediatamente depois com o mesmo preço -> Suprime (cooldown ativo)
    assert temp_repo.should_notify(sample_deal, target_price=800.0) is False

    # 4. Preço caiu ainda mais (ex: 699.0) -> Notifica imediatamente mesmo dentro do cooldown!
    cheaper_deal = sample_deal.model_copy(update={"price": 699.0})
    assert temp_repo.should_notify(cheaper_deal, target_price=800.0) is True


def test_should_notify_after_cooldown_expired(temp_repo, sample_deal):
    temp_repo.save_deal(sample_deal)
    # Simula gravação de notificação antiga (15 horas atrás)
    old_time = (datetime.now() - timedelta(hours=15)).strftime("%Y-%m-%d %H:%M:%S")
    with temp_repo._get_connection() as conn:
        conn.cursor().execute(
            """
            INSERT INTO notifications (route_id, price, currency, notified_at)
            VALUES (?, ?, ?, ?)
            """,
            (sample_deal.route_id, sample_deal.price, sample_deal.currency, old_time),
        )

    # Com cooldown de 12h, após 15h deve notificar novamente mesmo com o mesmo preço
    assert temp_repo.should_notify(sample_deal, target_price=800.0, cooldown_hours=12) is True


def test_metadata_operations(temp_repo):
    assert temp_repo.get_metadata("test_key") is None
    temp_repo.set_metadata("test_key", "value_1")
    assert temp_repo.get_metadata("test_key") == "value_1"
    temp_repo.set_metadata("test_key", "value_2")
    assert temp_repo.get_metadata("test_key") == "value_2"


def test_get_stats(temp_repo, sample_deal):
    stats_empty = temp_repo.get_stats()
    assert stats_empty["total_prices"] == 0
    assert stats_empty["total_notifications"] == 0
    assert stats_empty["lowest_prices"] == []

    temp_repo.save_deal(sample_deal)
    temp_repo.record_notification(sample_deal)

    stats = temp_repo.get_stats()
    assert stats["total_prices"] == 1
    assert stats["total_notifications"] == 1
    assert len(stats["lowest_prices"]) == 1
    assert stats["lowest_prices"][0]["min_price"] == sample_deal.price
