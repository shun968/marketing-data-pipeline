# 開発環境ごと隔離境界に入れるイメージ(docs/isolation.md §4 C / ADR-0007)。
#
# 方針:
#   - ネットワークを使うインストールはすべてビルド時に済ませる。
#     実行時の許可ドメイン(init-firewall.sh)を増やさないため
#   - Claude Code は自動更新を無効にして焼き込む。更新はイメージの再ビルドで行う
#   - バージョンはホストで検証済みのものに固定する

FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

ARG TASK_VERSION=v3.52.0
ARG UV_VERSION=0.11.32

# iptables/ipset/dnsutils/iproute2 は init-firewall.sh の実行に必要
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dnsutils \
        gh \
        ipset \
        iptables \
        iproute2 \
        jq \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# uv(lefthook / shellcheck / yamllint は uvx 経由で解決するため、これ1つで足りる)
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
    | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh

# go-task
RUN curl -LsSf https://taskfile.dev/install.sh | sh -s -- -d -b /usr/local/bin "${TASK_VERSION}"

# ファイアウォール。root所有の固定コピーだけを sudo 対象にする。
# 作業ツリー側のスクリプトを直接 sudo させると、スクリプトを書き換えてから
# 実行することで境界を自由に外せてしまう
COPY init-firewall.sh /usr/local/bin/init-firewall.sh
RUN chmod 755 /usr/local/bin/init-firewall.sh \
    && chown root:root /usr/local/bin/init-firewall.sh

# base イメージが付けてくる無条件 NOPASSWD sudo を剥がす。
# コンテナ内で root が取れると iptables を消せるため、境界が形骸化する。
# 残すのはファイアウォールの再適用だけ
RUN rm -f /etc/sudoers.d/vscode /etc/sudoers.d/nopasswd \
    && echo "vscode ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" \
       > /etc/sudoers.d/init-firewall \
    && chmod 440 /etc/sudoers.d/init-firewall

# 認証情報を保持する named volume のマウント先。
# イメージ内で所有者を合わせておくと、初回マウント時に volume が引き継ぐ
RUN mkdir -p /home/vscode/.claude /home/vscode/.config/gh \
    && chown -R vscode:vscode /home/vscode/.claude /home/vscode/.config

# Claude Code 本体。native インストーラで vscode ユーザ配下へ入れる。
# 自動更新は devcontainer.json の DISABLE_AUTOUPDATER=1 で止める
USER vscode
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/home/vscode/.local/bin:${PATH}"
USER root
