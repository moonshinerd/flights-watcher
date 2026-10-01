import pytest
from pydantic import ValidationError
from flights_watcher.domain.models import FlightDeal, RouteConfig


def test_route_config_valid_one_way():
    route = RouteConfig(
        id="bsb-cgh",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        target_price=550.0,
    )
    assert route.id == "bsb-cgh"
    assert route.origin == "BSB"
    assert route.destination == "CGH"
    assert route.departure_date == "2027-09-03"
    assert route.return_date is None
    assert route.target_price == 550.0
    assert route.currency == "BRL"
    assert route.max_stops == "ANY"
    assert route.cabin_class == "ECONOMY"
    assert route.active is True


def test_route_config_valid_round_trip_with_filters():
    route = RouteConfig(
        id="bsb-gru-round",
        origin="BSB",
        destination="GRU",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        target_price=600.0,
        currency="USD",
        max_stops="0",
        cabin_class="BUSINESS",
        airlines=["G3", "LA"],
        exclude_airlines=["AD"],
        active=False,
    )
    assert route.return_date == "2027-09-06"
    assert route.currency == "USD"
    assert route.max_stops == "0"
    assert route.cabin_class == "BUSINESS"
    assert route.airlines == ["G3", "LA"]
    assert route.exclude_airlines == ["AD"]
    assert route.active is False


def test_route_config_validation_error():
    with pytest.raises(ValidationError):
        # Missing required fields
        RouteConfig(id="invalid")


def test_flight_deal_properties_one_way():
    deal = FlightDeal(
        route_id="r1",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        price=350.0,
        currency="BRL",
        airline="GOL",
        stops=0,
        outbound_departure="08:00",
        outbound_arrival="09:45",
        total_duration_minutes=105,
    )
    assert deal.is_round_trip is False
    assert deal.return_date is None
    assert deal.google_flights_url is None


def test_flight_deal_properties_round_trip():
    deal = FlightDeal(
        route_id="r1",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        price=550.0,
        currency="BRL",
        airline="LATAM",
        stops=1,
        outbound_departure="08:00",
        outbound_arrival="11:30",
        return_departure="19:00",
        return_arrival="20:45",
        total_duration_minutes=210,
        google_flights_url="https://google.com/flights",
    )
    assert deal.is_round_trip is True
    assert deal.return_date == "2027-09-06"
    assert deal.price == 550.0
