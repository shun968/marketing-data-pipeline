"""開発ルールの読み取り。

リポジトリの規約は「何がどこで強制されるか」がすべてで、散文そのものより
**どの検査がどこで走るか**が実体である(CLAUDE.md)。
そこでドキュメントの本文に加えて、lefthook.yml と CI から
「実際に動いているゲートの一覧」を組み立てて並べる。

散文だけを表示すると、書いてあるが動いていない規約と、
動いているが書かれていない規約の区別が付かない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dashboard import markup
from dashboard.paths import relative_to_repo, repo_root, roots


@dataclass(frozen=True)
class Document:
    slug: str
    title: str
    path: str
    body: str

    @property
    def html(self) -> str:
        return markup.render(self.body)


@dataclass(frozen=True)
class Gate:
    """実際に動いているゲート1つ。"""

    name: str
    command: str
    where: str
    interactive: bool

    @property
    def script(self) -> str:
        """呼んでいる検査スクリプト。記録層のラッパーは剥がす。"""
        found = re.findall(r"\./scripts/[a-z0-9-]+\.sh", self.command)
        for candidate in found:
            if "record-check.sh" not in candidate:
                return candidate
        return found[0] if found else self.command

    @property
    def recorded(self) -> bool:
        return "record-check.sh" in self.command

    @property
    def is_check(self) -> bool:
        """検査そのものか。

        テストの実行やコミットメッセージ補助はゲートだが検査ではなく、
        記録の対象にしていない。「記録が無い」と並べても対処のしようがない
        ため、記録漏れの指摘からは外す。
        """
        return bool(re.search(r"scripts/(check|lint)-[a-z0-9-]+\.sh", self.command))


def _document(path: Path, slug: str, title: str) -> Document | None:
    if not path.is_file():
        return None
    return Document(
        slug=slug,
        title=title,
        path=relative_to_repo(path),
        body=path.read_text(encoding="utf-8"),
    )


def load_documents() -> list[Document]:
    """規約と設計のドキュメント。

    CLAUDE.md はルートと各領域に散らしてよい規約であり(領域固有のものは
    その領域へ置く)、ここでは見つかったものをすべて並べる。
    """
    root = repo_root()
    documents: list[Document] = []

    doc = _document(root / "CLAUDE.md", "root", "CLAUDE.md（リポジトリ全体）")
    if doc:
        documents.append(doc)

    for path in sorted(root.glob("*/CLAUDE.md")):
        area = path.parent.name
        doc = _document(path, f"area-{area}", f"CLAUDE.md（{area}）")
        if doc:
            documents.append(doc)

    skills_dir = roots().skills
    if skills_dir.is_dir():
        for path in sorted(skills_dir.glob("*/SKILL.md")):
            name = path.parent.name
            doc = _document(path, f"skill-{name}", f"{name} スキル")
            if doc:
                documents.append(doc)

    design_docs = (("design.md", "設計"), ("requirements.md", "要件"), ("roadmap.md", "実装計画"))
    for name, title in design_docs:
        doc = _document(roots().docs / name, f"docs-{Path(name).stem}", title)
        if doc:
            documents.append(doc)

    return documents


# lefthook のフック見出し。列0から始まる `pre-commit:` `commit-msg:` など
_HOOK_HEADING = re.compile(r"^(?P<hook>[a-z][a-z0-9-]*):\s*$")

# **ジョブの境界は `-` の有無で決まる。**
# リスト項目(`- name:` / `- run:`)が新しいジョブの始まりで、
# 字下げだけの `name:` / `run:` は現在のジョブの属性である。
# ここを区別しないと、名前を持たないジョブが2つ以上並んだときに
# 2つ目以降が現在のジョブへ吸収されて消え、`interactive` も前へ漏れる。
_JOB_NAME = re.compile(r"^\s*-\s*name:\s*(?P<name>.+?)\s*$")
_JOB_RUN = re.compile(r"^\s*-\s*run:\s*(?P<cmd>.+?)\s*$")
_NAME_PROP = re.compile(r"^\s+name:\s*(?P<name>.+?)\s*$")
_RUN_PROP = re.compile(r"^\s+run:\s*(?P<cmd>.+?)\s*$")
_INTERACTIVE = re.compile(r"^\s*-?\s*interactive:\s*true\s*$")
_CI_STEP = re.compile(r"^\s+-\s*name:\s*(?P<name>.+?)\s*\n\s+run:\s*(?P<cmd>.+?)\s*$", re.MULTILINE)


def _parse_lefthook(text: str) -> list[Gate]:
    """lefthook.yml を上から1行ずつ読み、フックごとにジョブを組み立てる。

    **どのフックで動くかを取り違えない。** この画面の主眼は
    「実際に動いているゲート」を出すことなので、実行場所を誤ると
    目的そのものが崩れる。`prepare-commit-msg` や `commit-msg` の
    ジョブを `pre-commit` として出さない。

    YAMLパーサを入れず行単位で読むのは、ここで欲しいのが
    「フック名・ジョブ名・コマンド」の3つだけで、
    構造の完全な解釈が要らないため。
    """
    gates: list[Gate] = []
    hook: str | None = None
    name: str | None = None
    command: str | None = None
    interactive = False

    def flush() -> None:
        nonlocal name, command, interactive
        # 名前は無くてもよい。`- run:` だけのジョブはコマンドを名前として出す
        if hook and command:
            gates.append(
                Gate(name=name or command, command=command, where=hook, interactive=interactive)
            )
        name = None
        command = None
        interactive = False

    for line in text.splitlines():
        heading = _HOOK_HEADING.match(line)
        if heading:
            flush()
            hook = heading.group("hook")
            continue

        job_name = _JOB_NAME.match(line)
        if job_name:
            flush()
            name = job_name.group("name")
            continue

        job_run = _JOB_RUN.match(line)
        if job_run:
            flush()
            command = job_run.group("cmd")
            continue

        if _INTERACTIVE.match(line):
            interactive = True
            continue

        name_prop = _NAME_PROP.match(line)
        if name_prop and name is None:
            name = name_prop.group("name")
            continue

        run_prop = _RUN_PROP.match(line)
        if run_prop and command is None:
            command = run_prop.group("cmd")

    flush()
    return gates


def load_gates() -> list[Gate]:
    """lefthook と CI から、実際に動いているゲートを組み立てる。

    読めなかった行は落とすが、画面には出典のパスを併記するので
    実ファイルを開けば確認できる。
    """
    root = repo_root()
    gates: list[Gate] = []

    lefthook = root / "lefthook.yml"
    if lefthook.is_file():
        gates.extend(_parse_lefthook(lefthook.read_text(encoding="utf-8")))

    ci = root / ".github" / "workflows" / "ci.yml"
    if ci.is_file():
        text = ci.read_text(encoding="utf-8")
        for step in _CI_STEP.finditer(text):
            command = step.group("cmd")
            if "scripts/" not in command:
                continue
            gates.append(
                Gate(
                    name=step.group("name"),
                    command=command,
                    where="CI",
                    interactive=False,
                )
            )

    return gates
