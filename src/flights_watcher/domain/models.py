from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class RouteConfig(BaseModel):
    """Configuração de uma rota a ser monitorada."""

    id: str = Field(description="Identificador único da rota (ex: gru-mia-nov26)")
    origin: str = Field(description="Código IATA de origem (ex: GRU)")
    destination: str = Field(description="Código IATA de destino (ex: MIA)")
    departure_date: str = Field(description="Data de ida YYYY-MM-DD")
    return_date: str | None = Field(default=None, description="Data de volta YYYY-MM-DD")
    target_price: float = Field(description="Preço teto desejado para disparar alerta")
    currency: str = Field(default="BRL", description="Moeda para pesquisa")
    max_stops: Literal["ANY", "0", "1", "2+"] = Field(
        default="ANY", description="Máximo de escalas permitidas"
    )
    cabin_class: Literal["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"] = Field(
        default="ECONOMY", description="Classe da cabine"
    )
    airlines: list[str] | None = Field(
        default=None, description="Lista de códigos IATA para filtrar (ex: ['G3', 'LA', 'AD'])"
    )
    exclude_airlines: list[str] | None = Field(
        default=None, description="Lista de códigos IATA para excluir (ex: ['AA'])"
    )
    active: bool = Field(default=True, description="Se a rota está ativa para monitoramento")


class FlightDeal(BaseModel):
    """Representação de uma oferta de voo encontrada."""

    route_id: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None = None
    price: float
    currency: str = "BRL"
    airline: str
    stops: int
    outbound_departure: str
    outbound_arrival: str
    return_departure: str | None = None
    return_arrival: str | None = None
    total_duration_minutes: int
    google_flights_url: str | None = None
    checked_at: datetime = Field(default_factory=datetime.now)

    @property
    def is_round_trip(self) -> bool:
        return self.return_date is not None
