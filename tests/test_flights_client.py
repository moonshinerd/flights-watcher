import base64
from unittest.mock import MagicMock, patch
import pytest
from flights_watcher.clients.flights_client import (
    FlightSearchClient,
    _encode_airport,
    _encode_leg,
    _encode_string,
    _encode_submessage,
    _encode_tag,
    _encode_varint,
    build_canonical_google_flights_url,
)
from flights_watcher.domain.models import RouteConfig


def test_protobuf_encode_varint():
    # 0 -> [0]
    assert _encode_varint(0) == bytearray([0])
    # 1 -> [1]
    assert _encode_varint(1) == bytearray([1])
    # 127 -> [127]
    assert _encode_varint(127) == bytearray([127])
    # 128 -> [128 | 0x80, 1] = [128, 1]
    assert _encode_varint(128) == bytearray([0x80, 1])
    # 300 -> 300 = 0b00000010 0101100 -> [0xAC, 0x02]
    assert _encode_varint(300) == bytearray([0xAC, 0x02])

    with pytest.raises(ValueError, match="non-negative"):
        _encode_varint(-1)


def test_protobuf_encode_primitives():
    # Tag: field 1, wire 2 -> (1 << 3) | 2 = 10 -> [10]
    assert _encode_tag(1, 2) == bytearray([10])

    # String: field 2, "BSB"
    s_bytes = _encode_string(2, "BSB")
    assert b"BSB" in s_bytes

    # Submessage
    inner = bytearray([1, 2, 3])
    sub = _encode_submessage(3, inner)
    assert len(sub) > len(inner)
    assert sub[-3:] == inner

    # Airport
    apt = _encode_airport("CGH")
    assert b"CGH" in apt

    # Leg
    leg = _encode_leg("2027-09-03", "BSB", "CGH")
    assert b"2027-09-03" in leg
    assert b"BSB" in leg
    assert b"CGH" in leg


def test_build_canonical_google_flights_url_one_way():
    url = build_canonical_google_flights_url(
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date=None,
        currency="BRL",
    )
    assert "https://www.google.com/travel/flights/search?tfs=" in url
    assert "hl=pt-BR" in url
    assert "gl=BR" in url
    assert "curr=BRL" in url

    # Validate that base64 decodes cleanly
    tfs_param = url.split("tfs=")[1].split("&")[0]
    decoded = base64.b64decode(tfs_param)
    assert b"BSB" in decoded
    assert b"CGH" in decoded
    assert b"2027-09-03" in decoded


def test_build_canonical_google_flights_url_round_trip():
    url = build_canonical_google_flights_url(
        origin="BSB",
        destination="GRU",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        currency="USD",
    )
    assert "curr=USD" in url
    tfs_param = url.split("tfs=")[1].split("&")[0]
    decoded = base64.b64decode(tfs_param)
    assert b"BSB" in decoded
    assert b"GRU" in decoded
    assert b"2027-09-03" in decoded
    assert b"2027-09-06" in decoded


def test_to_domain_conversion():
    client = FlightSearchClient()
    route = RouteConfig(
        id="test-route",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        target_price=550.0,
    )

    data = {
        "price": 480.0,
        "currency": "BRL",
        "duration": 105,
        "stops": 0,
        "outbound": {
            "legs": [
                {
                    "airline": {"name": "LATAM Airlines"},
                    "departure_time": "08:30",
                    "arrival_time": "10:15",
                }
            ]
        },
        "return": {
            "legs": [
                {
                    "airline": {"name": "LATAM Airlines"},
                    "departure_time": "18:00",
                    "arrival_time": "19:45",
                }
            ]
        },
    }

    deal = client._to_domain(route, data)
    assert deal.price == 480.0
    assert deal.airline == "LATAM Airlines"
    assert deal.outbound_departure == "08:30"
    assert deal.outbound_arrival == "10:15"
    assert deal.return_departure == "18:00"
    assert deal.return_arrival == "19:45"
    assert deal.is_round_trip is True
    assert "https://www.google.com/travel/flights/search?tfs=" in deal.google_flights_url


def test_to_domain_fallback_empty_legs():
    client = FlightSearchClient()
    route = RouteConfig(
        id="test-fallback",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        target_price=550.0,
    )

    data = {
        "price": 300.0,
        "legs": [],  # Empty legs
    }

    deal = client._to_domain(route, data)
    assert deal.airline == "Desconhecida"
    assert deal.outbound_departure == ""
    assert deal.return_departure is None
    assert deal.is_round_trip is False


@patch("flights_watcher.clients.flights_client.SearchFlights")
def test_search_route_success(mock_search_flights_cls):
    mock_instance = MagicMock()
    mock_search_flights_cls.return_value = mock_instance

    client = FlightSearchClient()
    client._client = mock_instance

    route = RouteConfig(
        id="bsb-cgh",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        target_price=550.0,
        airlines=["LA"],
        exclude_airlines=["AD"],
        max_stops="0",
        cabin_class="ECONOMY",
    )

    # Mock raw fli results
    mock_item = MagicMock()
    mock_instance.search.return_value = [mock_item]

    with patch("flights_watcher.clients.flights_client.serialize_flight_result") as mock_serialize:
        mock_serialize.return_value = {
            "price": 500.0,
            "currency": "BRL",
            "duration": 100,
            "stops": 0,
            "outbound": {"legs": [{"airline": {"name": "LATAM"}, "departure_time": "08:00", "arrival_time": "09:40"}]},
        }
        deals = client.search_route(route)

    assert len(deals) == 1
    assert deals[0].price == 500.0
    mock_instance.search.assert_called_once()


@patch("flights_watcher.clients.flights_client.SearchFlights")
def test_search_route_no_results(mock_search_flights_cls):
    mock_instance = MagicMock()
    mock_instance.search.return_value = None

    client = FlightSearchClient()
    client._client = mock_instance

    route = RouteConfig(
        id="empty-route",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        target_price=550.0,
    )

    deals = client.search_route(route)
    assert deals == []


@patch("flights_watcher.clients.flights_client.SearchFlights")
def test_search_route_handles_exception(mock_search_flights_cls):
    mock_instance = MagicMock()
    mock_instance.search.side_effect = RuntimeError("Network error")

    client = FlightSearchClient()
    client._client = mock_instance

    route = RouteConfig(
        id="error-route",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        target_price=550.0,
    )

    deals = client.search_route(route)
    assert deals == []
