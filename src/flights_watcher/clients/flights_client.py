import base64
import urllib.parse
from loguru import logger

from fli.cli.utils import serialize_flight_result
from fli.core import (
    build_flight_segments,
    parse_airlines,
    parse_cabin_class,
    parse_max_stops,
    parse_sort_by,
    resolve_airport,
)
from fli.models import FlightSearchFilters, PassengerInfo
from fli.search import SearchFlights
from flights_watcher.domain.models import FlightDeal, RouteConfig


def _encode_varint(value: int) -> bytearray:
    buf = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            buf.append(byte)
            break
        buf.append(byte | 0x80)
    return buf


def _encode_tag(field: int, wire_type: int) -> bytearray:
    return _encode_varint((field << 3) | wire_type)


def _encode_string(field: int, s: str) -> bytearray:
    buf = bytearray()
    s_bytes = s.encode("utf-8")
    buf.extend(_encode_tag(field, 2))
    buf.extend(_encode_varint(len(s_bytes)))
    buf.extend(s_bytes)
    return buf


def _encode_submessage(field: int, inner: bytes | bytearray) -> bytearray:
    buf = bytearray()
    buf.extend(_encode_tag(field, 2))
    buf.extend(_encode_varint(len(inner)))
    buf.extend(inner)
    return buf


def _encode_airport(code: str) -> bytearray:
    return _encode_string(2, code)


def _encode_leg(date: str, from_apt: str, to_apt: str) -> bytearray:
    buf = bytearray()
    buf.extend(_encode_string(2, date))
    buf.extend(_encode_submessage(13, _encode_airport(from_apt)))
    buf.extend(_encode_submessage(14, _encode_airport(to_apt)))
    return buf


def build_canonical_google_flights_url(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    currency: str = "BRL",
) -> str:
    """Gera a URL canônica do Google Flights com protobuf tfs base64."""
    buf = bytearray()
    leg1 = _encode_leg(departure_date, origin, destination)
    buf.extend(_encode_submessage(3, leg1))

    trip_code = 2  # ONE_WAY
    if return_date:
        leg2 = _encode_leg(return_date, destination, origin)
        buf.extend(_encode_submessage(3, leg2))
        trip_code = 1  # ROUND_TRIP

    # 1 passageiro adulto
    pax_packed = bytearray()
    pax_packed.extend(_encode_varint(1))
    buf.extend(_encode_tag(8, 2))
    buf.extend(_encode_varint(len(pax_packed)))
    buf.extend(pax_packed)

    # Assento: Economy (1)
    buf.extend(_encode_tag(9, 0))
    buf.extend(_encode_varint(1))

    # Tipo de viagem
    buf.extend(_encode_tag(19, 0))
    buf.extend(_encode_varint(trip_code))

    b64 = base64.standard_b64encode(buf).decode("utf-8")
    return (
        f"https://www.google.com/travel/flights/search?tfs={b64}&hl=pt-BR&gl=BR&curr={currency}"
    )


class FlightSearchClient:
    """Cliente para consulta de voos no Google Flights via fli (curl_cffi/RPC)."""

    def __init__(self) -> None:
        self._client = SearchFlights()

    def search_route(self, route: RouteConfig) -> list[FlightDeal]:
        """Pesquisa voos para uma determinada rota e retorna a lista de ofertas."""
        try:
            origin_apt = resolve_airport(route.origin)
            dest_apt = resolve_airport(route.destination)

            segments, trip_type = build_flight_segments(
                origin=origin_apt,
                destination=dest_apt,
                departure_date=route.departure_date,
                return_date=route.return_date,
            )

            parsed_airlines = parse_airlines(route.airlines) if route.airlines else None
            parsed_exclude = (
                parse_airlines(route.exclude_airlines) if route.exclude_airlines else None
            )

            filters = FlightSearchFilters(
                trip_type=trip_type,
                passenger_info=PassengerInfo(adults=1),
                flight_segments=segments,
                stops=parse_max_stops(route.max_stops),
                seat_type=parse_cabin_class(route.cabin_class),
                airlines=parsed_airlines,
                airlines_exclude=parsed_exclude,
                sort_by=parse_sort_by("CHEAPEST"),
                show_all_results=False,
            )

            logger.info(
                f"Consultando voos: {route.origin} -> {route.destination} "
                f"(Ida: {route.departure_date}"
                f"{f', Volta: {route.return_date}' if route.return_date else ''})..."
            )

            raw_results = self._client.search(
                filters,
                currency=route.currency,
                language="pt-BR",
                country="BR",
            )

            if not raw_results:
                logger.warning(
                    f"Nenhum voo encontrado para {route.origin} -> {route.destination}"
                )
                return []

            deals: list[FlightDeal] = []
            for item in raw_results:
                serialized = serialize_flight_result(item, trip_type)
                deal = self._to_domain(route, serialized)
                deals.append(deal)

            deals.sort(key=lambda d: d.price)
            logger.info(
                f"Encontrados {len(deals)} voos. Menor preço: {route.currency} {deals[0].price}"
            )
            return deals

        except Exception as e:
            logger.error(f"Erro ao buscar voos para rota {route.id}: {e}")
            return []

    def _to_domain(self, route: RouteConfig, data: dict) -> FlightDeal:
        """Converte o dicionário serializado do fli em entidade FlightDeal."""
        outbound = data.get("outbound")
        if isinstance(outbound, dict) and "legs" in outbound:
            outbound_legs = outbound.get("legs", [])
        else:
            outbound_legs = data.get("legs", [])

        airline_name = "Desconhecida"
        out_dep = ""
        out_arr = ""

        if outbound_legs:
            first_leg = outbound_legs[0]
            last_leg = outbound_legs[-1]
            airline_name = first_leg.get("airline", {}).get("name", "Várias")
            out_dep = first_leg.get("departure_time", "")
            out_arr = last_leg.get("arrival_time", "")

        ret_dep = None
        ret_arr = None
        ret_data = data.get("return")
        if ret_data and ret_data.get("legs"):
            ret_legs = ret_data["legs"]
            ret_dep = ret_legs[0].get("departure_time")
            ret_arr = ret_legs[-1].get("arrival_time")

        # Construir link canônico direto no Google Flights com protobuf tfs
        google_url = build_canonical_google_flights_url(
            origin=route.origin,
            destination=route.destination,
            departure_date=route.departure_date,
            return_date=route.return_date,
            currency=route.currency,
        )

        return FlightDeal(
            route_id=route.id,
            origin=route.origin,
            destination=route.destination,
            departure_date=route.departure_date,
            return_date=route.return_date,
            price=float(data.get("price", 0.0)),
            currency=data.get("currency", route.currency),
            airline=airline_name,
            stops=int(data.get("stops", 0)),
            outbound_departure=out_dep,
            outbound_arrival=out_arr,
            return_departure=ret_dep,
            return_arrival=ret_arr,
            total_duration_minutes=int(data.get("duration", 0)),
            google_flights_url=google_url,
        )
