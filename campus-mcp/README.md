# CIT Campus MCP 0.1.8

macOS向けのCITポータル読み取り専用MCPサーバーです。旧wrapperを保全し、Downloadsのr1.7（0.1.7）のSSO/MFA/TOTP実装を引き継いでいます。過去に報告されたr1.8の実体は確認できなかったため、今回の版を **0.1.8** としました。v1.9.0やリリースタグの公開は行っていません。

2026-11-10に正規のMFAログイン、再起動後のSSO復元、実際のstdio経由の掲示板・時間割・出欠・成績取得を確認しました。詳細は [検証結果](docs/TEST_RESULTS.md) を参照してください。

## インストール

実機検証環境: macOS 26.6.2 / Apple Silicon / Python 3.12.14 / MCP SDK 2.3.0。パッケージ要件はPython 3.10以上、推奨は3.12です。3.12/3.13のmacOS・Linux合成テストをCIに設定しています。ほかのmacOS、Intel Mac、Python 3.10/3.11/3.14/3.15の実接続は未検証です。

直下のsetup.pyは旧wrapper用です。MCPはサブディレクトリからインストールします。

```bash
git clone https://github.com/issa06/cit-portal-wrapper.git
cd cit-portal-wrapper
git switch codex/campus-mcp-stabilization
cd campus-mcp
uv sync --locked --extra dev --no-editable --python 3.12
```

uvを使わない場合は `./scripts/bootstrap_macos.sh` でPython 3.12とpipからインストールできます。ただしuv.lockによる固定は適用しません。

macOSのhiddenフラグ付き `.pth` がPythonから無視される現象を実機で確認したため、通常インストールを採用しています。ソース更新後はインストールも更新してください。

```bash
uv sync --locked --extra dev --no-editable --reinstall-package cit-campus-mcp
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
```

## 認証とセッション

```bash
.venv/bin/cit-campus-keyring
.venv/bin/cit-campus-login-test portal --trace
```

既存のmacOS Keychainサービス `cit-campus-mcp` を使います。アカウント名は `portal.user_id`、`portal.password`、`portal.totp_secret` です。TOTPはポータルがMFAを要求した時に必要です。複数TOTP登録がある場合の既定ラベルは `Python`。別ラベルには `CIT_PORTAL_TOTP_CREDENTIAL_LABEL` を指定します。パスワードの前後の空白は除去しません。

`CIT_PORTAL_USER_ID`、`CIT_PORTAL_PASSWORD`、`CIT_PORTAL_TOTP_SECRET` による環境変数方式も維持しています。値を診断・ログ・Gitへ出力しないでください。環境ファイルは自動で読み込みません。

Cookieキャッシュは従来と同じ `~/.config/cit-campus-mcp/portal-session.json` です。ディレクトリ0700・ファイル0600で保存し、一時ファイルは書き込み前に権限を制限します。安全でない権限、壊れたJSON、symlinkは再利用しません。安全な既存v2キャッシュを継続利用できます。

認証はプロセス間ロックで直列化します。失効したUPRXの代わりにKeycloakのSSOを先に再利用し、明確に認証が要求された時だけ通常のログインへ戻ります。UPRX復元先が500を返す場合も、パスワードなしで一度SSO再構築を試します。通信障害だけでCookieを削除しません。TOTPはサーバー時刻を使い、再試行は別の時間窓で最大2回です。`--force` は必要な診断時にだけ使用してください。

`--trace` は動作状態と数値のみです。`--debug-html` は指定した新規ファイルへ0600で書きますが、個人情報を含み得るためGitHubへ送らないでください。通常のスモークテストではHTMLを保存しません。

## Mac版Codex

```bash
.venv/bin/python scripts/configure_codex.py
.venv/bin/python scripts/smoke_mcp.py
# 既存Keychainを使った本人アカウントの読み取り専用テスト
.venv/bin/python scripts/smoke_mcp.py --live
```

設定スクリプトは `~/.codex/config.toml` に次の資格情報を含まないブロックだけを追加します。他の設定を保持し、異なる同名設定は上書きしません。追加差分と削除方法をコードで確定してから書き込み、秘密値を含む設定全体のバックアップは作りません。

```toml
[mcp_servers.cit-campus]
command = "/ABSOLUTE/PATH/cit-portal-wrapper/campus-mcp/scripts/run_mcp.sh"
startup_timeout_sec = 20
tool_timeout_sec = 65
```

復旧は `.venv/bin/python scripts/configure_codex.py --remove` で管理ブロックだけを除去できます。移設する場合は移動前に除去し、移動後に再登録してください。通常はMac再起動後も同じ絶対パスとKeychainで再利用できます。

CLIの登録確認と、**その設定のランチャー**を2回別プロセスで起動したinitialize/list/statusは検証済みです。この作業中のデスクトップチャットには新サーバーが動的追加されていないため、アプリのツール表示・モデルによる選択は新しいチャットまたはアプリ再起動後に確認してください。

接続障害時は、まず `smoke_mcp.py` で認証せず起動・列挙を確認し、その後 `cit-campus-login-test portal --trace` を使用します。依存が見つからない場合は通常インストールを再実行します。他のMCP設定やCookieを一括削除しないでください。設定は [OpenAI公式MCPドキュメント](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) に基づきます。

## MCPツール

既存12ツールの名前・引数と成功時のlist/dict形式を維持しています。SDKは構造化JSONも返します。失敗は `isError=true` と `structuredContent.error = {code, retryable}` で返し、例外原文やURL、学籍情報を含めません。成功応答は最大128KiB。超える場合は切り捨てず `RESPONSE_TOO_LARGE` を返します。

| ツール | 内容 | 実機確認 |
| --- | --- | --- |
| `portal_status` | 掲示メニューでセッションを確認 | PASS |
| `portal_get_notices(full=False)` | タイトル・日付・カテゴリ・表示アイコン、全件表示・ページ送り | PASS（通常/全件） |
| `portal_get_timetable` | 週次の曜日・時限・科目・教員・教室・単位表示、集中講義 | PASS |
| `portal_get_attendance` | 状態の正規化、科目別独自件数集計、欠損数 | PASS |
| `portal_get_grades` | 年度・学期・科目・単位表示・評価・GPA対象表示・公開状態 | PASS |
| `portal_get_student_info` | 学籍情報、顔写真を除外 | NOT RUN（合成PASS） |
| `manaba_list_courses` | コース一覧 | NOT RUN（合成PASS） |
| `manaba_list_action_items` | 課題等の参照 | NOT RUN（合成PASS） |
| `manaba_get_page_text(path_or_url)` | manabaページ本文 | NOT RUN（合成PASS） |
| `docs_list_links` | 学生資料のリンク | NOT RUN（合成PASS） |
| `docs_search(query, limit=20)` | 学生資料検索 | NOT RUN（合成PASS） |
| `docs_get_text(url, max_chars=50000)` | HTML/PDF本文 | NOT RUN（合成PASS） |
| `portal_query` | 4種の大学情報の絞り込み・応答ページング・出典・取得日時 | PASS |

`portal_query` の引数:

| 引数 | 制約・意味 |
| --- | --- |
| `kind` | `notices`, `timetable`, `attendance`, `grades` |
| `offset`, `limit` | 0以上 / 1〜200（既定50） |
| `refresh` | 既定false。trueで30秒のメモリキャッシュを更新 |
| `full` | 掲示の全件一覧と提供される次ページ操作を追跡 |
| `category`, `start_date`, `end_date` | 掲示のみ。カテゴリ完全一致 / ISO日付、両端を含む |
| `semester` | 時間割・成績のみ。ポータルの学期ラベルと完全一致 |
| `weekday` | 時間割のみ。ISO曜日1（月）〜7（日） |
| `on_date` | 時間割のみ。ISO日付から曜日の週次パターンを選択 |

成功は `items`, `total`, `offset`, `next_offset`, `fetched_at`, `source`, `kind`, `status` を返します。`fetched_at` はキャッシュでも元の取得時刻を保持します。認識できる空一覧・フィルター結果は `status=empty`、未公開は `DATA_UNAVAILABLE`、想定外DOMは `STRUCTURE_CHANGED` と区別します。

メニュー操作と認証は直列化し、最新のJSFフォームとHTTP接続を再利用します。セッションとデータキャッシュは別で、大学データはディスクへ保存しません。GETの502/503/504だけ最大1回、0.5秒以上の待機で再試行します。POST/資格情報/MFAはHTTP層で再送しません。429は `RATE_LIMITED` を返します。1リクエスト20秒、ツール60秒、認証最大12ステップ、掲示最大20ページ/2000件、ダウンロード最大8MiBに制限しています。

キャンセルでMCPループを止めません。進行中の同期HTTPはタイムアウトまで継続し得ますが、次のリクエスト前にキャンセルを確認します。認証ページへの並列アクセスは行いません。

## 既知の制限と移行

- 時間割は明示的な前期・後期等を返します。現在学期を暦から推測しません。必要な `semester` を指定してください。`on_date` は週次パターンであり、休講・祝日・補講の確定情報ではありません。
- `unread_or_highlighted` は表示アイコンで、確実な既読フラグと同一とは扱いません。アイコンがない場合はnullです。掲示全文・発信元・添付の詳細取得は未対応です。詳細表示が既読状態を変える可能性があるため、自動で開いていません。
- 全件ボタンとPrimeFacesの次ページ制御に対応します。合成複数ページ・繰り返し検知は検証済みですが、本人アカウントの複数実ページ巡回は未確認です。未知の制御や上限到達は成功扱いにしません。
- 出欠の `computed_summary` は `summary_source=local_record_count`。大学公式集計ではありません。未知・欠損状態はnullのまま残します。
- 成績の空欄は「履修中」と補完しません。`reported` は掲載された評価であり最終確定を保証しません。`credits` は画面の単位表示で、修得済み単位の独自認定はしません。正式規則を未確認のためGPAを独自計算しません。
- エラーコードは `DATA_UNAVAILABLE`, `STRUCTURE_CHANGED`, `SESSION_EXPIRED`, `AUTHENTICATION_FAILED`, `AUTHENTICATION_LOOP`, `MFA_REQUIRED`, `TIMEOUT`, `NETWORK_ERROR`, `RATE_LIMITED`, `SERVICE_UNAVAILABLE` 等です。HTTPS/ホスト制限はリダイレクトにも適用します。
- manaba・資料系は従来機能を維持しましたが実接続対象外です。操作リンクを開かず読み取り用途で使用してください。
- r1.7からは同じKeychainと安全なv2キャッシュを利用できます。時間割は従来の出欠形式から週次/集中講義形式へ修正しました。欠損値のnull化と機械可読エラーにも利用側で対応してください。

## 将来のChatGPT連携

[公式のカスタムMCP要件](https://developers.openai.com/api/docs/guides/custom-mcp-server) ではSSE/Streaming HTTP、サーバー認証設定、利用者/ワークスペースの権限が必要です。プライベートサーバーにはSecure MCP Tunnelの選択肢もあります。stdio設定をそのままChatGPTに追加できるとは扱いません。

今回はMacローカルのstdioまでです。HTTPエンドポイント、外部公開、Tunnel、ドメイン、ホスティング、デプロイ、大学資格情報の外部移送は行っていません。ChatGPT向けには本人データへのアクセス制御とサーバー認証を別途設計・検証する必要があります。

開発記録: [Audit](docs/AUDIT.md) / [CHANGELOG](CHANGELOG.md) / [検証結果](docs/TEST_RESULTS.md)。旧r1.7は [保存文書](docs/legacy-r1.7.md)。由来とライセンスは [NOTICE](NOTICE.md) とリポジトリのLICENSEを参照してください。
