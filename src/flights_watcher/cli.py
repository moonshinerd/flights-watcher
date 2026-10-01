from typing import Annotated
import typer
from rich.console import Console
from rich.table import Table

from flights_watcher.clients.flights_client import FlightSearchClient
from flights_watcher.clients.notifier import EmailNotifier, TelegramNotifier
from flights_watcher.config import settings
from flights_watcher.domain.models import FlightDeal, RouteConfig
from flights_watcher.services.monitor import MonitorService
from flights_watcher.storage.repository import FlightRepository

app = typer.Typer(
    name="flight-monitor",
    help="Monitor 24/7 de passagens aéreas e alertas automáticos",
    add_completion=False,
)
console = Console()


@app.command()
def check() -> None:
    """Executa uma única rodada de verificação em todas as rotas configuradas."""
    service = MonitorService()
    results = service.run_once()
    console.print(f"\n[bold green]✓ Verificação concluída. {len(results)} rota(s) processada(s).[/bold green]")


@app.command()
def start() -> None:
    """Inicia o monitor 24/7 em segundo plano/daemon contínuo."""
    service = MonitorService()
    service.run_forever()


@app.command()
def search(
    origin: Annotated[str, typer.Argument(help="Código IATA de origem (ex: GRU)")],
    destination: Annotated[str, typer.Argument(help="Código IATA de destino (ex: GIG)")],
    departure_date: Annotated[str, typer.Argument(help="Data de ida YYYY-MM-DD")],
    return_date: Annotated[str | None, typer.Option("--return", "-r", help="Data de volta YYYY-MM-DD")] = None,
    target_price: Annotated[float, typer.Option("--target", "-t", help="Preço desejado")] = 999999.0,
    currency: Annotated[str, typer.Option("--currency", "-c", help="Moeda (BRL, USD)")] = "BRL",
    airlines: Annotated[list[str] | None, typer.Option("--airlines", "-a", help="Códigos IATA de companhias para filtrar (ex: G3, LA, AD)")] = None,
    exclude_airlines: Annotated[list[str] | None, typer.Option("--exclude-airlines", "-A", help="Códigos IATA para excluir")] = None,
) -> None:
    """Pesquisa rápida de uma rota avulsa no Google Flights."""
    route = RouteConfig(
        id=f"{origin}-{destination}-custom",
        origin=origin.upper(),
        destination=destination.upper(),
        departure_date=departure_date,
        return_date=return_date,
        target_price=target_price,
        currency=currency.upper(),
        airlines=[a.upper() for a in airlines] if airlines else None,
        exclude_airlines=[a.upper() for a in exclude_airlines] if exclude_airlines else None,
    )

    client = FlightSearchClient()
    deals = client.search_route(route)

    if not deals:
        console.print("[yellow]Nenhum voo encontrado para os filtros selecionados.[/yellow]")
        return

    table = Table(title=f"Voos: {route.origin} ➔ {route.destination} ({route.departure_date})")
    table.add_column("Preço", style="bold green")
    table.add_column("Companhia", style="cyan")
    table.add_column("Escalas", justify="center")
    table.add_column("Ida", style="magenta")
    table.add_column("Volta", style="magenta")

    for deal in deals[:5]:
        ret_info = f"{deal.return_departure} -> {deal.return_arrival}" if deal.return_departure else "-"
        table.add_row(
            f"{deal.currency} {deal.price:.2f}",
            deal.airline,
            str(deal.stops),
            f"{deal.outbound_departure} -> {deal.outbound_arrival}",
            ret_info,
        )

    console.print(table)


@app.command()
def test_alert(
    channel: str = typer.Option(
        "all", "--channel", "-c", help="Canal de notificação: 'email', 'telegram' ou 'all'"
    ),
) -> None:
    """Envia um alerta de teste para validar a integração de e-mail ou Telegram."""
    email_notifier = EmailNotifier()
    telegram_notifier = TelegramNotifier()

    fake_route = RouteConfig(
        id="bsb-cgh-teste",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        target_price=550.0,
    )
    fake_deal = FlightDeal(
        route_id=fake_route.id,
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        price=450.0,
        currency="BRL",
        airline="LATAM Airlines",
        stops=0,
        outbound_departure="08:30",
        outbound_arrival="10:15",
        return_departure="18:00",
        return_arrival="19:45",
        total_duration_minutes=105,
        google_flights_url="https://www.google.com/travel/flights",
    )

    if channel in ("all", "email"):
        if email_notifier.is_configured:
            console.print(f"Enviando e-mail de teste para [cyan]{email_notifier.email_to}[/cyan]...")
            if email_notifier.send_deal_alert(fake_route, fake_deal):
                console.print(f"[bold green]✓ E-mail enviado com sucesso para {email_notifier.email_to}![/bold green]")
            else:
                console.print("[bold red]✗ Falha ao enviar e-mail de teste.[/bold red]")
        else:
            console.print("[yellow]⚠ E-mail não configurado no .env (SMTP_USER/PASSWORD ausentes).[/yellow]")

    if channel in ("all", "telegram"):
        if telegram_notifier.is_configured:
            console.print(f"Enviando Telegram de teste para chat [cyan]{telegram_notifier.chat_id}[/cyan]...")
            if telegram_notifier.send_deal_alert(fake_route, fake_deal):
                console.print("[bold green]✓ Notificação enviada para o Telegram![/bold green]")
            else:
                console.print("[bold red]✗ Falha ao enviar notificação no Telegram.[/bold red]")
        elif channel == "telegram":
            console.print("[bold red]✗ Telegram não configurado no .env.[/bold red]")


@app.command()
def history() -> None:
    """Exibe o histórico recente de preços salvos no banco SQLite."""
    repo = FlightRepository(settings.DATABASE_PATH)
    with repo._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT route_id, origin, destination, departure_date, return_date, price, currency, airline, created_at
            FROM price_history
            ORDER BY id DESC LIMIT 15
            """
        )
        rows = cursor.fetchall()

    if not rows:
        console.print("[yellow]Nenhum histórico registrado ainda.[/yellow]")
        return

    table = Table(title="Histórico Recente de Cotações (SQLite)")
    table.add_column("Data/Hora", style="dim")
    table.add_column("Rota", style="cyan")
    table.add_column("Datas", style="magenta")
    table.add_column("Preço", style="bold green")
    table.add_column("Companhia")

    for r in rows:
        dates = f"{r['departure_date']}" + (f" ➔ {r['return_date']}" if r['return_date'] else "")
        table.add_row(
            str(r["created_at"]),
            f"{r['origin']} ➔ {r['destination']}",
            dates,
            f"{r['currency']} {r['price']:.2f}",
            str(r["airline"] or "-"),
        )

    console.print(table)


if __name__ == "__main__":
    app()
