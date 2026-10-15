from unittest.mock import MagicMock, patch
import pytest
from typer.testing import CliRunner
from flights_watcher.cli import app
from flights_watcher.domain.models import FlightDeal

runner = CliRunner()


@pytest.fixture
def mock_deal():
    return FlightDeal(
        route_id="bsb-cgh",
        origin="BSB",
        destination="CGH",
        departure_date="2027-09-03",
        return_date="2027-09-06",
        price=480.0,
        currency="BRL",
        airline="LATAM",
        stops=0,
        outbound_departure="08:00",
        outbound_arrival="09:45",
        return_departure="18:00",
        return_arrival="19:45",
        total_duration_minutes=105,
        google_flights_url="https://google.com",
    )


@patch("flights_watcher.cli.MonitorService")
def test_cli_check(mock_service_cls, mock_deal):
    mock_service = MagicMock()
    mock_service.run_once.return_value = [mock_deal]
    mock_service_cls.return_value = mock_service

    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "Verificação concluída" in result.stdout
    assert "1 rota(s) processada(s)" in result.stdout
    mock_service.run_once.assert_called_once()


@patch("flights_watcher.cli.MonitorService")
def test_cli_check_no_results(mock_service_cls):
    mock_service = MagicMock()
    mock_service.run_once.return_value = []
    mock_service_cls.return_value = mock_service

    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "Verificação concluída" in result.stdout
    assert "0 rota(s) processada(s)" in result.stdout


@patch("flights_watcher.cli.MonitorService")
def test_cli_start(mock_service_cls):
    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service

    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0
    mock_service.run_forever.assert_called_once()


@patch("flights_watcher.cli.FlightSearchClient")
def test_cli_search_success(mock_client_cls, mock_deal):
    mock_client = MagicMock()
    mock_client.search_route.return_value = [mock_deal]
    mock_client_cls.return_value = mock_client

    result = runner.invoke(
        app,
        ["search", "BSB", "CGH", "2027-09-03", "-r", "2027-09-06", "--currency", "BRL"],
    )
    assert result.exit_code == 0
    assert "BSB" in result.stdout
    assert "CGH" in result.stdout
    assert "480" in result.stdout


@patch("flights_watcher.cli.FlightSearchClient")
def test_cli_search_no_results(mock_client_cls):
    mock_client = MagicMock()
    mock_client.search_route.return_value = []
    mock_client_cls.return_value = mock_client

    result = runner.invoke(app, ["search", "BSB", "CGH", "2027-09-03"])
    assert result.exit_code == 0
    assert "Nenhum voo encontrado" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_deal_email(mock_telegram_cls, mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_deal_alert.return_value = True
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email"])
    assert result.exit_code == 0
    assert "E-mail enviado com sucesso" in result.stdout
    mock_email.send_deal_alert.assert_called_once()


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_deal_email_not_configured(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = False
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email"])
    assert result.exit_code == 0
    assert "E-mail não configurado" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_error_mode(mock_telegram_cls, mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_error_alert.return_value = True
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--error"])
    assert result.exit_code == 0
    assert "E-mail de erro enviado com sucesso" in result.stdout
    mock_email.send_error_alert.assert_called_once()


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_telegram_channel(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_deal_alert.return_value = True
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram"])
    assert result.exit_code == 0
    assert "Notificação enviada para o Telegram" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_telegram_not_configured(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = False
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram"])
    assert result.exit_code == 0
    assert "Telegram não configurado" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_deal_email_failure(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_deal_alert.return_value = False
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email"])
    assert result.exit_code == 0
    assert "Falha ao enviar e-mail de teste" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_error_email_failure(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_error_alert.return_value = False
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--error"])
    assert result.exit_code == 0
    assert "Falha ao enviar e-mail de erro" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_error_telegram_success(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_error_alert.return_value = True
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--error"])
    assert result.exit_code == 0
    assert "Alerta de erro enviado para o Telegram" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_error_telegram_failure(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_error_alert.return_value = False
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--error"])
    assert result.exit_code == 0
    assert "Falha ao enviar alerta de erro no Telegram" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_error_telegram_not_configured(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = False
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--error"])
    assert result.exit_code == 0
    assert "Telegram não configurado" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_deal_telegram_failure(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_deal_alert.return_value = False
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram"])
    assert result.exit_code == 0
    assert "Falha ao enviar notificação no Telegram" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_channel_all(mock_telegram_cls, mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_deal_alert.return_value = True
    mock_email_cls.return_value = mock_email

    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_deal_alert.return_value = True
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "all"])
    assert result.exit_code == 0
    mock_email.send_deal_alert.assert_called_once()
    mock_telegram.send_deal_alert.assert_called_once()


@patch("flights_watcher.cli.FlightSearchClient")
def test_cli_search_with_airlines_options(mock_client_cls, mock_deal):
    mock_client = MagicMock()
    mock_client.search_route.return_value = [mock_deal]
    mock_client_cls.return_value = mock_client

    result = runner.invoke(
        app,
        ["search", "BSB", "CGH", "2027-09-03", "-a", "LA", "-a", "G3", "-A", "AD"],
    )
    assert result.exit_code == 0
    mock_client.search_route.assert_called_once()
    route_arg = mock_client.search_route.call_args[0][0]
    assert route_arg.airlines == ["LA", "G3"]
    assert route_arg.exclude_airlines == ["AD"]


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_heartbeat_email(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_heartbeat_alert.return_value = True
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--heartbeat"])
    assert result.exit_code == 0
    assert "Relatório de saúde enviado com sucesso" in result.stdout
    mock_email.send_heartbeat_alert.assert_called_once()


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_heartbeat_email_failure(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_heartbeat_alert.return_value = False
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--heartbeat"])
    assert result.exit_code == 0
    assert "Falha ao enviar relatório de saúde" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_heartbeat_email_not_configured(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = False
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--heartbeat"])
    assert result.exit_code == 0
    assert "E-mail não configurado" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_heartbeat_telegram(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_heartbeat_alert.return_value = True
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--heartbeat"])
    assert result.exit_code == 0
    assert "Relatório de saúde enviado para o Telegram" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_heartbeat_telegram_failure(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_heartbeat_alert.return_value = False
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--heartbeat"])
    assert result.exit_code == 0
    assert "Falha ao enviar relatório no Telegram" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_shutdown_email(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_shutdown_alert.return_value = True
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--shutdown"])
    assert result.exit_code == 0
    assert "Alerta de shutdown enviado com sucesso" in result.stdout
    mock_email.send_shutdown_alert.assert_called_once()


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_shutdown_email_failure(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_shutdown_alert.return_value = False
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--shutdown"])
    assert result.exit_code == 0
    assert "Falha ao enviar alerta de shutdown" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_shutdown_telegram(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_shutdown_alert.return_value = True
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--shutdown"])
    assert result.exit_code == 0
    assert "Alerta de shutdown enviado para o Telegram" in result.stdout


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_shutdown_telegram_failure(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_shutdown_alert.return_value = False
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--shutdown"])
    assert result.exit_code == 0
    assert "Falha ao enviar alerta de shutdown no Telegram" in result.stdout


def test_cli_history_empty(tmp_path):
    with patch("flights_watcher.cli.settings") as mock_settings:
        mock_settings.DATABASE_PATH = tmp_path / "empty.db"
        result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        assert "Nenhum histórico registrado ainda" in result.stdout


def test_cli_history_with_data(tmp_path, mock_deal):
    db_path = tmp_path / "test_history.db"
    from flights_watcher.storage.repository import FlightRepository
    repo = FlightRepository(db_path)
    repo.save_deal(mock_deal)

    with patch("flights_watcher.cli.settings") as mock_settings:
        mock_settings.DATABASE_PATH = db_path
        result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        assert "Histórico Recente de Cotações" in result.stdout
        assert "BSB" in result.stdout
        assert "CGH" in result.stdout
        assert "480.00" in result.stdout


@patch("flights_watcher.cli.EmailNotifier")
def test_cli_test_alert_split_email(mock_email_cls):
    mock_email = MagicMock()
    mock_email.is_configured = True
    mock_email.email_to = "test@example.com"
    mock_email.send_split_deal_alert.return_value = True
    mock_email_cls.return_value = mock_email

    result = runner.invoke(app, ["test-alert", "--channel", "email", "--split"])
    assert result.exit_code == 0
    assert "E-mail de viagem avulsa enviado com sucesso" in result.stdout
    mock_email.send_split_deal_alert.assert_called_once()


@patch("flights_watcher.cli.TelegramNotifier")
def test_cli_test_alert_split_telegram(mock_telegram_cls):
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_telegram.chat_id = "123456"
    mock_telegram.send_split_deal_alert.return_value = True
    mock_telegram_cls.return_value = mock_telegram

    result = runner.invoke(app, ["test-alert", "--channel", "telegram", "--split"])
    assert result.exit_code == 0
    assert "Alerta de viagem avulsa enviado para o Telegram" in result.stdout
    mock_telegram.send_split_deal_alert.assert_called_once()

