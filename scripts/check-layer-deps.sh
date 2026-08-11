#!/usr/bin/env bash
set -euo pipefail

# 層をまたぐ import が ADR-0011 の規則に反していないかを検査する。
#
# なぜ必要か:
#   層の分け方は散文で書いても、その作業の瞬間に想起されなければ発火しない。
#   実際、収集元を1つ足すたびに client/models/search の3点セットが複製され、
#   6つ目で「兄弟の収集元を直接 import する」依存が生まれた(ADR-0010)。
#   import の可否は文字列と構造で決まるため、承認フローではなく検査に落とす
#   (CLAUDE.md「機械検査と承認フローの使い分け」)。
#
# 何を見るか:
#   1. 層をまたぐ import の向き。規則表は ADR-0011 にあり、下の ALLOWED が実装。
#   2. adapter 内の水平依存。収集元どうし(source/<A> -> source/<B>)は不可。
#      共通基盤(adapter直下)へは可。逆に共通基盤から収集元へは不可。
#   3. domain / usecase が外部ライブラリへ依存していないか。
#      **この3つ目が実質である。** usecase から duckdb と requests を締め出すと、
#      収集ロジックのテストがHTTPサーバもDBファイルもモックも無しで書ける。
#
# 判定できないもの:
#   実行時にだけ現れる依存(文字列でのimport、動的なgetattr)は見ない。
#   静的に import 文として書かれたものだけが対象。
#
# 使い方:
#   scripts/check-layer-deps.sh
#
# 実装がPythonなのは、import の解析に ast が要るため。外部依存を増やさないよう
# 標準ライブラリだけで書き、スクリプト内に埋め込んでいる。
#
# テスト: scripts/tests/check-layer-deps.test.sh

root="$(git rev-parse --show-toplevel)"
target="${1:-${root}/sns-collector/src/sns_collector}"

if [ ! -d "${target}" ]; then
  echo "対象が見つからない: ${target}" >&2
  exit 1
fi

python3 - "${target}" <<'PY'
import ast
import pathlib
import sys

# ADR-0011 の規則表。キーが import する側、値が import してよい層。
ALLOWED = {
    "domain": {"domain"},
    "usecase": {"domain", "usecase"},
    "adapter": {"domain", "adapter"},
    "entrypoint": {"domain", "usecase", "adapter", "entrypoint"},
}

# 外部ライブラリを使ってよい層。ここに無い層は標準ライブラリのみ。
EXTERNAL_ALLOWED = {"adapter", "entrypoint"}

STDLIB = set(sys.stdlib_module_names)

root = pathlib.Path(sys.argv[1]).resolve()
package = root.name
violations = []


def layer_of(module: str) -> str | None:
    """パッケージ相対のモジュール名から層を決める。層の外なら None。"""
    head = module.split(".", 1)[0]
    return head if head in ALLOWED else None


def targets_of(module: str, node: ast.stmt, is_package: bool) -> list[str]:
    """この import 文が指す、パッケージ相対のモジュール名を列挙する。

    **`__init__.py` は自分自身がパッケージである。** モジュール名から
    `.__init__` を落としてあるため、相対 import の基点を「1つ上」にすると
    1階層ずれる。ずれると収集元どうしの依存を見逃し（`hnjobs/__init__.py` の
    `from ..hackernews.dto import ...` が `adapter.hackernews.dto` に化ける）、
    同時に正当な `from .dto import ...` を誤検知する。

    自パッケージへの絶対 import（`import <pkg>.adapter.db` /
    `from <pkg> import adapter`）も層の対象にする。ここを素通しにすると、
    import の書き方を変えるだけで規則を迂回できる。
    """
    if isinstance(node, ast.Import):
        out = []
        for alias in node.names:
            head, _, rest = alias.name.partition(".")
            if head == package and rest:
                out.append(rest)
        return out

    if not isinstance(node, ast.ImportFrom):
        return []

    if node.level:
        # __init__.py の `.` は自分自身のパッケージを指す
        parts = module.split(".") if is_package else module.split(".")[:-1]
        up = node.level - 1
        base = parts[: len(parts) - up] if up else parts
        tail = node.module.split(".") if node.module else []
        return [".".join([*base, *tail])]

    if not node.module:
        return []
    head, _, rest = node.module.partition(".")
    if head != package:
        return []
    if rest:
        return [rest]
    # `from <pkg> import adapter` の形。取り込む名前そのものが層になる
    return [alias.name for alias in node.names]


def check_horizontal(module: str, target: str) -> str | None:
    """adapter 層内の追加規則。違反の説明を返す。問題なければ None。"""
    src_parts = module.split(".")
    dst_parts = target.split(".")
    src_is_source = src_parts[:2] == ["adapter", "source"]
    dst_is_source = dst_parts[:2] == ["adapter", "source"]

    if src_is_source and dst_is_source and src_parts[2:3] != dst_parts[2:3]:
        return "収集元どうしは互いを import できない"
    if not src_is_source and dst_is_source and src_parts[0] == "adapter":
        return "共通基盤から収集元への import はできない"
    return None


for path in sorted(root.rglob("*.py")):
    rel = path.relative_to(root)
    is_package = path.name == "__init__.py"
    module = str(rel).removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    src_layer = layer_of(module)
    if src_layer is None:
        continue

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue

        # 層をまたぐ import
        for target in targets_of(module, node, is_package):
            dst_layer = layer_of(target)
            if dst_layer is None:
                continue
            if dst_layer not in ALLOWED[src_layer]:
                violations.append(
                    (rel, node.lineno, f"{src_layer} -> {dst_layer} は不可（ADR-0011）")
                )
            elif dst_layer == src_layer == "adapter":
                reason = check_horizontal(module, target)
                if reason:
                    violations.append((rel, node.lineno, reason))

        # 外部ライブラリ
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif not node.level and node.module:
            names = [node.module.split(".")[0]]

        for name in names:
            if name in STDLIB or name == package:
                continue
            if src_layer not in EXTERNAL_ALLOWED:
                violations.append(
                    (rel, node.lineno, f"{src_layer} は外部ライブラリ {name} を使えない（ADR-0011）")
                )

if violations:
    print(f"NG: [layer-deps] 層の依存規則に反する import がある（{len(violations)} 件）")
    print()
    for rel, lineno, reason in violations:
        print(f"  {rel}:{lineno}  {reason}")
    print()
    print("層と規則表は docs/adr/0011-layered-architecture-and-import-rules.md にある。")
    print("内側の層が外側を知らない形へ直すか、共有するものを共通基盤へ引き上げること。")
    sys.exit(1)
PY
