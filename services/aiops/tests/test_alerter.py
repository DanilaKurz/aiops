import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.drain.alerter import KeepAlerter


@pytest.mark.asyncio
async def test_send_alert_success():
    with patch("app.drain.alerter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(status_code=200)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        alerter = KeepAlerter("http://keep:8080", "test-key", db_path=":memory:")
        await alerter.send_alert({
            "service": "gateway",
            "template": "Connection timeout to <*>",
            "score": 0.95,
            "anomaly_type": "isolation_forest",
        })
        mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_alert_queues_on_failure():
    with patch("app.drain.alerter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        alerter = KeepAlerter("http://keep:8080", "test-key", db_path=":memory:")
        await alerter.send_alert({
            "service": "gateway",
            "template": "test",
            "score": 0.9,
            "anomaly_type": "test",
        })
        pending = alerter.get_pending_count()
        assert pending >= 1
