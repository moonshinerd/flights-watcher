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
        outbound = data.get("outbound", {})
        outbound_legs = outbound.get("legs", [])

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

        # Construir link direto no Google Flights
        search_query = f"flights from {route.origin} to {route.destination} on {route.departure_date}"
        if route.return_date:
            search_query += f" returning {route.return_date}"
        encoded_query = urllib.parse.quote(search_query)
        google_url = f"https://www.google.com/travel/flights?q={encoded_query}"

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
