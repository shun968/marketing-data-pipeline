# ADR-0007: 隔離境界をdevcontainerで実現しホストのAppArmorは変更しない

- ステータス: 採用
- 日付: 2026-08-09
- 関連: docs/isolation.md（制御の層と経路） / CLAUDE.md「開発セッションはdevcontainer内で動かす」 / ADR-0003（Claude Codeセッションの役割）

## コンテキスト

Claude Codeセッションには、permissionsルール（ツール層の制御点）だけでは塞げない経路が2つある。Bashが起動した子プロセスによるファイル・ネットワークアクセス（docs/isolation.md §3 経路3）と、hooks・MCPサーバー（同 経路4）である。経路3を塞ぐOS層の仕組みとしてClaude CodeはBashサンドボックス（bubblewrap + seccomp）を持つが、この開発機（Ubuntu 26.04）では起動できない。同梱のAppArmorプロファイル `bwrap-userns-restrict` が「bwrapの子プロセスはcapabilityを持たない」設計を強制しており、サンドボックスが必要とするbwrap内の入れ子user namespace構築（`CAP_SYS_ADMIN` 要求）がここで拒否されるためである。

このリポジトリはPublicで、収集データ・APIキーを外部へ出さないことが最重要制約である。ツール層の制御点は維持した上で、OS層の境界をどこに引くかを決める必要があった。

### 検討した選択肢

| 案 | 却下理由 |
|---|---|
| AppArmorのlocal overrideで `unpriv_bwrap` に `sys_admin` を許可 | 最小の変更でBashサンドボックスが動くが、bwrapを使う全アプリ（flatpak等）の隔離が同時に緩む。ホストの防御を削って開発ツールを通すのは本末転倒 |
| プロファイル無効化 + sysctl緩和 | 上と同じ方向でさらに影響が広い |
| sandbox runtime（Claude Codeプロセス全体をbwrapで包む） | 同じbubblewrapに依存し、この機械では同じ箇所で落ちる（検証済み） |
| `sandbox.failIfUnavailable: false` で黙認 | 境界が無いまま静かに素通りし、守れているという誤解だけが残る |
| 実行ユーザの分離 | git・gh・各種認証が全て別ユーザ側になり、単独の開発環境では運用が成立しない |

## 決定

**開発セッションをdevcontainer（Docker + iptables default-deny）の内側で動かし、ホストのAppArmorには一切手を入れない。**

判断の根拠:

1. **ホストの防御を削らない。** Ubuntuのuserns制限は攻撃面を狭めるための設計で、これを緩めて得るものは開発ツールの利便でしかない。境界が過剰（hooks・MCPまで囲う）になる不利益より、ホストに穴を開ける不利益のほうが大きい。
2. **遮断がネットワーク層で全経路に効く。** Bashサンドボックスの遮断はサンドボックスを通る呼び出しにしか効かないが、コンテナのiptablesはhooks・MCP・任意の子プロセスを含む全プロセスに効く。許可ドメインの管理も `.devcontainer/init-firewall.sh` の1箇所になる。
3. **境界の書き換えに明示的な操作が要る。** sudoは root所有の固定コピーされたファイアウォールスクリプト1つにしか通らず、変更の反映にはイメージ再ビルドが要る。ツール層でも `.devcontainer/**` の編集は承認制で、`scripts/check-repo-conventions.sh` がdefault-denyの存在をコミット時に検査する。

## 結果

hooks・MCP・Bash子プロセスの全経路が許可ドメイン以外へ通信できなくなり、ホスト側の `~/.ssh` 等はコンテナに存在すらしなくなる。ツール層のpermissions（秘匿ファイルのdeny・ガードレールのask）はコンテナ内でも従来どおり効く。

受け入れた不利益と残る作業:

- **ホスト直起動のセッションには境界が無い。** コンテナ内で使うことは機械強制できず、CLAUDE.mdの運用ルールに留まる。Bashサンドボックスは使えない前提のため `settings.json` でも有効化しない。
- 境界内にコンテナ専用の認証（Claude Codeログイン・ghトークン）を置く。ホストの認証情報は持ち込まない運用とし、漏洩時の影響をコンテナ発行分に限る。
- 許可IPはコンテナ起動時の解決で固定され、CDNのIP変動時は再起動が要る。
- 開発環境の変更（ツール追加・バージョン更新）がイメージ再ビルドを伴い、ホスト直編集より重くなる。
- 定期収集（cron）はホスト側で従来どおり動く。コンテナはあくまで開発セッションの境界であり、収集経路の隔離は対象外。
- Docker（rootful）の導入自体がホストにrootデーモンを増やす。rootless podmanへの置き換えは、devcontainerツール群との相性問題が解消したら再検討してよい。
