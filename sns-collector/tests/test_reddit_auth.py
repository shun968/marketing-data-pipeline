from __future__ import annotations

import pytest
import requests

from sns_collector.reddit.auth import TokenProvider, fetch_token


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _provider(clock: _Clock, fetch) -> TokenProvider:
    return TokenProvider("id", "secret", "test-agent", now=clock, fetch=fetch)


def test_トークンはrun中に1度しか取りに行かない():
    clock = _Clock()
    calls = []

    def fake_fetch(client_id, client_secret, user_agent):
        calls.append((client_id, client_secret, user_agent))
        return "token-1", 3600.0

    provider = _provider(clock, fake_fetch)
    assert provider.token() == "token-1"
    assert provider.token() == "token-1"
    assert provider.token() == "token-1"
    assert len(calls) == 1


def test_期限が切れたら取り直す():
    clock = _Clock()
    tokens = iter(["token-1", "token-2"])
    calls = []

    def fake_fetch(*_args):
        calls.append(1)
        return next(tokens), 100.0

    provider = _provider(clock, fake_fetch)
    assert provider.token() == "token-1"

    clock.now += 200  # 期限(100秒)を大きく超える
    assert provider.token() == "token-2"
    assert len(calls) == 2


def test_期限の手前で先に取り直す():
    """マージン(60秒)の分だけ早めに更新する。ちょうどの期限で使うと通信中に切れる。"""
    clock = _Clock()
    tokens = iter(["token-1", "token-2"])
    calls = []

    def fake_fetch(*_args):
        calls.append(1)
        return next(tokens), 100.0

    provider = _provider(clock, fake_fetch)
    provider.token()

    clock.now += 30  # 期限まで70秒残っている(マージン60秒より外)
    assert provider.token() == "token-1"
    assert len(calls) == 1

    clock.now += 15  # 期限まで55秒(マージン60秒圏内) -> 取り直す
    assert provider.token() == "token-2"
    assert len(calls) == 2


def test_取得失敗はrequests例外としてそのまま送出される():
    clock = _Clock()

    def fake_fetch(*_args):
        raise requests.HTTPError("401 Unauthorized")

    provider = _provider(clock, fake_fetch)
    with pytest.raises(requests.HTTPError):
        provider.token()


def test_access_tokenが無いレスポンスはRequestExceptionになる(monkeypatch):
    """RedditはOAuth失敗をHTTP 200 + エラー本文で返すことがある。

    KeyErrorを漏らすとTokenProvider.token()の「RequestExceptionだけが伝播する」
    という約束が破れ、search.py側のキーワード単位隔離をすり抜けてrunが落ちる。
    """

    def fake_post_json(*_args, **_kwargs):
        return {"error": "invalid_grant"}

    monkeypatch.setattr("sns_collector.reddit.auth.post_json", fake_post_json)
    with pytest.raises(requests.RequestException):
        fetch_token("id", "secret", "test-agent")


def test_access_tokenが無いレスポンスはTokenProvider経由でもRequestExceptionのまま(monkeypatch):
    """fetch_tokenだけでなくTokenProvider.token()を通しても契約が保たれることを確認する。"""

    def fake_post_json(*_args, **_kwargs):
        return {}

    monkeypatch.setattr("sns_collector.reddit.auth.post_json", fake_post_json)
    provider = TokenProvider("id", "secret", "test-agent")
    with pytest.raises(requests.RequestException):
        provider.token()


def test_User_Agentヘッダを付けてトークンを取りに行く(monkeypatch):
    captured = {}

    def fake_post_json(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["auth"] = kwargs.get("auth")
        captured["data"] = kwargs.get("data")
        return {"access_token": "t", "expires_in": 3600}

    monkeypatch.setattr("sns_collector.reddit.auth.post_json", fake_post_json)
    token, expires_in = fetch_token("id", "secret", "test-agent")

    assert token == "t"
    assert expires_in == 3600.0
    assert captured["headers"] == {"User-Agent": "test-agent"}
    assert captured["auth"] == ("id", "secret")
    assert captured["data"] == {"grant_type": "client_credentials"}


def test_ログにclient_secretを出さない(monkeypatch, capsys):
    def fake_post_json(*_args, **_kwargs):
        return {"access_token": "t", "expires_in": 3600}

    monkeypatch.setattr("sns_collector.reddit.auth.post_json", fake_post_json)
    fetch_token("id", "super-secret-value", "test-agent")

    assert "super-secret-value" not in capsys.readouterr().out
