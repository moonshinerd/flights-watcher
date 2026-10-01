from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações da aplicação carregadas via variáveis de ambiente ou .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    # Rotas e Persistência
    DATABASE_PATH: Path = Path("flight_monitor.db")
    ROUTES_FILE: Path = Path("routes.json")

    # Parâmetros de execução
    CHECK_INTERVAL_MINUTES: int = 60
    NOTIFICATION_COOLDOWN_HOURS: int = 12
    DEFAULT_CURRENCY: str = "BRL"


settings = Settings()
