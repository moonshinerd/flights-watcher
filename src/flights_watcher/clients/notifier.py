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

    def send_split_deal_alert(self, combo: dict) -> bool:
        """Envia alerta de combinação de trechos avulsos (Ida + Volta) abaixo da meta."""
        return False

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

    def send_split_deal_alert(self, combo: dict) -> bool:
        savings_info = f" | Economia vs Pacote: {combo['currency']} {combo['savings']:.2f}" if combo.get('savings') and combo['savings'] > 0 else ""
        logger.success(
            f"\n{'='*50}\n"
            f"🎯 ALERTA DE VIAGEM COMBINADA (TRECHOS AVULSOS)!\n"
            f"Preço Total: {combo['currency']} {combo['total_price']:.2f} (Meta: {combo['currency']} {combo['target_price']:.2f}{savings_info})\n"
            f"Ida: {combo['outbound_origin']} ➔ {combo['outbound_destination']} em {combo['departure_date']} ({combo['outbound_airline']}) - {combo['currency']} {combo['outbound_price']:.2f}\n"
            f"Volta: {combo['inbound_origin']} ➔ {combo['inbound_destination']} em {combo['return_date']} ({combo['inbound_airline']}) - {combo['currency']} {combo['inbound_price']:.2f}\n"
            f"Link Ida: {combo['outbound_url']}\n"
            f"Link Volta: {combo['inbound_url']}\n"
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

    def send_split_deal_alert(self, combo: dict) -> bool:
        if not self.is_configured:
            logger.debug("EmailNotifier não configurado para envio de split deal.")
            return False

        subject = (
            f"✈️ Alerta: Ida e Volta Avulsas por {combo['currency']} {combo['total_price']:.2f} "
            f"(Meta: {combo['currency']} {combo['target_price']:.2f})"
        )

        savings_plain = (
            f"Economia: {combo['currency']} {combo['savings']:.2f} mais barato que o pacote fechado!\n"
            if combo.get('savings') and combo['savings'] > 0
            else ""
        )

        plain_text = (
            f"Alerta de Viagem Combinada (Trechos Avulsos)!\n\n"
            f"Preço Total: {combo['currency']} {combo['total_price']:.2f} (Meta: {combo['currency']} {combo['target_price']:.2f})\n"
            f"{savings_plain}\n"
            f"1. VOO DE IDA:\n"
            f"Rota: {combo['outbound_origin']} ➔ {combo['outbound_destination']}\n"
            f"Data: {combo['departure_date']}\n"
            f"Companhia: {combo['outbound_airline']}\n"
            f"Preço: {combo['currency']} {combo['outbound_price']:.2f}\n"
            f"Link: {combo['outbound_url']}\n\n"
            f"2. VOO DE VOLTA:\n"
            f"Rota: {combo['inbound_origin']} ➔ {combo['inbound_destination']}\n"
            f"Data: {combo['return_date']}\n"
            f"Companhia: {combo['inbound_airline']}\n"
            f"Preço: {combo['currency']} {combo['inbound_price']:.2f}\n"
            f"Link: {combo['inbound_url']}\n"
        )

        savings_banner = ""
        if combo.get("savings") and combo["savings"] > 0:
            savings_banner = f"""
            <div style="background: #e6f4ea; border: 1px solid #ceead6; border-radius: 8px; padding: 12px; margin-top: 12px; font-size: 14px; color: #137333; font-weight: 700;">
              🔥 Economia de {combo['currency']} {combo['savings']:.2f} em relação ao pacote fechado ({combo['currency']} {combo['round_trip_min_price']:.2f})!
            </div>
            """

        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px;">
  <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
    <div style="background: #1a73e8; color: #ffffff; padding: 20px; text-align: center;">
      <h2 style="margin: 0; font-size: 20px;">✈️ Viagem Avulsa Abaixo da Meta Encontrada!</h2>
    </div>
    <div style="padding: 24px;">
      <div style="background: #e6f4ea; border: 1px solid #ceead6; border-radius: 8px; padding: 16px; text-align: center; margin-bottom: 20px;">
        <div style="font-size: 28px; font-weight: bold; color: #137333;">{combo['currency']} {combo['total_price']:.2f}</div>
        <div style="font-size: 13px; color: #5f6368; margin-top: 4px;">Sua meta era {combo['currency']} {combo['target_price']:.2f}</div>
        {savings_banner}
      </div>

      <h3 style="font-size: 15px; color: #202124; margin: 18px 0 8px 0;">🛫 1. Trecho de Ida</h3>
      <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 12px; background: #f8f9fa; border-radius: 6px; padding: 8px;">
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 12px; color: #666;">Rota:</td>
          <td style="padding: 8px 12px; font-weight: bold; text-align: right;">{combo['outbound_origin']} ➔ {combo['outbound_destination']}</td>
        </tr>
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 12px; color: #666;">Data:</td>
          <td style="padding: 8px 12px; font-weight: bold; text-align: right;">{combo['departure_date']}</td>
        </tr>
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 12px; color: #666;">Companhia:</td>
          <td style="padding: 8px 12px; font-weight: bold; text-align: right;">{combo['outbound_airline']}</td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; color: #666;">Preço:</td>
          <td style="padding: 8px 12px; font-weight: bold; color: #137333; text-align: right;">{combo['currency']} {combo['outbound_price']:.2f}</td>
        </tr>
      </table>
      <div style="text-align: center; margin-bottom: 20px;">
        <a href="{combo['outbound_url']}" target="_blank" style="background-color: #1a73e8; color: #ffffff; padding: 10px 18px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px; display: inline-block;">1. Comprar Ida no Google Flights ↗</a>
      </div>

      <h3 style="font-size: 15px; color: #202124; margin: 18px 0 8px 0;">🛬 2. Trecho de Volta</h3>
      <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 12px; background: #f8f9fa; border-radius: 6px; padding: 8px;">
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 12px; color: #666;">Rota:</td>
          <td style="padding: 8px 12px; font-weight: bold; text-align: right;">{combo['inbound_origin']} ➔ {combo['inbound_destination']}</td>
        </tr>
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 12px; color: #666;">Data:</td>
          <td style="padding: 8px 12px; font-weight: bold; text-align: right;">{combo['return_date']}</td>
        </tr>
        <tr style="border-bottom: 1px solid #eee;">
          <td style="padding: 8px 12px; color: #666;">Companhia:</td>
          <td style="padding: 8px 12px; font-weight: bold; text-align: right;">{combo['inbound_airline']}</td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; color: #666;">Preço:</td>
          <td style="padding: 8px 12px; font-weight: bold; color: #137333; text-align: right;">{combo['currency']} {combo['inbound_price']:.2f}</td>
        </tr>
      </table>
      <div style="text-align: center; margin-bottom: 20px;">
        <a href="{combo['inbound_url']}" target="_blank" style="background-color: #7c3aed; color: #ffffff; padding: 10px 18px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px; display: inline-block;">2. Comprar Volta no Google Flights ↗</a>
      </div>
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

        return self._send_message(msg, recipient=self.email_to, log_label="Alerta de viagem avulsa por e-mail")


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
        routes_matrix = stats.get("routes_matrix", [])
        split_combinations = stats.get("split_combinations", [])
        total_routes = stats.get("total_configured_routes", len(routes_matrix) or len(lowest_prices))

        subject = "💚 [Flights Watcher] Relatório Semanal de Saúde - Sistema 100% Operacional"

        # Combinações de trechos avulsos (Split-Ticket) agrupadas por par de datas
        best_date_combos_map: dict[tuple[str, str], dict] = {}
        for c in split_combinations:
            key = (c["departure_date"], c["return_date"])
            if key not in best_date_combos_map:
                best_date_combos_map[key] = c
            else:
                curr = best_date_combos_map[key]
                if c["total_price"] is not None and (curr["total_price"] is None or c["total_price"] < curr["total_price"]):
                    best_date_combos_map[key] = c

        best_date_combos = list(best_date_combos_map.values())
        best_date_combos.sort(
            key=lambda c: (
                0 if c["total_price"] is not None else 1,
                c["total_price"] if c["total_price"] is not None else 999999,
                c["departure_date"],
                c["return_date"],
            )
        )
        best_overall_combo = best_date_combos[0] if best_date_combos and best_date_combos[0]["total_price"] is not None else None

        if routes_matrix:
            round_trips = [r for r in routes_matrix if r["trip_type"] == "Ida e Volta"]
            one_way_out = [r for r in routes_matrix if r["trip_type"] == "Ida"]
            one_way_in = [r for r in routes_matrix if r["trip_type"] == "Volta"]

            def render_table_rows(items):
                html = ""
                for it in items:
                    dates = f"{it['departure_date']}" + (f" ➔ {it['return_date']}" if it.get('return_date') else "")
                    target_str = f"{it['currency']} {it['target_price']:.2f}"
                    url = it.get("url", "#")
                    if it['min_price'] is not None:
                        price_str = f"<strong style='color: #059669;'>{it['currency']} {it['min_price']:.2f}</strong>"
                        cia_str = it['airline']
                    else:
                        price_str = "<span style='color: #9ca3af; font-size: 12px;'>Aguardando abertura</span>"
                        cia_str = "<span style='color: #d1d5db;'>-</span>"

                    badge_bg = "#ecfdf5" if "Abaixo" in it['status'] else ("#fffbeb" if "Acima" in it['status'] else "#f3f4f6")
                    badge_color = "#047857" if "Abaixo" in it['status'] else ("#b45309" if "Acima" in it['status'] else "#6b7280")
                    status_badge = f"<span style='background: {badge_bg}; color: {badge_color}; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; display: inline-block;'>{it['status_badge']} {it['status']}</span>"

                    html += f"""
                    <tr style="border-bottom: 1px solid #f3f4f6;">
                      <td style="padding: 10px 12px; font-weight: 600; color: #1f2937;">
                        <a href="{url}" target="_blank" style="color: #1a73e8; text-decoration: none; font-weight: 600;">{it['origin']} ➔ {it['destination']} ↗</a>
                      </td>
                      <td style="padding: 10px 12px; color: #4b5563; font-size: 13px;">{dates}</td>
                      <td style="padding: 10px 12px; color: #4b5563; font-size: 13px;">{target_str}</td>
                      <td style="padding: 10px 12px; font-size: 13px;">{price_str}</td>
                      <td style="padding: 10px 12px; color: #6b7280; font-size: 12px;">{cia_str}</td>
                      <td style="padding: 10px 12px; text-align: center;">{status_badge}</td>
                      <td style="padding: 8px 12px; text-align: center;">
                        <a href="{url}" target="_blank" style="background-color: #1a73e8; color: #ffffff; padding: 4px 10px; border-radius: 4px; text-decoration: none; font-size: 11px; font-weight: 600; display: inline-block; white-space: nowrap;">Ver no Google Flights ↗</a>
                      </td>
                    </tr>
                    """
                return html

            def render_combo_table_rows(items):
                html = ""
                for c in items:
                    dates = f"{c['departure_date']} ➔ {c['return_date']}"
                    badge_bg = "#ecfdf5" if "Abaixo" in c['status'] else ("#fffbeb" if "Acima" in c['status'] else "#f3f4f6")
                    badge_color = "#047857" if "Abaixo" in c['status'] else ("#b45309" if "Acima" in c['status'] else "#6b7280")
                    status_badge = f"<span style='background: {badge_bg}; color: {badge_color}; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; display: inline-block;'>{c['status_badge']} {c['status']}</span>"

                    if c['total_price'] is not None:
                        price_str = f"<strong style='color: #059669; font-size: 14px;'>{c['currency']} {c['total_price']:.2f}</strong><br><span style='font-size: 11px; color: #6b7280;'>Meta: {c['currency']} {c['target_price']:.2f}</span>"
                    else:
                        price_str = "<span style='color: #9ca3af; font-size: 12px;'>Aguardando</span>"

                    if c.get('savings') and c['savings'] > 0:
                        vs_pkg = f"<span style='color: #047857; font-weight: 700;'>Economize {c['currency']} {c['savings']:.2f}</span><br><span style='font-size: 11px; color: #6b7280;'>(Pacote: {c['currency']} {c['round_trip_min_price']:.2f})</span>"
                    elif c.get('round_trip_min_price') is not None:
                        vs_pkg = f"<span style='font-size: 12px; color: #4b5563;'>Pacote: {c['currency']} {c['round_trip_min_price']:.2f}</span>"
                    else:
                        vs_pkg = "<span style='font-size: 12px; color: #9ca3af;'>-</span>"

                    out_info = f"<strong>{c['outbound_origin']} ➔ {c['outbound_destination']}</strong><br><span style='font-size: 11px; color: #6b7280;'>{c['outbound_airline']} ({c['currency']} {c['outbound_price']:.2f})</span>" if c['outbound_price'] is not None else f"{c['outbound_origin']} ➔ {c['outbound_destination']}"
                    in_info = f"<strong>{c['inbound_origin']} ➔ {c['inbound_destination']}</strong><br><span style='font-size: 11px; color: #6b7280;'>{c['inbound_airline']} ({c['currency']} {c['inbound_price']:.2f})</span>" if c['inbound_price'] is not None else f"{c['inbound_origin']} ➔ {c['inbound_destination']}"

                    html += f"""
                    <tr style="border-bottom: 1px solid #f3f4f6;">
                      <td style="padding: 10px 12px; font-weight: 600; color: #1f2937; white-space: nowrap;">{dates}</td>
                      <td style="padding: 10px 12px; font-size: 13px;">{out_info}</td>
                      <td style="padding: 10px 12px; font-size: 13px;">{in_info}</td>
                      <td style="padding: 10px 12px; font-size: 13px;">{price_str}</td>
                      <td style="padding: 10px 12px; font-size: 12px;">{vs_pkg}</td>
                      <td style="padding: 10px 12px; text-align: center;">{status_badge}</td>
                      <td style="padding: 10px 12px; text-align: center; white-space: nowrap;">
                        <a href="{c['outbound_url']}" target="_blank" style="background-color: #1a73e8; color: #ffffff; padding: 4px 8px; border-radius: 4px; text-decoration: none; font-size: 11px; font-weight: 600; display: inline-block; margin-bottom: 4px;">Ida ↗</a>
                        <br>
                        <a href="{c['inbound_url']}" target="_blank" style="background-color: #7c3aed; color: #ffffff; padding: 4px 8px; border-radius: 4px; text-decoration: none; font-size: 11px; font-weight: 600; display: inline-block;">Volta ↗</a>
                      </td>
                    </tr>
                    """
                return html

            combos_section_html = ""
            if best_date_combos:
                combos_section_html = f"""
                <h3 style="font-size: 15px; color: #111827; margin: 26px 0 10px 0; border-left: 4px solid #10b981; padding-left: 10px;">
                  ✨ 1. Melhores Combinações Ida + Volta Avulsas (Split-Ticket) — {len(best_date_combos)} Opções de Datas
                </h3>
                <div style="overflow-x: auto; margin-bottom: 20px;">
                  <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; background: #fafafa; border: 1px solid #e5e7eb; border-radius: 8px;">
                    <thead>
                      <tr style="background: #f3f4f6; color: #4b5563; font-size: 11px; text-transform: uppercase;">
                        <th style="padding: 10px 12px;">Datas</th>
                        <th style="padding: 10px 12px;">Trecho Ida</th>
                        <th style="padding: 10px 12px;">Trecho Volta</th>
                        <th style="padding: 10px 12px;">Total Avulso</th>
                        <th style="padding: 10px 12px;">vs. Pacote</th>
                        <th style="padding: 10px 12px; text-align: center;">Status</th>
                        <th style="padding: 10px 12px; text-align: center;">Links</th>
                      </tr>
                    </thead>
                    <tbody>
                      {render_combo_table_rows(best_date_combos)}
                    </tbody>
                  </table>
                </div>
                """

            body_sections_html = f"""
            {combos_section_html}

            <h3 style="font-size: 15px; color: #111827; margin: 26px 0 10px 0; border-left: 4px solid #059669; padding-left: 10px;">
              ✈️ 2. Pacotes Fechados (Ida e Volta) — {len(round_trips)} Rotas
            </h3>
            <div style="overflow-x: auto; margin-bottom: 20px;">
              <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; background: #fafafa; border: 1px solid #e5e7eb; border-radius: 8px;">
                <thead>
                  <tr style="background: #f3f4f6; color: #4b5563; font-size: 11px; text-transform: uppercase;">
                    <th style="padding: 10px 12px;">Rota</th>
                    <th style="padding: 10px 12px;">Datas</th>
                    <th style="padding: 10px 12px;">Meta</th>
                    <th style="padding: 10px 12px;">Menor Preço</th>
                    <th style="padding: 10px 12px;">Cia</th>
                    <th style="padding: 10px 12px; text-align: center;">Status</th>
                    <th style="padding: 10px 12px; text-align: center;">Link</th>
                  </tr>
                </thead>
                <tbody>
                  {render_table_rows(round_trips)}
                </tbody>
              </table>
            </div>

            <h3 style="font-size: 15px; color: #111827; margin: 26px 0 10px 0; border-left: 4px solid #3b82f6; padding-left: 10px;">
              🛫 3. Trechos Avulsos de Ida (BSB ➔ SP) — {len(one_way_out)} Rotas
            </h3>
            <div style="overflow-x: auto; margin-bottom: 20px;">
              <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; background: #fafafa; border: 1px solid #e5e7eb; border-radius: 8px;">
                <thead>
                  <tr style="background: #f3f4f6; color: #4b5563; font-size: 11px; text-transform: uppercase;">
                    <th style="padding: 10px 12px;">Rota</th>
                    <th style="padding: 10px 12px;">Data Ida</th>
                    <th style="padding: 10px 12px;">Meta</th>
                    <th style="padding: 10px 12px;">Menor Preço</th>
                    <th style="padding: 10px 12px;">Cia</th>
                    <th style="padding: 10px 12px; text-align: center;">Status</th>
                    <th style="padding: 10px 12px; text-align: center;">Link</th>
                  </tr>
                </thead>
                <tbody>
                  {render_table_rows(one_way_out)}
                </tbody>
              </table>
            </div>

            <h3 style="font-size: 15px; color: #111827; margin: 26px 0 10px 0; border-left: 4px solid #8b5cf6; padding-left: 10px;">
              🛬 4. Trechos Avulsos de Volta (SP ➔ BSB) — {len(one_way_in)} Rotas
            </h3>
            <div style="overflow-x: auto; margin-bottom: 20px;">
              <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; background: #fafafa; border: 1px solid #e5e7eb; border-radius: 8px;">
                <thead>
                  <tr style="background: #f3f4f6; color: #4b5563; font-size: 11px; text-transform: uppercase;">
                    <th style="padding: 10px 12px;">Rota</th>
                    <th style="padding: 10px 12px;">Data Volta</th>
                    <th style="padding: 10px 12px;">Meta</th>
                    <th style="padding: 10px 12px;">Menor Preço</th>
                    <th style="padding: 10px 12px;">Cia</th>
                    <th style="padding: 10px 12px; text-align: center;">Status</th>
                    <th style="padding: 10px 12px; text-align: center;">Link</th>
                  </tr>
                </thead>
                <tbody>
                  {render_table_rows(one_way_in)}
                </tbody>
              </table>
            </div>
            """
        else:
            rows_html = ""
            for lp in lowest_prices:
                dates = f"{lp['departure_date']}" + (f" ➔ {lp['return_date']}" if lp.get('return_date') else "")
                url = lp.get("google_flights_url") or "#"
                rows_html += f"""
                <tr style="border-bottom: 1px solid #e5e7eb;">
                  <td style="padding: 10px 12px; font-weight: 600; color: #1f2937;">
                    <a href="{url}" target="_blank" style="color: #1a73e8; text-decoration: none;">{lp['origin']} ➔ {lp['destination']} ↗</a>
                  </td>
                  <td style="padding: 10px 12px; color: #4b5563; font-size: 13px;">{dates}</td>
                  <td style="padding: 10px 12px; font-weight: 700; color: #059669;">{lp['currency']} {lp['min_price']:.2f}</td>
                  <td style="padding: 10px 12px; color: #6b7280; font-size: 13px;">{lp['airline']}</td>
                  <td style="padding: 8px 12px; text-align: center;">
                    <a href="{url}" target="_blank" style="background-color: #1a73e8; color: #ffffff; padding: 4px 10px; border-radius: 4px; text-decoration: none; font-size: 11px; font-weight: 600; display: inline-block;">Ver voo ↗</a>
                  </td>
                </tr>
                """
            if not rows_html:
                rows_html = "<tr><td colspan='5' style='padding: 16px; text-align: center; color: #6b7280;'>Ainda não há cotações salvas no histórico.</td></tr>"

            body_sections_html = f"""
            <h3 style="font-size: 16px; color: #111827; margin: 24px 0 12px 0;">📊 Menores Preços Históricos por Rota</h3>
            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; background: #fafafa; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
              <thead>
                <tr style="background: #f3f4f6; color: #4b5563; font-size: 12px; text-transform: uppercase;">
                  <th style="padding: 10px 12px;">Rota</th>
                  <th style="padding: 10px 12px;">Datas</th>
                  <th style="padding: 10px 12px;">Menor Preço</th>
                  <th style="padding: 10px 12px;">Cia</th>
                  <th style="padding: 10px 12px; text-align: center;">Link</th>
                </tr>
              </thead>
              <tbody>
                {rows_html}
              </tbody>
            </table>
            """

        best_combo_card = ""
        if best_overall_combo:
            savings_tag = ""
            if best_overall_combo.get("savings") and best_overall_combo["savings"] > 0:
                savings_tag = f"<span style='background: #d1fae5; color: #065f46; font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 4px; margin-left: 8px;'>Economia de {best_overall_combo['currency']} {best_overall_combo['savings']:.2f} vs Pacote Fechado!</span>"

            best_combo_card = f"""
            <div style="background: linear-gradient(135deg, #ecfdf5 0%, #f0fdf4 100%); border: 1px solid #a7f3d0; border-radius: 10px; padding: 16px 20px; margin: 18px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">
              <div style="font-size: 12px; font-weight: 700; color: #047857; text-transform: uppercase; letter-spacing: 0.5px;">✨ Menor Viagem Encontrada (Ida + Volta Avulsas)</div>
              <div style="font-size: 24px; font-weight: 800; color: #065f46; margin: 6px 0;">
                {best_overall_combo['currency']} {best_overall_combo['total_price']:.2f}
                {savings_tag}
              </div>
              <div style="font-size: 13px; color: #374151; margin-bottom: 12px; line-height: 1.5;">
                <strong>Ida:</strong> {best_overall_combo['outbound_origin']} ➔ {best_overall_combo['outbound_destination']} ({best_overall_combo['departure_date']} · {best_overall_combo['outbound_airline']} por {best_overall_combo['currency']} {best_overall_combo['outbound_price']:.2f})<br>
                <strong>Volta:</strong> {best_overall_combo['inbound_origin']} ➔ {best_overall_combo['inbound_destination']} ({best_overall_combo['return_date']} · {best_overall_combo['inbound_airline']} por {best_overall_combo['currency']} {best_overall_combo['inbound_price']:.2f})
              </div>
              <div>
                <a href="{best_overall_combo['outbound_url']}" target="_blank" style="background-color: #1a73e8; color: #ffffff; padding: 8px 14px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 700; display: inline-block; margin-right: 8px;">1. Comprar Ida no Google Flights ↗</a>
                <a href="{best_overall_combo['inbound_url']}" target="_blank" style="background-color: #7c3aed; color: #ffffff; padding: 8px 14px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 700; display: inline-block;">2. Comprar Volta no Google Flights ↗</a>
              </div>
            </div>
            """

        combo_text = ""
        if best_overall_combo:
            combo_text = (
                f"\n✨ Menor Viagem Encontrada (Ida + Volta Avulsas):\n"
                f"• Total: {best_overall_combo['currency']} {best_overall_combo['total_price']:.2f} (Meta: {best_overall_combo['currency']} {best_overall_combo['target_price']:.2f})\n"
                f"• Ida: {best_overall_combo['outbound_origin']} ➔ {best_overall_combo['outbound_destination']} em {best_overall_combo['departure_date']} ({best_overall_combo['outbound_airline']}) - Link: {best_overall_combo['outbound_url']}\n"
                f"• Volta: {best_overall_combo['inbound_origin']} ➔ {best_overall_combo['inbound_destination']} em {best_overall_combo['return_date']} ({best_overall_combo['inbound_airline']}) - Link: {best_overall_combo['inbound_url']}\n"
            )

        plain_text = (
            f"💚 RELATÓRIO SEMANAL DE SAÚDE - FLIGHTS WATCHER\n\n"
            f"O monitor 24/7 está rodando normalmente no servidor talos e vigiando suas passagens!\n\n"
            f"• Uptime: {uptime}\n"
            f"• Total de cotações gravadas: {total_prices}\n"
            f"• Total de alertas enviados: {total_notifications}\n"
            f"• Rotas configuradas ativas: {total_routes}\n"
            f"{combo_text}\n"
            f"Para checar os logs completos:\n"
            f"ssh talos 'journalctl --user -u flights-watcher -n 50 --no-pager'\n"
        )

        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; margin: 0; padding: 20px;">
  <div style="max-width: 720px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.06); border: 1px solid #e5e7eb;">
    <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #ffffff; padding: 24px; text-align: center;">
      <h2 style="margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.5px;">💚 Monitor 24/7 Ativo e Saudável</h2>
      <p style="margin: 6px 0 0 0; opacity: 0.92; font-size: 14px;">Relatório Periódico de Integridade & Matriz de Rotas</p>
    </div>
    <div style="padding: 24px;">
      <p style="color: #374151; font-size: 15px; line-height: 1.5; margin-top: 0;">
        Olá! Este é o seu relatório semanal automático confirmando que o <strong>Flights Watcher</strong> continua ativo e vigiando todas as opções de voo para The Town 2027.
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
            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #86198f;">Rotas Ativas</div>
            <div style="font-size: 16px; font-weight: 800; color: #a21caf; margin-top: 4px;">{total_routes}</div>
          </td>
        </tr>
      </table>

      {best_combo_card}

      {body_sections_html}

      <div style="margin-top: 24px; padding: 14px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb; font-size: 13px; color: #4b5563;">
        🔍 <strong>Diagnóstico rápido:</strong> Para inspecionar o serviço no servidor talos:
        <br><code style="background: #e5e7eb; padding: 3px 6px; border-radius: 4px; display: inline-block; margin-top: 6px; font-family: monospace;">ssh talos 'journalctl --user -u flights-watcher -n 50 --no-pager'</code>
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

    def send_split_deal_alert(self, combo: dict) -> bool:
        if not self.is_configured:
            return False

        savings_text = ""
        if combo.get("savings") and combo["savings"] > 0:
            savings_text = f"🔥 *Economia:* `{combo['currency']} {combo['savings']:.2f}` mais barato que o pacote fechado!\n\n"

        msg = (
            f"✈️ *ALERTA: VIAGEM COMBINADA (TRECHOS AVULSOS)!*\n\n"
            f"💰 *Preço Total Combinado:* `{combo['currency']} {combo['total_price']:.2f}`\n"
            f"🎯 *Sua Meta:* `{combo['currency']} {combo['target_price']:.2f}`\n"
            f"{savings_text}"
            f"🛫 *Trecho Ida:*\n"
            f"📍 `{combo['outbound_origin']} ➔ {combo['outbound_destination']}`\n"
            f"📅 `{combo['departure_date']}` | 🏢 {combo['outbound_airline']}\n"
            f"💵 `{combo['currency']} {combo['outbound_price']:.2f}`\n"
            f"🔗 [Comprar Ida no Google Flights]({combo['outbound_url']})\n\n"
            f"🛬 *Trecho Volta:*\n"
            f"📍 `{combo['inbound_origin']} ➔ {combo['inbound_destination']}`\n"
            f"📅 `{combo['return_date']}` | 🏢 {combo['inbound_airline']}\n"
            f"💵 `{combo['currency']} {combo['inbound_price']:.2f}`\n"
            f"🔗 [Comprar Volta no Google Flights]({combo['inbound_url']})\n"
        )
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
        split_combos = stats.get("split_combinations", [])
        best_combo = next((c for c in split_combos if c.get("total_price") is not None), None)

        text = (
            f"💚 *[Flights Watcher] Relatório Semanal de Saúde*\n\n"
            f"O monitor 24/7 está rodando normalmente no servidor!\n\n"
            f"⏱ *Uptime:* {uptime}\n"
            f"📊 *Rotas ativas:* {len(lowest)}\n"
            f"📈 *Total de cotações:* {total_prices}\n"
        )
        if best_combo:
            savings_info = f" (Economia: *{best_combo['currency']} {best_combo['savings']:.2f}*)" if best_combo.get('savings') and best_combo['savings'] > 0 else ""
            text += (
                f"\n✨ *Menor Viagem (Ida + Volta Avulsas):*\n"
                f"• `{best_combo['outbound_origin']} ➔ {best_combo['outbound_destination']}` ({best_combo['departure_date']}) + "
                f"`{best_combo['inbound_origin']} ➔ {best_combo['inbound_destination']}` ({best_combo['return_date']})\n"
                f"• Total: *{best_combo['currency']} {best_combo['total_price']:.2f}*{savings_info}\n"
                f"• 🔗 [Comprar Ida]({best_combo['outbound_url']}) | [Comprar Volta]({best_combo['inbound_url']})\n"
            )
        if lowest:
            text += "\n*Menores Preços por Rota:* \n"
            for item in lowest[:5]:
                ret = f" ➔ {item['return_date']}" if item.get('return_date') else ""
                url_link = f" [🔗]({item['google_flights_url']})" if item.get('google_flights_url') else ""
                text += f"• `{item['origin']} ➔ {item['destination']}` ({item['departure_date']}{ret}): *{item['currency']} {item['min_price']:.2f}*{url_link}\n"
        return self._send_telegram(text)

    def send_shutdown_alert(self, reason: str, uptime_str: str) -> bool:
        if not self.is_configured:
            return False
        text = (
            f"⚠️ *[Flights Watcher] Processo Encerrando*\n\n"
            f"O monitor foi interrompido ou reiniciado.\n\n"
            f"🛑 *Motivo:* `{reason}`\n"
            f"⏱ *Uptime acumulado:* {uptime_str}\n\n"
            f"Para checar o status:\n`ssh talos 'journalctl --user -u flights-watcher -n 50 --no-pager'`"
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

    def send_split_deal_alert(self, combo: dict) -> bool:
        success = False
        for notifier in self.notifiers:
            try:
                res = notifier.send_split_deal_alert(combo)
                if res:
                    success = True
            except Exception as e:
                logger.error(f"Erro ao enviar alerta de split deal no {type(notifier).__name__}: {e}")
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

