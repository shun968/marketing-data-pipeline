#!/usr/bin/env bash
set -euo pipefail

# scripts/check-layer-deps.sh の回帰テスト。
#
# **検知できることと同じ数だけ、誤検知しないことを書く。** 層の検査は
# 全ファイルに掛かるため、誤検知が出ると無関係なコミットが止まり、
# --no-verify の常用を招く（CLAUDE.md）。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-layer-deps.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup() {
  new_git_workdir
  mkdir -p scripts pkg/domain pkg/usecase pkg/adapter/db pkg/adapter/source/alpha \
    pkg/adapter/source/beta pkg/entrypoint
  cp "${SCRIPT}" scripts/check-layer-deps.sh
  # 層の外のファイル。検査対象にならないこと自体も確認したい
  : > pkg/__init__.py
  for layer in domain usecase adapter entrypoint; do : > "pkg/${layer}/__init__.py"; done
  : > pkg/adapter/db/__init__.py
  : > pkg/adapter/source/alpha/__init__.py
  : > pkg/adapter/source/beta/__init__.py
}

teardown() {
  cleanup_workdir
}

# write <相対パス> <本文>
write() {
  printf '%s\n' "$2" > "pkg/$1"
}

# assert_exit <期待する終了コード> <ケース名>
assert_exit() {
  local actual=0
  ./scripts/check-layer-deps.sh "$(pwd)/pkg" > /dev/null 2>&1 || actual=$?
  check_exit "$1" "$2" "${actual}"
}

suite_begin "check-layer-deps.sh"

# ── 検知する ────────────────────────────────────────────────────────

setup
write "domain/thing.py" "from ..usecase import collect"
assert_exit 1 "domain が usecase を import したら止める"
teardown

setup
write "usecase/collect.py" "from ..adapter.db import connect"
assert_exit 1 "usecase が adapter を import したら止める"
teardown

setup
write "adapter/db/store.py" "from ...usecase import collect"
assert_exit 1 "adapter が usecase を import したら止める"
teardown

setup
write "adapter/source/alpha/dto.py" "from ..beta.dto import clean"
assert_exit 1 "収集元どうしの import を止める"
teardown

setup
write "adapter/http.py" "from .source.alpha import client"
assert_exit 1 "共通基盤から収集元への import を止める"
teardown

setup
write "usecase/collect.py" "import duckdb"
assert_exit 1 "usecase の外部ライブラリを止める"
teardown

setup
write "domain/post.py" "import requests"
assert_exit 1 "domain の外部ライブラリを止める"
teardown

setup
write "usecase/collect.py" "from requests import Session"
assert_exit 1 "from形式の外部ライブラリも止める"
teardown

# __init__.py は自分自身がパッケージであり、相対importの基点が1つ深い。
# ここを間違えると、収集元どうしの依存を素通しにする(PR #70 のレビュー指摘)
setup
write "adapter/source/alpha/__init__.py" "from ..beta.dto import clean"
assert_exit 1 "__init__.py に置いた収集元どうしの import も止める"
teardown

# import の書き方を変えるだけで規則を迂回できてはならない
setup
write "usecase/collect.py" "import pkg.adapter.db as db"
assert_exit 1 "自パッケージへの絶対 import も層の対象にする"
teardown

setup
write "usecase/collect.py" "from pkg import adapter"
assert_exit 1 "from <pkg> import <層> の形も止める"
teardown

# ── 誤検知しない ────────────────────────────────────────────────────

setup
write "usecase/collect.py" "from ..domain.collect import CollectTask"
assert_exit 0 "usecase -> domain は通す"
teardown

setup
write "adapter/db/store.py" "from ...domain.post import PostRow"
assert_exit 0 "adapter -> domain は通す"
teardown

setup
write "entrypoint/cli.py" "from ..usecase.collect import collect
from ..adapter.db import connect
from ..domain.config import ConfigError"
assert_exit 0 "entrypoint は全層を通す"
teardown

setup
write "adapter/source/alpha/client.py" "from ...http import get_json"
assert_exit 0 "収集元から共通基盤への import は通す"
teardown

setup
write "adapter/source/alpha/source.py" "from .client import fetch
from .dto import Item"
assert_exit 0 "同じ収集元の中は通す"
teardown

setup
write "adapter/db/repository.py" "from .mapping import ADAPTERS
from .schema import migrate"
assert_exit 0 "共通基盤どうしは通す"
teardown

setup
write "domain/post.py" "import json
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable"
assert_exit 0 "domain の標準ライブラリは通す"
teardown

setup
write "usecase/collect.py" "import re
from pathlib import Path"
assert_exit 0 "usecase の標準ライブラリは通す"
teardown

setup
write "adapter/http.py" "import requests
import yaml
import duckdb"
assert_exit 0 "adapter の外部ライブラリは通す"
teardown

setup
write "usecase/collect.py" "from . import keyword_quality"
assert_exit 0 "同じ層の中は通す"
teardown

setup
write "adapter/source/alpha/__init__.py" "from .dto import clean"
assert_exit 0 "__init__.py の同一パッケージ内 import は通す"
teardown

setup
write "usecase/collect.py" "import pkg.domain.post
from pkg import domain"
assert_exit 0 "自パッケージへの絶対 import でも、許された層なら通す"
teardown

# 層のディレクトリに属さないファイルは、規則の対象外
setup
write "__init__.py" "import duckdb"
assert_exit 0 "層の外のファイルは対象にしない"
teardown

# 何も無い状態で誤って失敗しない
setup
assert_exit 0 "違反が無ければ通す"
teardown

suite_end
