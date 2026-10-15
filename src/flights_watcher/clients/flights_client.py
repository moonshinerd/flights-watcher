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
    if value < 0:
        raise ValueError("Varint value must be non-negative")
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


def _encode_varint_64(val: int) -> bytearray:
    """Codifica inteiro de 64 bits (inclusive valores negativos como complemento de dois)."""
    if val < 0:
        val = (1 << 64) + val
    buf = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val == 0:
            buf.append(b)
            break
        buf.append(b | 0x80)
    return buf


def _encode_flight_segment(
    origin: str, date: str, destination: str, airline_code: str, flight_number: str
) -> bytearray:
    buf = bytearray()
    buf.extend(_encode_string(1, origin))
    buf.extend(_encode_string(2, date))
    buf.extend(_encode_string(3, destination))
    buf.extend(_encode_string(5, airline_code))
    buf.extend(_encode_string(6, flight_number))
    return buf


def _encode_booking_airport(code: str) -> bytearray:
    buf = bytearray()
    buf.extend(_encode_tag(1, 0))
    buf.extend(_encode_varint(1))
    buf.extend(_encode_string(2, code))
    return buf


def _encode_tfu_wrapper(token: str) -> str:
    """Empacota o token de reserva do Google Flights no invólucro protobuf esperado pelo parâmetro tfu."""
    buf = bytearray()
    tok_bytes = token.encode("ascii")
    buf.append((1 << 3) | 2)
    buf.extend(_encode_varint(len(tok_bytes)))
    buf.extend(tok_bytes)
    buf.append((2 << 3) | 2)
    sub = bytearray([(1 << 3) | 0, 0])
    buf.extend(_encode_varint(len(sub)))
    buf.extend(sub)
    buf.append((4 << 3) | 2)
    buf.append(0)
    return base64.urlsafe_b64encode(buf).decode("ascii").rstrip("=")


AIRLINE_NAME_TO_CODE = {
    "LATAM": "LA",
    "LATAM AIRLINES": "LA",
    "LATAM CHILE": "LA",
    "LATAM BRASIL": "LA",
    "GOL": "G3",
    "GOL TRANSPORTES AÉREOS": "G3",
    "GOL TRANSPORTES AEREOS": "G3",
    "GOL LINHAS AÉREAS": "G3",
    "GOL LINHAS AEREAS": "G3",
    "AZUL": "AD",
    "AZUL LINHAS AÉREAS": "AD",
    "AZUL LINHAS AEREAS": "AD",
    "VOEPASS": "2Z",
}


def build_google_flights_booking_url(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    outbound_legs: list[dict] | None = None,
    return_legs: list[dict] | None = None,
    session_id: str | None = None,
    price: float | None = None,
    currency: str = "BRL",
) -> str:
    """Gera a URL direta da página de reserva (/booking) do Google Flights para os voos selecionados."""
    if not outbound_legs or not any(
        seg.get("airline_code") and seg.get("flight_number") for seg in outbound_legs
    ):
        return build_canonical_google_flights_url(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            currency=currency,
        )

    buf = bytearray()
    buf.extend(_encode_tag(1, 0))
    buf.extend(_encode_varint(28))
    buf.extend(_encode_tag(2, 0))
    buf.extend(_encode_varint(2))

    # Outbound leg
    leg1 = bytearray()
    leg1.extend(_encode_string(2, departure_date))
    for seg in outbound_legs:
        leg1.extend(
            _encode_submessage(
                4,
                _encode_flight_segment(
                    seg["origin"],
                    seg.get("date", departure_date),
                    seg["destination"],
                    seg["airline_code"],
                    str(seg["flight_number"]),
                ),
            )
        )
    leg1.extend(_encode_submessage(13, _encode_booking_airport(origin)))
    leg1.extend(_encode_submessage(14, _encode_booking_airport(destination)))
    buf.extend(_encode_submessage(3, leg1))

    trip_code = 2  # ONE_WAY
    if (
        return_date
        and return_legs
        and any(seg.get("airline_code") and seg.get("flight_number") for seg in return_legs)
    ):
        trip_code = 1  # ROUND_TRIP
        leg2 = bytearray()
        leg2.extend(_encode_string(2, return_date))
        for seg in return_legs:
            leg2.extend(
                _encode_submessage(
                    4,
                    _encode_flight_segment(
                        seg["origin"],
                        seg.get("date", return_date),
                        seg["destination"],
                        seg["airline_code"],
                        str(seg["flight_number"]),
                    ),
                )
            )
        leg2.extend(_encode_submessage(13, _encode_booking_airport(destination)))
        leg2.extend(_encode_submessage(14, _encode_booking_airport(origin)))
        buf.extend(_encode_submessage(3, leg2))

    buf.extend(_encode_tag(8, 0))
    buf.extend(_encode_varint(1))
    buf.extend(_encode_tag(9, 0))
    buf.extend(_encode_varint(1))
    buf.extend(_encode_tag(14, 0))
    buf.extend(_encode_varint(1))

    f16 = bytearray()
    f16.extend(_encode_tag(1, 0))
    f16.extend(_encode_varint_64(-1))
    buf.extend(_encode_submessage(16, f16))

    buf.extend(_encode_tag(19, 0))
    buf.extend(_encode_varint(trip_code))

    tfs = base64.urlsafe_b64encode(buf).decode("utf-8").rstrip("=")

    tfu = None
    if session_id and price is not None:
        try:
            from fli.search._proto import build_booking_token

            last_leg = (
                return_legs[-1] if (trip_code == 1 and return_legs) else outbound_legs[-1]
            )
            token = build_booking_token(
                session_id=session_id,
                airline_code=last_leg["airline_code"],
                flight_number=str(last_leg["flight_number"]),
                leg_index=1,
                price_cents=int(round(price * 100)),
                currency=currency,
            )
            tfu = _encode_tfu_wrapper(token)
        except Exception as e:
            logger.debug(f"Não foi possível gerar parâmetro tfu para booking: {e}")

    url = f"https://www.google.com/travel/flights/booking?tfs={tfs}"
    if tfu:
        url += f"&tfu={tfu}"
    url += f"&hl=pt-BR&gl=BR&curr={currency}"
    return url


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
            session_id = getattr(self._client, "_last_session_id", None)
            for item in raw_results:
                serialized = serialize_flight_result(item, trip_type)
                deal = self._to_domain(route, serialized, session_id=session_id)
                deals.append(deal)

            deals.sort(key=lambda d: d.price)
            logger.info(
                f"Encontrados {len(deals)} voos. Menor preço: {route.currency} {deals[0].price}"
            )
            return deals

        except Exception as e:
            logger.error(f"Erro ao buscar voos para rota {route.id}: {e}")
            return []

    def _to_domain(
        self, route: RouteConfig, data: dict, session_id: str | None = None
    ) -> FlightDeal:
        """Converte o dicionário serializado do fli em entidade FlightDeal com link direto de reserva."""
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
        ret_legs = []
        ret_data = data.get("return")
        if ret_data and ret_data.get("legs"):
            ret_legs = ret_data["legs"]
            ret_dep = ret_legs[0].get("departure_time")
            ret_arr = ret_legs[-1].get("arrival_time")

        def _extract_parsed_legs(
            legs_list: list[dict],
            default_origin: str,
            default_dest: str,
            default_date: str,
        ) -> list[dict]:
            parsed = []
            for l in legs_list:
                orig = (
                    l.get("departure_airport", {}).get("code")
                    if isinstance(l.get("departure_airport"), dict)
                    else str(l.get("departure_airport") or default_origin)
                ) or default_origin
                dest = (
                    l.get("arrival_airport", {}).get("code")
                    if isinstance(l.get("arrival_airport"), dict)
                    else str(l.get("arrival_airport") or default_dest)
                ) or default_dest
                dep_time = l.get("departure_time", "")
                date_str = dep_time[:10] if len(dep_time) >= 10 else default_date

                air = l.get("airline", {})
                air_code = ""
                if isinstance(air, dict):
                    air_code = air.get("code", "")
                    if not air_code and air.get("name"):
                        air_code = AIRLINE_NAME_TO_CODE.get(air["name"].upper(), "")
                elif isinstance(air, str):
                    air_code = AIRLINE_NAME_TO_CODE.get(air.upper(), air)

                f_num = str(l.get("flight_number", "") or "")
                parsed.append(
                    {
                        "origin": orig,
                        "destination": dest,
                        "date": date_str,
                        "airline_code": air_code,
                        "flight_number": f_num,
                    }
                )
            return parsed

        parsed_out_legs = _extract_parsed_legs(
            outbound_legs, route.origin, route.destination, route.departure_date
        )
        parsed_ret_legs = (
            _extract_parsed_legs(
                ret_legs, route.destination, route.origin, route.return_date or ""
            )
            if ret_legs
            else []
        )

        google_url = build_google_flights_booking_url(
            origin=route.origin,
            destination=route.destination,
            departure_date=route.departure_date,
            return_date=route.return_date,
            outbound_legs=parsed_out_legs,
            return_legs=parsed_ret_legs,
            session_id=session_id,
            price=float(data.get("price", 0.0)),
            currency=data.get("currency", route.currency),
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
