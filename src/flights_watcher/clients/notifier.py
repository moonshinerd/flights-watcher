import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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


_SENTINEL = object()


class EmailNotifier(NotifierPort):
    """Notificador via E-mail (SMTP com suporte a SSL/TLS e HTML responsivo)."""

    def __init__(
        self,
        smtp_host: str = _SENTINEL,
        smtp_port: int = _SENTINEL,
        smtp_user: str | None = _SENTINEL,
        smtp_password: str | None = _SENTINEL,
        email_to: str | None = _SENTINEL,
    ) -> None:
        self.smtp_host = settings.SMTP_HOST if smtp_host is _SENTINEL else smtp_host
        self.smtp_port = settings.SMTP_PORT if smtp_port is _SENTINEL else smtp_port
        self.smtp_user = settings.email_user if smtp_user is _SENTINEL else smtp_user
        self.smtp_password = (
            settings.email_password if smtp_password is _SENTINEL else smtp_password
        )
        self.email_to = settings.email_to if email_to is _SENTINEL else email_to

    @property
    def is_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_to)

    def send_deal_alert(self, route: RouteConfig, deal: FlightDeal) -> bool:
        if not self.is_configured:
            logger.debug("EmailNotifier não configurado (credenciais ausentes).")
            return False

        trip_type = "Ida e Volta" if deal.is_round_trip else "Somente Ida"
        stops_text = "Voo direto" if deal.stops == 0 else f"{deal.stops} parada(s)"

        subject = (
            f"✈️ Alerta: {deal.origin} ➔ {deal.destination} por {deal.currency} {deal.price:.2f} "
            f"(Meta: {route.currency} {route.target_price:.2f})"
        )

        plain_text = (
            f"Alerta de Passagem Aérea!\n\n"
            f"Rota: {deal.origin} -> {deal.destination} ({trip_type})\n"
            f"Preço: {deal.currency} {deal.price:.2f} (Sua meta: {route.currency} {route.target_price:.2f})\n"
            f"Companhia: {deal.airline}\n"
            f"Escalas: {stops_text}\n"
            f"Ida: {deal.departure_date} ({deal.outbound_departure} -> {deal.outbound_arrival})\n"
        )
        if deal.is_round_trip:
            plain_text += f"Volta: {deal.return_date} ({deal.return_departure} -> {deal.return_arrival})\n"

        if deal.google_flights_url:
            plain_text += f"\nComprar no Google Flights: {deal.google_flights_url}\n"

        return_row = ""
        if deal.is_round_trip:
            return_times = f" ({deal.return_departure} - {deal.return_arrival})" if deal.return_departure else ""
            return_row = f"""<tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 0; color: #666;">Volta:</td>
          <td style="padding: 8px 0; text-align: right;"><strong>{deal.return_date}</strong>{return_times}</td>
        </tr>"""

        cta_button = ""
        if deal.google_flights_url:
            cta_button = f'<div style="text-align: center; margin-top: 24px;"><a href="{deal.google_flights_url}" style="background-color: #1a73e8; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">Ver e Comprar no Google Flights</a></div>'

        outbound_times = f" ({deal.outbound_departure} - {deal.outbound_arrival})" if deal.outbound_departure else ""

        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px;">
  <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
    <div style="background: #1a73e8; color: #ffffff; padding: 20px; text-align: center;">
      <h2 style="margin: 0; font-size: 20px;">✈️ Passagem Abaixo da Meta Encontrada!</h2>
    </div>
    <div style="padding: 24px;">
      <div style="background: #e6f4ea; border: 1px solid #ceead6; border-radius: 8px; padding: 16px; text-align: center; margin-bottom: 20px;">
        <div style="font-size: 26px; font-weight: bold; color: #137333;">{deal.currency} {deal.price:.2f}</div>
        <div style="font-size: 13px; color: #5f6368; margin-top: 4px;">Sua meta era {route.currency} {route.target_price:.2f}</div>
      </div>
      <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 0; color: #666;">Rota:</td>
          <td style="padding: 8px 0; font-weight: bold; text-align: right;">{deal.origin} ➔ {deal.destination} ({trip_type})</td>
        </tr>
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 0; color: #666;">Companhia:</td>
          <td style="padding: 8px 0; font-weight: bold; text-align: right;">{deal.airline}</td>
        </tr>
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 0; color: #666;">Escalas:</td>
          <td style="padding: 8px 0; font-weight: bold; text-align: right;">{stops_text}</td>
        </tr>
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 0; color: #666;">Ida:</td>
          <td style="padding: 8px 0; text-align: right;"><strong>{deal.departure_date}</strong>{outbound_times}</td>
        </tr>
        {return_row}
      </table>
      {cta_button}
    </div>
    <div style="padding: 14px; text-align: center; font-size: 11px; color: #888; background: #fafafa; border-top: 1px solid #f0f0f0;">
      Enviado automaticamente pelo flights-watcher 24/7.
    </div>
  </div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Flights Watcher <{self.smtp_user}>"
        msg["To"] = self.email_to

        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            logger.info(f"Notificação por e-mail enviada com sucesso para {self.email_to}!")
            return True
        except Exception as e:
            logger.error(f"Falha ao enviar notificação por e-mail: {e}")
            return False


class TelegramNotifier(NotifierPort):
    """Notificador via Telegram Bot API."""

    def __init__(
        self, bot_token: str | None = _SENTINEL, chat_id: str | None = _SENTINEL
    ) -> None:
        self.bot_token = (
            settings.TELEGRAM_BOT_TOKEN if bot_token is _SENTINEL else bot_token
        )
        self.chat_id = settings.TELEGRAM_CHAT_ID if chat_id is _SENTINEL else chat_id

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
    """Envia notificação para todos os canais configurados (Console + Email + Telegram)."""

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
