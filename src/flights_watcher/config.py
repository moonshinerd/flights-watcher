from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações da aplicação carregadas via variáveis de ambiente ou .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Email / SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 465
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    ALERT_EMAIL_TO: str | None = None

    # Compatibilidade com formatos legados de .env
    EMAIL: str | None = None
    SENHA_APP_EMAIL: str | None = None

    # Telegram
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    # Rotas e Persistência
    DATABASE_PATH: Path = Path("flights_watcher.db")
    ROUTES_FILE: Path = Path("routes.json")

    # Parâmetros de execução
    CHECK_INTERVAL_MINUTES: int = 60
    NOTIFICATION_COOLDOWN_HOURS: int = 12
    DEFAULT_CURRENCY: str = "BRL"

    @property
    def email_user(self) -> str | None:
        return self.SMTP_USER or self.EMAIL

    @property
    def email_password(self) -> str | None:
        return self.SMTP_PASSWORD or self.SENHA_APP_EMAIL

    @property
    def email_to(self) -> str | None:
        return self.ALERT_EMAIL_TO or self.email_user


settings = Settings()
