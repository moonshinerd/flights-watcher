from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from loguru import logger

from flights_watcher.domain.models import FlightDeal


class FlightRepository:
    """Repositório SQLite para histórico de preços e controle de alertas."""

    def __init__(self, db_path: Path | str = "flights_watcher.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Cria as tabelas necessárias se não existirem."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    return_date TEXT,
                    price REAL NOT NULL,
                    currency TEXT NOT NULL,
                    airline TEXT,
                    stops INTEGER,
                    google_flights_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_id TEXT NOT NULL,
                    price REAL NOT NULL,
                    currency TEXT NOT NULL,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_price_history_route
                ON price_history(route_id, created_at);
                """
            )
            conn.commit()

    def save_deal(self, deal: FlightDeal) -> None:
        """Registra uma cotação no histórico de preços."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO price_history (
                    route_id, origin, destination, departure_date, return_date,
                    price, currency, airline, stops, google_flights_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deal.route_id,
                    deal.origin,
                    deal.destination,
                    deal.departure_date,
                    deal.return_date,
                    deal.price,
                    deal.currency,
                    deal.airline,
                    deal.stops,
                    deal.google_flights_url,
                    deal.checked_at.isoformat(),
                ),
            )
            conn.commit()

    def record_notification(self, deal: FlightDeal) -> None:
        """Registra que um alerta foi enviado para evitar notificações repetidas."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO notifications (route_id, price, currency, notified_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    deal.route_id,
                    deal.price,
                    deal.currency,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def should_notify(
        self, deal: FlightDeal, target_price: float, cooldown_hours: int = 12
    ) -> bool:
        """Verifica se o alerta deve ser disparado para este voo."""
        # Se o preço não está abaixo ou igual à meta, não notifica
        if deal.price > target_price:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Buscar a última notificação para essa rota
            cursor.execute(
                """
                SELECT price, notified_at FROM notifications
                WHERE route_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (deal.route_id,),
            )
            row = cursor.fetchone()

            if not row:
                # Primeira vez que encontra abaixo da meta: dispara!
                return True

            last_notified_price = float(row["price"])
            last_notified_time = datetime.fromisoformat(row["notified_at"])

            # Se o preço caiu ainda mais do que o último notificado, notifica!
            if deal.price < last_notified_price:
                logger.info(
                    f"Preço caiu ainda mais ({deal.currency} {deal.price} < {last_notified_price})! Notificando..."
                )
                return True

            # Se já passou o cooldown (ex: 12 horas) e o preço continua bom, notifica novamente
            if datetime.now() - last_notified_time > timedelta(hours=cooldown_hours):
                logger.info(
                    f"Cooldown de {cooldown_hours}h expirou e o preço continua abaixo da meta! Relembrando..."
                )
                return True

            logger.debug(
                f"Alerta suprimido para rota {deal.route_id}: já notificado recentemente a {last_notified_price}."
            )
            return False

    def get_lowest_historical_price(self, route_id: str) -> float | None:
        """Retorna o menor preço histórico já registrado para uma rota."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MIN(price) as min_price FROM price_history WHERE route_id = ?",
                (route_id,),
            )
            row = cursor.fetchone()
            if row and row["min_price"] is not None:
                return float(row["min_price"])
            return None

    def get_metadata(self, key: str) -> str | None:
        """Obtém um valor de configuração persistente ou timestamp do banco."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        """Define ou atualiza um valor de configuração persistente no banco."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO metadata (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def get_stats(self) -> dict:
        """Retorna estatísticas consolidadas para relatórios periódicos de saúde."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM price_history")
            total_prices = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM notifications")
            total_notifications = cursor.fetchone()["count"]

            cursor.execute(
                """
                SELECT route_id, origin, destination, departure_date, return_date, currency,
                       MIN(price) as min_price, airline
                FROM price_history
                GROUP BY route_id
                ORDER BY min_price ASC
                """
            )
            lowest_prices = [
                {
                    "route_id": row["route_id"],
                    "origin": row["origin"],
                    "destination": row["destination"],
                    "departure_date": row["departure_date"],
                    "return_date": row["return_date"],
                    "currency": row["currency"],
                    "min_price": float(row["min_price"]),
                    "airline": row["airline"] or "-",
                }
                for row in cursor.fetchall()
            ]

            return {
                "total_prices": total_prices,
                "total_notifications": total_notifications,
                "lowest_prices": lowest_prices,
            }

    def get_route_price_summary(self) -> dict[str, dict]:
        """Retorna resumo do menor preço histórico, companhia e url para cada route_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.route_id, p.price as min_price, p.currency, p.airline, p.google_flights_url, counts.checks_count
                FROM price_history p
                INNER JOIN (
                    SELECT route_id, MIN(price) as min_price, COUNT(*) as checks_count
                    FROM price_history
                    GROUP BY route_id
                ) counts ON p.route_id = counts.route_id AND p.price = counts.min_price
                GROUP BY p.route_id
                """
            )
            summary = {}
            for row in cursor.fetchall():
                summary[row["route_id"]] = {
                    "min_price": float(row["min_price"]) if row["min_price"] is not None else None,
                    "currency": row["currency"],
                    "airline": row["airline"] or "-",
                    "google_flights_url": row["google_flights_url"],
                    "checks_count": row["checks_count"],
                }
            return summary

    def should_notify_combo(
        self, combo_id: str, total_price: float, target_price: float, cooldown_hours: int = 12
    ) -> bool:
        """Verifica se o alerta de oferta combinada (Split-Ticket) deve ser disparado."""
        if total_price > target_price:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT price, notified_at FROM notifications
                WHERE route_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (combo_id,),
            )
            row = cursor.fetchone()

            if not row:
                return True

            last_notified_price = float(row["price"])
            last_notified_time = datetime.fromisoformat(row["notified_at"])

            if total_price < last_notified_price:
                logger.info(
                    f"Preço do combo {combo_id} caiu ainda mais ({total_price} < {last_notified_price})! Notificando..."
                )
                return True

            if datetime.now() - last_notified_time > timedelta(hours=cooldown_hours):
                logger.info(
                    f"Cooldown de {cooldown_hours}h expirou para combo {combo_id}! Relembrando..."
                )
                return True

            logger.debug(
                f"Alerta suprimido para combo {combo_id}: já notificado recentemente a {last_notified_price}."
            )
            return False

    def record_combo_notification(
        self, combo_id: str, total_price: float, currency: str = "BRL"
    ) -> None:
        """Registra notificação enviada para oferta combinada."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO notifications (route_id, price, currency, notified_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    combo_id,
                    total_price,
                    currency,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

