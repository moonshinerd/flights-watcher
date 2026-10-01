from datetime import datetime, timedelta
import json
from pathlib import Path
import signal
import sys
import time
import httpx
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
        self._start_time: datetime = datetime.now()

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

    @property
    def uptime_str(self) -> str:
        """Formata o tempo decorrido desde a inicialização do serviço."""
        diff = datetime.now() - self._start_time
        total_seconds = int(diff.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        parts = []
        if days > 0:
            parts.append(f"{days} dia(s)")
        if hours > 0 or days > 0:
            parts.append(f"{hours} hora(s)")
        parts.append(f"{minutes} minuto(s)")
        return ", ".join(parts)

    def build_routes_matrix(self) -> list[dict]:
        """Constrói a matriz completa de todas as rotas configuradas com o status atual."""
        routes = self.load_routes()
        price_summary = self.repository.get_route_price_summary()

        matrix = []
        for r in routes:
            info = price_summary.get(r.id, {})
            min_price = info.get("min_price")
            airline = info.get("airline", "-")
            checks_count = info.get("checks_count", 0)

            if r.return_date:
                trip_type = "Ida e Volta"
            elif r.origin == "BSB":
                trip_type = "Ida"
            else:
                trip_type = "Volta"

            if min_price is not None:
                if min_price <= r.target_price:
                    status = "Abaixo da Meta"
                    status_badge = "🟢"
                else:
                    status = f"Acima da Meta ({r.currency} {min_price:.2f})"
                    status_badge = "🟡"
            else:
                status = "Aguardando Abertura"
                status_badge = "⏳"

            matrix.append(
                {
                    "id": r.id,
                    "origin": r.origin,
                    "destination": r.destination,
                    "trip_type": trip_type,
                    "departure_date": r.departure_date,
                    "return_date": r.return_date,
                    "target_price": r.target_price,
                    "min_price": min_price,
                    "currency": r.currency,
                    "airline": airline,
                    "status": status,
                    "status_badge": status_badge,
                    "checks_count": checks_count,
                }
            )
        return matrix

    def send_heartbeat_if_due(self, force: bool = False) -> bool:
        """Envia relatório periódico de saúde caso o intervalo de dias tenha expirado."""
        now = datetime.now()
        last_heartbeat_str = self.repository.get_metadata("last_heartbeat_at")

        if last_heartbeat_str and not force:
            try:
                last_time = datetime.fromisoformat(last_heartbeat_str)
                interval = timedelta(days=settings.HEARTBEAT_INTERVAL_DAYS)
                if now - last_time < interval:
                    return False
            except Exception as e:
                logger.warning(f"Erro ao interpretar timestamp de heartbeat anterior: {e}")

        stats = self.repository.get_stats()
        stats["uptime"] = self.uptime_str
        matrix = self.build_routes_matrix()
        stats["routes_matrix"] = matrix
        stats["total_configured_routes"] = len(matrix)

        sent = self.notifier.send_heartbeat_alert(stats)
        if sent or force:
            self.repository.set_metadata("last_heartbeat_at", now.isoformat())
            logger.info("Relatório periódico de saúde (Heartbeat) processado.")
        return sent

    def ping_healthcheck(self) -> bool:
        """Envia ping HTTP para monitor externo de Dead Man's Switch (ex: healthchecks.io)."""
        if not settings.HEALTHCHECK_PING_URL:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(settings.HEALTHCHECK_PING_URL)
                resp.raise_for_status()
                logger.debug(f"Ping externo de saúde enviado para {settings.HEALTHCHECK_PING_URL}.")
                return True
        except Exception as e:
            logger.warning(f"Falha ao enviar ping de healthcheck externo: {e}")
            return False

    def send_shutdown_alert(self, reason: str) -> bool:
        """Envia alerta de emergência comunicando que o processo está sendo finalizado."""
        if not settings.ALERT_ON_SHUTDOWN:
            return False
        try:
            logger.warning(f"Disparando alerta de shutdown: {reason}")
            return self.notifier.send_shutdown_alert(reason, self.uptime_str)
        except Exception as e:
            logger.error(f"Erro ao disparar alerta de shutdown: {e}")
            return False

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

        # Verifica e envia o heartbeat se devido (ex: a cada 7 dias)
        self.send_heartbeat_if_due()

        # Envia ping externo de Dead Man's Switch (se configurado)
        self.ping_healthcheck()

        logger.info("Ciclo de verificação finalizado com sucesso.")
        return found_deals

    def run_forever(self) -> None:
        """Executa o loop contínuo 24/7 com intervalo configurável."""
        logger.info(
            f"Iniciando Flight Monitor 24/7 (Intervalo: a cada {settings.CHECK_INTERVAL_MINUTES} minutos, "
            f"Heartbeat: a cada {settings.HEARTBEAT_INTERVAL_DAYS} dias)..."
        )

        def signal_handler(signum, frame):
            sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
            logger.warning(f"Sinal {sig_name} recebido. Encerrando monitor...")
            self.send_shutdown_alert(f"Sinal do sistema operacional ({sig_name})")
            sys.exit(0)

        # Registra captura de sinais para desligamento / systemctl stop
        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
        except (ValueError, AttributeError):
            pass

        try:
            while True:
                try:
                    self.run_once()
                except KeyboardInterrupt:
                    logger.warning("Interrupção pelo usuário recebida. Encerrando monitor...")
                    self.send_shutdown_alert("Interrupção manual (KeyboardInterrupt)")
                    break
                except SystemExit:
                    break
                except Exception as e:
                    self._handle_error(e, context="Loop contínuo 24/7")

                sleep_seconds = settings.CHECK_INTERVAL_MINUTES * 60
                logger.info(
                    f"Próxima checagem em {settings.CHECK_INTERVAL_MINUTES} minutos. Aguardando..."
                )
                try:
                    time.sleep(sleep_seconds)
                except KeyboardInterrupt:
                    logger.warning("Interrupção pelo usuário recebida. Encerrando monitor...")
                    self.send_shutdown_alert("Interrupção manual (KeyboardInterrupt)")
                    break
                except SystemExit:
                    break
        except Exception as fatal_e:
            logger.critical(f"Falha fatal no monitor: {fatal_e}")
            self.send_shutdown_alert(f"Falha fatal: {type(fatal_e).__name__}: {fatal_e}")
            raise
