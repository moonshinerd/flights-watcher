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

    def send_error_alert(self, error_message: str, context: str | None = None) -> bool:
        """Envia alerta de erro ou falha no monitor."""
        return False

    def send_heartbeat_alert(self, stats: dict) -> bool:
        """Envia relatório periódico (ex: a cada 7 dias) informando que o monitor está ativo."""
        return False

    def send_shutdown_alert(self, reason: str, uptime_str: str) -> bool:
        """Envia alerta de emergência informando que o processo está sendo finalizado."""
        return False


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

    def send_error_alert(self, error_message: str, context: str | None = None) -> bool:
        ctx = f" [Contexto: {context}]" if context else ""
        logger.error(
            f"\n{'!'*50}\n"
            f"🚨 ALERTA DE ERRO NO MONITOR{ctx}\n"
            f"{error_message}\n"
            f"{'!'*50}"
        )
        return True

    def send_heartbeat_alert(self, stats: dict) -> bool:
        logger.info(
            f"💚 [Heartbeat] Sistema ativo. Uptime: {stats.get('uptime', 'N/A')}. "
            f"Cotações registradas: {stats.get('total_prices', 0)}"
        )
        return True

    def send_shutdown_alert(self, reason: str, uptime_str: str) -> bool:
        logger.warning(f"⚠️ [Shutdown] Processo encerrando: {reason}. Uptime: {uptime_str}")
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

        return self._send_message(msg, recipient=self.email_to, log_label="Notificação por e-mail")

    def send_error_alert(self, error_message: str, context: str | None = None) -> bool:
        if not self.is_configured:
            logger.debug("EmailNotifier não configurado para envio de erros.")
            return False

        subject = "🚨 [Flights Watcher] Falha Detectada no Monitor 24/7"
        ctx_plain = f"Contexto: {context}\n\n" if context else ""
        plain_text = (
            f"🚨 ALERTA DE ERRO NO FLIGHTS WATCHER\n\n"
            f"{ctx_plain}"
            f"Descrição do Erro:\n{error_message}\n\n"
            f"Para verificar os logs no servidor:\n"
            f"ssh talos 'journalctl -u flights-watcher -n 50 --no-pager'\n"
        )

        ctx_html = (
            f'<div style="background: #f8f9fa; border-left: 4px solid #6c757d; padding: 10px 14px; font-size: 13px; color: #495057; margin-bottom: 16px;"><strong>Contexto:</strong> {context}</div>'
            if context
            else ""
        )

        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #fdf2f2; margin: 0; padding: 20px;">
  <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; border: 1px solid #f5c2c7; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
    <div style="background: #dc3545; color: #ffffff; padding: 18px; text-align: center;">
      <h2 style="margin: 0; font-size: 20px;">🚨 Falha no Monitor de Passagens</h2>
    </div>
    <div style="padding: 24px;">
      <p style="color: #333; font-size: 15px; margin-top: 0;">O monitor 24/7 encontrou uma instabilidade ou erro inesperado durante a execução:</p>
      {ctx_html}
      <div style="background: #fff5f5; border: 1px solid #ffcccc; border-radius: 6px; padding: 14px; font-family: monospace; font-size: 13px; color: #b02a37; white-space: pre-wrap; word-break: break-all;">{error_message}</div>
      <p style="color: #666; font-size: 13px; margin-top: 20px;">
        Para checar os logs completos no servidor:
        <br><code style="background: #f1f3f4; padding: 4px 8px; border-radius: 4px; display: inline-block; margin-top: 6px;">ssh talos "journalctl -u flights-watcher -n 50 --no-pager"</code>
      </p>
    </div>
    <div style="padding: 12px; text-align: center; font-size: 11px; color: #888; background: #fafafa; border-top: 1px solid #f0f0f0;">
      Enviado automaticamente pelo flights-watcher.
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

        return self._send_message(msg, recipient=self.email_to, log_label="Alerta de erro por e-mail")

    def send_heartbeat_alert(self, stats: dict) -> bool:
        if not self.is_configured:
            logger.debug("EmailNotifier não configurado para envio de heartbeat.")
            return False

        uptime = stats.get("uptime", "Ativo")
        total_prices = stats.get("total_prices", 0)
        total_notifications = stats.get("total_notifications", 0)
        lowest_prices = stats.get("lowest_prices", [])

        subject = "💚 [Flights Watcher] Relatório Semanal de Saúde - Sistema 100% Operacional"

        rows_html = ""
        for lp in lowest_prices:
            dates = f"{lp['departure_date']}" + (f" ➔ {lp['return_date']}" if lp.get('return_date') else "")
            rows_html += f"""
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 12px; font-weight: 600; color: #1f2937;">{lp['origin']} ➔ {lp['destination']}</td>
              <td style="padding: 10px 12px; color: #4b5563; font-size: 13px;">{dates}</td>
              <td style="padding: 10px 12px; font-weight: 700; color: #059669;">{lp['currency']} {lp['min_price']:.2f}</td>
              <td style="padding: 10px 12px; color: #6b7280; font-size: 13px;">{lp['airline']}</td>
            </tr>
            """

        if not rows_html:
            rows_html = """
            <tr>
              <td colspan="4" style="padding: 16px; text-align: center; color: #6b7280;">Ainda não há cotações salvas no histórico.</td>
            </tr>
            """

        plain_text = (
            f"💚 RELATÓRIO SEMANAL DE SAÚDE - FLIGHTS WATCHER\n\n"
            f"O monitor 24/7 está rodando normalmente no servidor talos e vigiando suas passagens!\n\n"
            f"• Uptime: {uptime}\n"
            f"• Total de cotações gravadas: {total_prices}\n"
            f"• Total de alertas enviados: {total_notifications}\n"
            f"• Rotas monitoradas ativas: {len(lowest_prices)}\n\n"
            f"Para checar os logs completos:\n"
            f"ssh talos 'journalctl -u flights-watcher -n 50 --no-pager'\n"
        )

        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; margin: 0; padding: 20px;">
  <div style="max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.06); border: 1px solid #e5e7eb;">
    <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #ffffff; padding: 24px; text-align: center;">
      <h2 style="margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.5px;">💚 Monitor 24/7 Ativo e Saudável</h2>
      <p style="margin: 6px 0 0 0; opacity: 0.92; font-size: 14px;">Relatório Periódico de Integridade do Sistema</p>
    </div>
    <div style="padding: 24px;">
      <p style="color: #374151; font-size: 15px; line-height: 1.5; margin-top: 0;">
        Olá! Este é o seu relatório semanal automático para confirmar que o <strong>Flights Watcher</strong> continua rodando normalmente no servidor e monitorando os voos para The Town 2027.
      </p>

      <table style="width: 100%; border-collapse: separate; border-spacing: 10px 0; margin: 20px 0;">
        <tr>
          <td style="width: 33%; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 14px; text-align: center;">
            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #065f46;">Tempo Ativo</div>
            <div style="font-size: 15px; font-weight: 800; color: #047857; margin-top: 4px;">{uptime}</div>
          </td>
          <td style="width: 33%; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 14px; text-align: center;">
            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #1e40af;">Cotações</div>
            <div style="font-size: 16px; font-weight: 800; color: #1d4ed8; margin-top: 4px;">{total_prices}</div>
          </td>
          <td style="width: 33%; background: #fdf4ff; border: 1px solid #f5d0fe; border-radius: 8px; padding: 14px; text-align: center;">
            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #86198f;">Rotas</div>
            <div style="font-size: 16px; font-weight: 800; color: #a21caf; margin-top: 4px;">{len(lowest_prices)}</div>
          </td>
        </tr>
      </table>

      <h3 style="font-size: 16px; color: #111827; margin: 24px 0 12px 0;">📊 Menores Preços Históricos por Rota</h3>
      <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; background: #fafafa; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
        <thead>
          <tr style="background: #f3f4f6; color: #4b5563; font-size: 12px; text-transform: uppercase;">
            <th style="padding: 10px 12px;">Rota</th>
            <th style="padding: 10px 12px;">Datas</th>
            <th style="padding: 10px 12px;">Menor Preço</th>
            <th style="padding: 10px 12px;">Cia</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>

      <div style="margin-top: 24px; padding: 14px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb; font-size: 13px; color: #4b5563;">
        🔍 <strong>Diagnóstico rápido:</strong> Para inspecionar o serviço no servidor talos:
        <br><code style="background: #e5e7eb; padding: 3px 6px; border-radius: 4px; display: inline-block; margin-top: 6px; font-family: monospace;">ssh talos 'journalctl -u flights-watcher -n 50 --no-pager'</code>
      </div>
    </div>
    <div style="padding: 14px; text-align: center; font-size: 12px; color: #9ca3af; background: #fafafa; border-top: 1px solid #f3f4f6;">
      Próximo relatório agendado para daqui a 7 dias. Flights Watcher 24/7.
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

        return self._send_message(msg, recipient=self.email_to, log_label="Relatório de saúde (Heartbeat)")

    def send_shutdown_alert(self, reason: str, uptime_str: str) -> bool:
        if not self.is_configured:
            logger.debug("EmailNotifier não configurado para envio de shutdown.")
            return False

        subject = "⚠️ [Flights Watcher] Processo Encerrando no Servidor"
        plain_text = (
            f"⚠️ ALERTA DE ENCERRAMENTO - FLIGHTS WATCHER\n\n"
            f"O serviço de monitoramento está sendo finalizado ou reiniciado.\n\n"
            f"• Motivo: {reason}\n"
            f"• Tempo em atividade (Uptime): {uptime_str}\n\n"
            f"Para verificar se o systemd já reiniciou o serviço:\n"
            f"ssh talos 'sudo systemctl status flights-watcher'\n"
        )

        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #fffbeb; margin: 0; padding: 20px;">
  <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; border: 1px solid #fde68a; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
    <div style="background: #d97706; color: #ffffff; padding: 18px; text-align: center;">
      <h2 style="margin: 0; font-size: 20px;">⚠️ Processo do Monitor Sendo Finalizado</h2>
    </div>
    <div style="padding: 24px;">
      <p style="color: #333; font-size: 15px; margin-top: 0;">
        O processo do <strong>Flights Watcher</strong> foi interrompido ou está sendo reiniciado no servidor.
      </p>
      <div style="background: #fef3c7; border: 1px solid #fcd34d; border-radius: 6px; padding: 14px; font-size: 14px; color: #92400e; margin: 16px 0;">
        <strong>Motivo:</strong> {reason}<br>
        <strong>Uptime acumulado:</strong> {uptime_str}
      </div>
      <p style="color: #666; font-size: 13px;">
        Se o encerramento não foi intencional, o <code>systemd</code> tentará subir o processo novamente em instantes. Para verificar o status atual:
        <br><code style="background: #f1f3f4; padding: 4px 8px; border-radius: 4px; display: inline-block; margin-top: 6px;">ssh talos "sudo systemctl status flights-watcher"</code>
      </p>
    </div>
    <div style="padding: 12px; text-align: center; font-size: 11px; color: #888; background: #fafafa; border-top: 1px solid #f0f0f0;">
      Enviado automaticamente pelo flights-watcher.
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

        return self._send_message(msg, recipient=self.email_to, log_label="Alerta de encerramento (Shutdown)")

    def _send_message(self, msg: MIMEMultipart, recipient: str, log_label: str) -> bool:
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
            logger.info(f"{log_label} enviada com sucesso para {recipient}!")
            return True
        except Exception as e:
            logger.error(f"Falha ao enviar {log_label.lower()}: {e}")
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

        return self._send_telegram(msg)

    def send_error_alert(self, error_message: str, context: str | None = None) -> bool:
        if not self.is_configured:
            return False

        ctx_text = f"📍 *Contexto:* `{context}`\n" if context else ""
        msg = (
            f"🚨 *FALHA NO MONITOR DE VOOS!*\n\n"
            f"{ctx_text}"
            f"⚠️ *Erro:* ```\n{error_message[:400]}\n```\n"
            f"Verifique o status do serviço no servidor."
        )
        return self._send_telegram(msg)

    def send_heartbeat_alert(self, stats: dict) -> bool:
        if not self.is_configured:
            return False
        uptime = stats.get("uptime", "Ativo")
        total_prices = stats.get("total_prices", 0)
        lowest = stats.get("lowest_prices", [])
        text = (
            f"💚 *[Flights Watcher] Relatório Semanal de Saúde*\n\n"
            f"O monitor 24/7 está rodando normalmente no servidor!\n\n"
            f"⏱ *Uptime:* {uptime}\n"
            f"📊 *Rotas ativas:* {len(lowest)}\n"
            f"📈 *Total de cotações:* {total_prices}\n"
        )
        if lowest:
            text += "\n*Menores Preços:* \n"
            for item in lowest[:5]:
                ret = f" ➔ {item['return_date']}" if item.get('return_date') else ""
                text += f"• `{item['origin']} ➔ {item['destination']}` ({item['departure_date']}{ret}): *{item['currency']} {item['min_price']:.2f}*\n"
        return self._send_telegram(text)

    def send_shutdown_alert(self, reason: str, uptime_str: str) -> bool:
        if not self.is_configured:
            return False
        text = (
            f"⚠️ *[Flights Watcher] Processo Encerrando*\n\n"
            f"O monitor foi interrompido ou reiniciado.\n\n"
            f"🛑 *Motivo:* `{reason}`\n"
            f"⏱ *Uptime acumulado:* {uptime_str}\n\n"
            f"Para checar o status:\n`ssh talos 'sudo systemctl status flights-watcher'`"
        )
        return self._send_telegram(text)

    def _send_telegram(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                logger.info(f"Mensagem Telegram enviada com sucesso para chat {self.chat_id}!")
                return True
        except Exception as e:
            logger.error(f"Falha ao enviar mensagem no Telegram: {e}")
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

    def send_error_alert(self, error_message: str, context: str | None = None) -> bool:
        success = False
        for notifier in self.notifiers:
            try:
                res = notifier.send_error_alert(error_message, context)
                if res:
                    success = True
            except Exception as e:
                logger.error(f"Erro ao enviar alerta de erro no {type(notifier).__name__}: {e}")
        return success

    def send_heartbeat_alert(self, stats: dict) -> bool:
        success = False
        for notifier in self.notifiers:
            try:
                res = notifier.send_heartbeat_alert(stats)
                if res:
                    success = True
            except Exception as e:
                logger.error(f"Erro ao enviar heartbeat no {type(notifier).__name__}: {e}")
        return success

    def send_shutdown_alert(self, reason: str, uptime_str: str) -> bool:
        success = False
        for notifier in self.notifiers:
            try:
                res = notifier.send_shutdown_alert(reason, uptime_str)
                if res:
                    success = True
            except Exception as e:
                logger.error(f"Erro ao enviar alerta de shutdown no {type(notifier).__name__}: {e}")
        return success
