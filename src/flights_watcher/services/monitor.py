import json
from pathlib import Path
import time
from loguru import logger

from flights_watcher.clients.flights_client import FlightSearchClient
from flights_watcher.clients.notifier import (
    CompositeNotifier,
    ConsoleNotifier,
    EmailNotifier,
    NotifierPort,
    TelegramNotifier,
)
from flights_watcher.config import settings
from flights_watcher.domain.models import FlightDeal, RouteConfig
from flights_watcher.storage.repository import FlightRepository


class MonitorService:
    """Serviço principal de monitoramento de passagens aéreas."""

    def __init__(
        self,
        search_client: FlightSearchClient | None = None,
        repository: FlightRepository | None = None,
        notifier: NotifierPort | None = None,
        routes_file: Path | str | None = None,
    ) -> None:
        self.search_client = search_client or FlightSearchClient()
        self.repository = repository or FlightRepository(settings.DATABASE_PATH)
        self.notifier = notifier or CompositeNotifier(
            [ConsoleNotifier(), EmailNotifier(), TelegramNotifier()]
        )
        self.routes_file = Path(routes_file or settings.ROUTES_FILE)
        self._consecutive_errors: int = 0
        self._last_error_alert_time: float = 0.0
        self._error_alert_cooldown_seconds: float = 7200.0  # 2 horas

    def _handle_error(self, error: Exception, context: str) -> None:
        """Registra erro e envia alerta com cooldown para evitar spam."""
        self._consecutive_errors += 1
        logger.error(f"Erro no monitor [{context}]: {error}")
        now = time.time()
        if now - self._last_error_alert_time >= self._error_alert_cooldown_seconds:
            error_msg = f"{type(error).__name__}: {str(error)}"
            full_context = f"{context} (Falhas consecutivas: {self._consecutive_errors})"
            try:
                self.notifier.send_error_alert(error_msg, context=full_context)
                self._last_error_alert_time = now
            except Exception as notify_err:
                logger.error(f"Falha ao enviar notificação de erro: {notify_err}")

    def load_routes(self) -> list[RouteConfig]:
        """Carrega a lista de rotas a partir do arquivo routes.json."""
        if not self.routes_file.exists():
            logger.warning(
                f"Arquivo de rotas {self.routes_file} não encontrado. Criando modelo de exemplo..."
            )
            self._create_example_routes_file()

        try:
            with open(self.routes_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            routes = [RouteConfig(**item) for item in data if item.get("active", True)]
            logger.info(f"{len(routes)} rota(s) ativa(s) carregada(s) de {self.routes_file}.")
            return routes
        except Exception as e:
            self._handle_error(e, context=f"Leitura de rotas ({self.routes_file})")
            return []

    def _create_example_routes_file(self) -> None:
        """Cria um arquivo routes.json de exemplo caso não exista."""
        examples = [
            {
                "id": "gru-gig-novembro",
                "origin": "GRU",
                "destination": "GIG",
                "departure_date": "2026-11-10",
                "return_date": "2026-11-17",
                "target_price": 800.0,
                "currency": "BRL",
                "max_stops": "ANY",
                "cabin_class": "ECONOMY",
                "active": True,
            }
        ]
        with open(self.routes_file, "w", encoding="utf-8") as f:
            json.dump(examples, f, indent=2, ensure_ascii=False)
        logger.info(f"Arquivo de rotas de exemplo criado em {self.routes_file}")

    def check_route(self, route: RouteConfig) -> FlightDeal | None:
        """Verifica uma rota específica, salva no histórico e envia alerta se oportuno."""
        deals = self.search_client.search_route(route)
        if not deals:
            return None

        best_deal = deals[0]

        # Salva o menor preço desta rodada no histórico
        self.repository.save_deal(best_deal)

        # Avalia se deve disparar notificação
        if self.repository.should_notify(
            best_deal,
            target_price=route.target_price,
            cooldown_hours=settings.NOTIFICATION_COOLDOWN_HOURS,
        ):
            notified = self.notifier.send_deal_alert(route, best_deal)
            if notified:
                self.repository.record_notification(best_deal)

        return best_deal

    def run_once(self) -> list[FlightDeal]:
        """Executa um ciclo completo de verificação em todas as rotas ativas."""
        routes = self.load_routes()
        found_deals: list[FlightDeal] = []

        logger.info(f"Iniciando ciclo de verificação para {len(routes)} rotas...")
        for route in routes:
            try:
                deal = self.check_route(route)
                if deal:
                    found_deals.append(deal)
            except Exception as e:
                logger.error(f"Erro ao verificar rota {route.id}: {e}")
            # Pequeno intervalo entre pesquisas para cortesia com o servidor
            time.sleep(2)

        # Se o ciclo concluiu normalmente, resetamos contador de erros consecutivos
        self._consecutive_errors = 0
        logger.info("Ciclo de verificação finalizado com sucesso.")
        return found_deals

    def run_forever(self) -> None:
        """Executa o loop contínuo 24/7 com intervalo configurável."""
        logger.info(
            f"Iniciando Flight Monitor 24/7 (Intervalo: a cada {settings.CHECK_INTERVAL_MINUTES} minutos)..."
        )
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                logger.warning("Interrupção pelo usuário recebida. Encerrando monitor...")
                break
            except Exception as e:
                self._handle_error(e, context="Loop contínuo 24/7")

            sleep_seconds = settings.CHECK_INTERVAL_MINUTES * 60
            logger.info(f"Próxima checagem em {settings.CHECK_INTERVAL_MINUTES} minutos. Aguardando...")
            try:
                time.sleep(sleep_seconds)
            except KeyboardInterrupt:
                logger.warning("Interrupção pelo usuário recebida. Encerrando monitor...")
                break
