#!/usr/bin/env bash
set -euo pipefail

# devcontainer のネットワーク境界の実体。OUTPUT を default-deny にし、
# 許可ドメインの解決済みIPだけを ipset で通す。
#
# なぜコンテナ側の iptables なのか:
#   ホスト(Ubuntu)の AppArmor は bwrap の子プロセスから capability を剥がす設計で、
#   Claude Code の Bash サンドボックス(bwrap内の入れ子userns)はこの機械では起動できない。
#   AppArmor へ例外を開けるとホスト全体の bwrap 隔離が緩むため、境界をコンテナ層へ
#   移した(ADR-0007)。この遮断は iptables なのでコンテナ内の全プロセス・全経路に効く。
#
# 実行のされ方:
#   devcontainer.json の postStartCommand から sudo で呼ばれる(起動のたびに適用し直す)。
#   Dockerfile が /usr/local/bin へ root所有 でコピーしたものだけが sudo 可能で、
#   作業ツリーのこのファイルを書き換えても、イメージを再ビルドするまで反映されない。
#   容易に反映されない不便さは意図したもの(境界の書き換えをビルドという明示的な
#   操作に縛る)。
#
# 既知の限界:
#   許可IPは起動時に解決した値で固定される。CDN等でIPが変わったら
#   コンテナを再起動する。
#   許可はIPアドレス単位であり、TLS SNI/Hostでは絞っていない。共有CDN上の
#   ドメイン(pypi.org等)は同じIPを他サービスとも共有しうるため、「許可ドメイン
#   以外へ通信できない」という保証はドメイン単位ではなくIP単位でしか成立しない。
#   **53番は宛先を絞っておらず、DNSは持ち出し経路として開いている。** 任意の
#   ネームサーバへ直接問い合わせられるほか、`<データ>.攻撃者のドメイン` を引けば
#   通常のリゾルバ経由でもクエリ名が相手の権威サーバへ届く。いずれの経路も
#   IP許可リストを通らない。塞ぐには53番を全遮断して許可ドメインを /etc/hosts へ
#   焼くしかなく、依存先のホスト名が多岐にわたるため採っていない(下の DNS の項)。
#
#   名前解決の結果も信頼している。リゾルバが侵害され、許可ドメインを攻撃者のIPへ
#   解決させる場合はこの層では防げない。
#
# 検査: scripts/check-repo-conventions.sh が default-deny 行の存在を見る

if [ "$(id -u)" -ne 0 ]; then
  echo "root で実行する(sudo /usr/local/bin/init-firewall.sh)" >&2
  exit 1
fi

# fail-closed: 許可リスト構築中(GitHub IPレンジのcurl・各ドメインのdig)は
# 一時的にOUTPUTをACCEPTへ戻す必要があり(下のブロックを見よ)、その窓の間に
# 名前解決やHTTP取得が失敗して`set -e`で中断すると、ACCEPTのまま終了してしまう
# (fail-open)。EXITトラップで、正常終了かどうかに関わらずdefault-denyを
# 必ず立て直す
trap 'iptables -P INPUT DROP 2> /dev/null || true
iptables -P FORWARD DROP 2> /dev/null || true
iptables -P OUTPUT DROP 2> /dev/null || true' EXIT

# 許可する外部ホスト。「必要最低限」の判断根拠を1件ずつ書く。
# GitHub は IP レンジが広く可変のため、下の meta API から別途取り込む
ALLOWED_DOMAINS=(
  api.anthropic.com        # Claude Code のモデルAPI
  claude.ai                # サブスクリプション認証(OAuth)
  pypi.org                 # uv のパッケージ解決
  files.pythonhosted.org   # uv のパッケージ取得
  api.bsky.app             # sns-collector: Bluesky検索
  www.googleapis.com       # sns-collector: YouTube Data API
  hn.algolia.com           # sns-collector: Hacker News検索
)

# 再実行時、前回の default-deny が残ったままだと下の名前解決が全部落ちる。
# 一旦 ACCEPT に戻してからルールを組み直す
iptables -P INPUT ACCEPT
iptables -P FORWARD ACCEPT
iptables -P OUTPUT ACCEPT
iptables -F
iptables -X
iptables -t nat -F
iptables -t nat -X
iptables -t mangle -F
iptables -t mangle -X
ipset destroy allowed-hosts 2> /dev/null || true

ipset create allowed-hosts hash:net

# GitHub のIPレンジ(git push/pull・gh・リリース取得)。
# 遮断前に取得する必要があるため、この位置で curl する
gh_meta="$(curl -fsSL https://api.github.com/meta)"
while IFS= read -r range; do
  ipset add allowed-hosts "${range}" -exist
done < <(jq -r '(.web + .api + .git)[]' <<< "${gh_meta}" | grep -v ':')

for domain in "${ALLOWED_DOMAINS[@]}"; do
  resolved="$(dig +short A "${domain}" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || true)"
  if [ -z "${resolved}" ]; then
    echo "${domain} を解決できなかったため中断する(許可リストに穴が開いたまま起動しない)" >&2
    exit 1
  fi
  while IFS= read -r ip; do
    ipset add allowed-hosts "${ip}" -exist
  done <<< "${resolved}"
done

# ループバック(dashboard の 127.0.0.1:8787 と Docker内蔵DNSがここを通る)
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# DNS。**宛先を絞らない。**
#
# 一度 resolv.conf のネームサーバへ限定したが戻した。許可したリゾルバは再帰
# 問い合わせを行うため、`<データ>.攻撃者のドメイン` を引けばクエリ名は上流経由で
# 権威サーバへ届く。宛先を絞ってもDNSによる持ち出しは塞がらず、閉じられるのは
# 「自前のネームサーバを直接指定する」変種だけだった。
#
# 塞ぐには53番を全遮断し、許可ドメインの解決結果を /etc/hosts へ焼くしかないが、
# 依存先(GitHub等)のホスト名が多岐にわたり解決漏れが起きるため採らない。
#
# **持ち出しを塞げない制限を残すと、塞げているつもりだけが残る。** 中途半端な
# 制御を持たず、DNSが開いた経路であることを「既知の限界」に書く方を選ぶ。
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# 確立済み接続の応答
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# ホスト側ブリッジとの通信(ポートフォワードの経路)
host_net="$(ip route | awk '/proto kernel/ {print $1; exit}')"
if [ -n "${host_net}" ]; then
  iptables -A INPUT -s "${host_net}" -j ACCEPT
  iptables -A OUTPUT -d "${host_net}" -j ACCEPT
fi

iptables -A OUTPUT -m set --match-set allowed-hosts dst -j ACCEPT

iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP

# IPv6 は許可リストを組んでいないため全て遮断する。
# ここを塞がないと、IPv6の生えている環境で許可リストが素通りになる。
#
# **`|| true` で握り潰さない。** IPv6カーネルモジュールが無い等でここが
# 失敗すると、以前は成功メッセージのまま起動していた(IPv6だけ無防備な状態が
# 検知されない)。IPv4側の自己検証と同じく、失敗したら`set -e`でここを
# fail-loudにする(上のEXITトラップでIPv4のdefault-denyは維持される)
if command -v ip6tables > /dev/null 2>&1; then
  ip6tables -P INPUT DROP
  ip6tables -P FORWARD DROP
  ip6tables -P OUTPUT DROP
  ip6tables -F
  ip6tables -A INPUT -i lo -j ACCEPT
  ip6tables -A OUTPUT -o lo -j ACCEPT
fi

# 自己検証。遮断が効いていないまま「守れているつもり」で起動するのが最悪の形
# (docs/isolation.md §6)なので、両方向を実際に叩いて確かめる
if curl -s --connect-timeout 5 https://example.com > /dev/null 2>&1; then
  echo "検証失敗: 許可していない example.com へ届いてしまう" >&2
  exit 1
fi
if ! curl -s --max-time 10 https://api.github.com/zen > /dev/null; then
  echo "検証失敗: 許可済みの api.github.com へ届かない" >&2
  exit 1
fi

echo "ファイアウォール適用済み: default-deny + 許可 $(ipset list allowed-hosts | grep -c '^[0-9]') レンジ"
