from abc import ABC, abstractmethod
import httpx
from loguru import logger

from flights_watcher.config import settings
from flights_watcher.domain.models import FlightDeal, RouteConfig


class NotifierPort(ABC):
    """Interface abstrata para envio de notificações."""

    @abstractmethod
    def send_deal_alert(self, route: RouteConfig, deal: FlightDeal) -> bool:
        """Envia alerta de passagem abaixo da meta."""
        pass


class ConsoleNotifier(NotifierPort):
    """Notificador via saída de terminal (Log/Stdout)."""

    def send_deal_alert(self, route: RouteConfig, deal: FlightDeal) -> bool:
        trip_type = "Ida e Volta" if deal.is_round_trip else "Somente Ida"
        logger.success(
            f"\n{'='*50}\n"
            f"🎯 ALERTA DE PASSAGEM ENCONTRADA!\n"
            f"Rota: {deal.origin} ➔ {deal.destination} ({trip_type})\n"
            f"Preço: {deal.currency} {deal.price:.2f} (Meta: {route.currency} {route.target_price:.2f})\n"
            f"Companhia: {deal.airline} | Escalas: {deal.stops}\n"
            f"Ida: {deal.departure_date} ({deal.outbound_departure} -> {deal.outbound_arrival})\n"
            f"{f'Volta: {deal.return_date} ({deal.return_departure} -> {deal.return_arrival})\n' if deal.is_round_trip else ''}"
            f"Link: {deal.google_flights_url}\n"
            f"{'='*50}"
        )
        return True


class TelegramNotifier(NotifierPort):
    """Notificador via Telegram Bot API."""

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None) -> None:
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_deal_alert(self, route: RouteConfig, deal: FlightDeal) -> bool:
        if not self.is_configured:
            logger.debug("Telegram não configurado (TELEGRAM_BOT_TOKEN/CHAT_ID ausentes).")
            return False

        trip_type = "Ida e Volta" if deal.is_round_trip else "Somente Ida"
        stops_text = "Voo direto" if deal.stops == 0 else f"{deal.stops} parada(s)"

        msg = (
            f"✈️ *ALERTA DE PASSAGEM AÉREA!*\n\n"
            f"📍 *Rota:* `{deal.origin}` ➔ `{deal.destination}`\n"
            f"🔄 *Tipo:* {trip_type}\n"
            f"💰 *Preço Atual:* `{deal.currency} {deal.price:.2f}`\n"
            f"🎯 *Sua Meta:* `{route.currency} {route.target_price:.2f}`\n\n"
            f"🏢 *Companhia:* {deal.airline}\n"
            f"🛑 *Escalas:* {stops_text}\n"
            f"📅 *Ida:* `{deal.departure_date}`\n"
        )
        if deal.is_round_trip:
            msg += f"📅 *Volta:* `{deal.return_date}`\n"

        if deal.google_flights_url:
            msg += f"\n🔗 [Abrir no Google Flights]({deal.google_flights_url})\n"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                logger.info(f"Notificação Telegram enviada com sucesso para chat {self.chat_id}!")
                return True
        except Exception as e:
            logger.error(f"Falha ao enviar notificação no Telegram: {e}")
            return False


class CompositeNotifier(NotifierPort):
    """Envia notificação para todos os canais configurados (Console + Telegram)."""

    def __init__(self, notifiers: list[NotifierPort]) -> None:
        self.notifiers = notifiers

    def send_deal_alert(self, route: RouteConfig, deal: FlightDeal) -> bool:
        success = False
        for notifier in self.notifiers:
            try:
                res = notifier.send_deal_alert(route, deal)
                if res:
                    success = True
            except Exception as e:
                logger.error(f"Erro no notificador {type(notifier).__name__}: {e}")
        return success
