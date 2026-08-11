from __future__ import annotations

import time
from collections.abc import Callable

import requests

from ...http import post_json

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

# 期限ちょうどで使うと、通信中に切れて401になる。手前で更新する
EXPIRY_MARGIN_SECONDS = 60.0

# expires_in が返らなかった場合の保守的な既定値
DEFAULT_EXPIRES_IN = 3600.0


def fetch_token(client_id: str, client_secret: str, user_agent: str) -> tuple[str, float]:
    """application-only OAuth2でアクセストークンを取る。戻り値は(token, expires_in秒)。

    grant_type=client_credentials は「アプリ自身」としての読み取り専用アクセスで、
    ユーザーのログイン・リダイレクトを必要としない。取得先は oauth.reddit.com
    ではなく www.reddit.com である点に注意。
    """
    payload = post_json(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": user_agent},
        auth=(client_id, client_secret),
        label="reddit:token",
    )
    # RedditはOAuthの失敗(未登録アプリ・資格情報の誤り等)をHTTP 200 + エラー本文
    # ({"error": "invalid_grant"}等)で返すことがある。ここで拾わずKeyErrorを漏らすと、
    # TokenProvider.token()が約束する「requests.RequestExceptionだけが伝播する」が
    # 破れ、呼び出し側(search.py)のキーワード単位隔離をすり抜けてrun全体が落ちる
    try:
        return str(payload["access_token"]), float(payload.get("expires_in", DEFAULT_EXPIRES_IN))
    except KeyError as e:
        # 本文をそのまま出さない。資格情報そのものは含まれないはずだが、
        # 予期しないフィールドを不用意にログへ出す経路を増やさない
        reason = payload.get("error", "不明")
        raise requests.HTTPError(
            f"Redditのトークン応答にaccess_tokenが無い(error: {reason})"
        ) from e


class TokenProvider:
    """トークンの取得・保持・期限判定を検索呼び出しから切り離す。

    これがあることで reddit/client.py は「トークンを受け取って叩く」だけの関数になり、
    他プラットフォームのclient.pyと同じ形を保てる。どうやってトークンを得たか・
    いつ更新するかをclient側は知らない。
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        *,
        now: Callable[[], float] = time.monotonic,
        fetch: Callable[[str, str, str], tuple[str, float]] = fetch_token,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._now = now
        self._fetch = fetch
        self._token: str | None = None
        self._expires_at: float = 0.0

    def token(self) -> str:
        """有効なトークンを返す。無い/期限切れなら取り直す。

        取得に失敗した場合は requests.RequestException をそのまま送出する。
        呼び出し側(search.py)がキーワード単位の隔離と同じ経路で扱う。
        """
        if self._token is None or self._now() >= self._expires_at - EXPIRY_MARGIN_SECONDS:
            token, expires_in = self._fetch(self._client_id, self._client_secret, self._user_agent)
            self._token = token
            self._expires_at = self._now() + expires_in
        return self._token
