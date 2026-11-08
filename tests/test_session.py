from unittest.mock import Mock, patch

import httpx

from _core._session import _dataGetHome_blocking


def test_dataGetHome_success():
    with patch("_core._session.send_get_request") as mock_get:
        mock_resp = Mock()
        mock_resp.text = (
            'DTSGInitialData",[],{"token":"mock_dtsg"}'
            ' async_get_token":"mock_dtsg_ag"'
            ' jazoest=22421"'
            ' hash":"mock_hash"'
            ' sessionId":"1234567890"'
            ' "actorID":"10001234567890"'
            ' client_revision":123456,'
        )
        mock_get.return_value = mock_resp

        cookie = "c_user=10001234567890; xs=mock_xs; fr=mock_fr; datr=mock_datr;"
        result = _dataGetHome_blocking(cookie)

        assert result == {
            "fb_dtsg": "mock_dtsg",
            "fb_dtsg_ag": "mock_dtsg_ag",
            "jazoest": "22421",
            "hash": "mock_hash",
            "sessionID": "1234567890",
            "IGSID": "10001234567890",
            "clientRevision": "123456",
            "cookieIGS": cookie,
        }
        mock_resp.raise_for_status.assert_called_once()


def test_dataGetHome_instagram_html_tokens():
    with patch("_core._session.send_get_request") as mock_get:
        mock_resp = Mock()
        mock_resp.text = (
            '"csrf_token":"ig_csrf_123"'
            ' "viewerId":"17841400000000"'
            ' "session_id":"ig_sess_999"'
            ' client_revision":998877,'
        )
        mock_get.return_value = mock_resp

        cookie = (
            "sessionid=ig_sess_999; csrftoken=ig_csrf_123; ds_user_id=17841400000000;"
        )
        result = _dataGetHome_blocking(cookie)

        assert result is not None
        assert result["fb_dtsg"] == "ig_csrf_123"
        assert result["IGSID"] == "17841400000000"
        assert result["sessionID"] == "ig_sess_999"
        assert result["clientRevision"] == "998877"
        assert result["cookieIGS"] == cookie


def test_dataGetHome_network_error():
    with patch(
        "_core._session.send_get_request",
        side_effect=httpx.RequestError("Network error", request=Mock()),
    ):
        result = _dataGetHome_blocking("cookie")
        assert result is None
