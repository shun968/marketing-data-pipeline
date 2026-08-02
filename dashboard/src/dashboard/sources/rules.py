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

    @property
    def outline(self) -> list[tuple[int, str]]:
        return markup.outline(self.body)


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


_LEFTHOOK_JOB = re.compile(
    r"^\s*-\s*name:\s*(?P<name>\S+)\s*$"
    r"(?P<rest>(?:\n\s+(?!-\s*name:)\S.*)*)",
    re.MULTILINE,
)
_RUN = re.compile(r"^\s+run:\s*(?P<cmd>.+?)\s*$", re.MULTILINE)
_INTERACTIVE = re.compile(r"^\s+interactive:\s*true\s*$", re.MULTILINE)
_CI_STEP = re.compile(r"^\s+-\s*name:\s*(?P<name>.+?)\s*\n\s+run:\s*(?P<cmd>.+?)\s*$", re.MULTILINE)


def load_gates() -> list[Gate]:
    """lefthook と CI から、実際に動いているゲートを組み立てる。

    YAMLパーサを入れずに正規表現で読むのは、ここで欲しいのが
    「名前とコマンドの対」だけで、構造の完全な解釈が要らないため。
    読めなかった行は落とすが、画面には出典のパスを併記するので
    実ファイルを開けば確認できる。
    """
    root = repo_root()
    gates: list[Gate] = []

    lefthook = root / "lefthook.yml"
    if lefthook.is_file():
        text = lefthook.read_text(encoding="utf-8")
        for job in _LEFTHOOK_JOB.finditer(text):
            block = job.group("rest") or ""
            run = _RUN.search(block)
            if not run:
                continue
            gates.append(
                Gate(
                    name=job.group("name"),
                    command=run.group("cmd"),
                    where="pre-commit",
                    interactive=bool(_INTERACTIVE.search(block)),
                )
            )

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
