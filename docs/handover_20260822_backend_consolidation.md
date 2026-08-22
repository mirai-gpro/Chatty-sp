# 引継ぎ文書 — 3バックエンド統合とコールドスタート削減の検討依頼

**作成日**: 2026-08-22
**作成元セッション**: Chatty-sp 初期起動問題（30秒待機 / 2重発火）の根本解決
**引継ぎ先**: LAM/A2E 最新論文の検証・進化 + コスト削減 検討セッション
**ブランチ**: `claude/initial-startup-improvement-sr72o3`

---

## 0. この文書の位置づけ

引継ぎ先セッションに **検討・プランニングを依頼する** ための資料。
本文書に書かれている内容は **すべてコードとログの実測に基づく事実** であり、推論は含めていない。
推論・推定を含む箇所には明示的に「未確認」と記載した。

**本文書はコードを一切変更していない時点でのスナップショットである。**

---

## 1. 依頼事項

### 検討してほしいこと

**3つのバックエンド（`chatty-sp-base` / `travel-sp-base` / `mtg-base`）を1つのCloud Runサービスに統合し、常駐（`--min-instances=1`）させることで、コールドスタート35.3秒を削減する。その具体的な設計とプランニング。**

### なぜこの依頼が生まれたか

1. Chatty-sp の初期起動が半日放置後に **45秒** かかる
2. 内訳を実測したところ **35.3秒（78%）が Cloud Run のコールドスタート**
3. `--min-instances=1` で解消できるが、月 $8.4〜9.7 のコストが発生
4. 3サービスすべてに適用すると **月 $27.81**
5. **3つのバックエンドがほぼ同一コードだったため、統合すれば1サービス分（$8.37）で済む**

ユーザーの指摘：
> 「それで意味がない！、同じような処理なら共有化できるかを検討してからでしょ？」

---

## 2. 測定済みデータ（実測・再測定不要）

### 2-1. 起動時間の実測（Chatty-sp）

| 状態 | コールドスタート | アプリ処理 | 合計 |
|---|---|---|---|
| コールド（半日放置後） | **35.3秒** | 9.7秒 | **45秒** |
| ウォーム | 0秒 | **7.76秒** | **7.76秒** |

コールドスタート35.3秒の内訳（Cloud Run ログより）：

| 区間 | 秒数 |
|---|---|
| gunicorn 起動 | 1.1s |
| import群 → `support_core.py:16` | 13.8s |
| GCSプロンプト読み込み（1回目） | 5.2s |
| **`live_api_handler` import（scipy/numpy + TTS×4）** | **14.3s** |
| GCSプロンプト読み込み（2回目・重複） | 0.8s |
| **合計** | **35.3s** |

### 2-2. コールドスタート発生の証拠

```
12:01:57  Starting new instance. Reason: AUTOSCALING - Instance started due to
          configured scaling factors ... or no existing capacity for current traffic.
12:01:58  Default STARTUP TCP probe succeeded after 1 attempt for
          container "chatty-sp-base-1" on port 8080.
12:02:33  （アプリ初期化完了）
```

**注意**: 同時間帯の A2E サービス（`audio2exp-onnx`）は**ウォームだった**。
5チャンクを 1.9秒で処理（12:02:37.557 / 38.213 / 38.984 / 39.210 / 39.400、全て 200 OK）。
コールドスタートしていたのは `chatty-sp-base` のみ。

### 2-3. TCP起動プローブの落とし穴（重要）

`Default STARTUP TCP probe succeeded` は **gunicorn がポートをバインドした 1.1秒時点** で成功する。
`--workers 1` 構成ではアプリモジュールの import はその後 34秒続くため、
**Cloud Run は「準備完了」と判定してトラフィックを流すが、実際にはアプリはまだ起動中**。

→ 起動プローブを HTTP `/health` に変更すれば、デプロイ時の新リビジョンが本当に暖まるまで
   旧リビジョンがトラフィックを処理し続ける（追加コスト $0）。
   `/health` は `chatty-base/app_customer_support.py:723` に定義されており、
   モジュール import が完全に終わらないと応答しない。

---

## 3. 3リポジトリの実測比較

### 3-1. リポジトリ

| プロジェクト | GitHub | Cloud Runサービス名 |
|---|---|---|
| Chatty-sp | `mirai-gpro/Chatty-sp` | `chatty-sp-base` |
| Travel-sp | `mirai-gpro/Travel-sp` | `travel-sp-base` |
| AI-mtg-assistant | `mirai-gpro/AI-mtg-assistant` | `mtg-base` |

**3つとも同一 GCP プロジェクト `ai-avator-492205` / 同一リージョン `us-central1`。**

### 3-2. Cloud Run 設定 — 3つとも完全に同一

`.github/workflows/deploy-cloud-run.yml:71-75`（3リポジトリとも同じ行番号）

| 項目 | 値（3つとも共通） |
|---|---|
| `--memory` | `512Mi` |
| `--cpu` | `1` |
| `--min-instances` | **`0`** |
| `--max-instances` | **`3`** |
| `--timeout` | `3600` |
| `--session-affinity` | なし |
| `--concurrency` | 未指定（Cloud Run既定 = 80） |
| `--cpu-boost` | なし |

Dockerfile CMD も3つとも同一：
```
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app_customer_support:app
```

### 3-3. コード差分（実測行数）

| ファイル | Chatty vs Travel | Chatty vs MTG |
|---|---|---|
| `api_integrations.py` (752行) | **0行（完全一致）** | ファイル自体が存在しない |
| `long_term_memory.py` (429行) | **0行（完全一致）** | **0行（完全一致）** |
| `app_customer_support.py` (1192行) | **43行（3%）** | 1589行（133%） |
| `support_core.py` (907行) | **68行（7%）** | 755行（83%） |
| `live_api_handler.py` (2103行) | 494行（23%） | 1864行（88%） |

---

## 4. 統合可能性の判定

### 4-1. Chatty は Travel の完全なスーパーセット

`live_api_handler.py` の494行差を関数単位で比較した結果、**差分はすべて Chatty 側の追加**。
**Travel にあって Chatty に無い関数・定数は 1つも無い。**

```
Chatty のみに存在:
  SHOP_DISPLAY_NAMES
  _get_shop_display_name() / _load_menu_markdown()
  _is_menu_available() / _search_menu_items()              ← メニュー機能
  RECOMMEND_MENU_DECLARATION / ADD_TO_ORDER_DECLARATION
  SHOW_ORDER_SUMMARY_DECLARATION                            ← 注文サポートのFC宣言
  GOOGLE_SEARCH_DECLARATION                                 ← Google検索FC
  LiveAPISession.on_greeting_trigger()                      ← 30秒ゲート
  LiveAPISession.enqueue_text()                             ← テキスト入力
  LiveAPISession._handle_google_search()

Travel のみに存在:  （なし）
```

`app_customer_support.py` の43行差も同様に全て Chatty 側の追加：
- `@socketio.on('greeting_trigger')` ハンドラ（`:978-986`）
- `@socketio.on('live_text_input')` ハンドラ（`:1018-1032`）
- `shop_id` パラメータ（`:759`, `:795`, `:942`）
- CORS に `"https://chatty-sp.vercel.app"` の1行（`:84`）

### 4-2. `support_core.py` の68行差 = プロンプトのファイル名と挨拶文のみ

アーキテクチャの差ではなく**コンテンツの差**。

| | Chatty | Travel |
|---|---|---|
| concierge系プロンプト | `prompts/order_support_{lang}.txt` | `prompts/concierge_{lang}.txt` |
| lesson系プロンプト | `prompts/chatty_system_{lang}.txt` | `prompts/lesson_{lang}.txt` |
| JSONパース経路 | なし | **あり**（`json.loads` → `concierge_system` キー） |
| 初回挨拶（ハードコード） | `support_core.py:527-533` 相談相手/おしゃべりの相棒 | `:537-543` English conversation coach |
| 再訪挨拶（ハードコード） | `support_core.py:539-543` | `:549-553` |

### 4-3. MTG は別物 — 統合対象外を推奨

`live_api_handler.py` に MTG 固有の実装が大量にある：

```
MTG のみに存在:
  LiveAPISession.inject_document()          ← 会議資料の注入
  LiveAPISession.set_response_gate()
  LiveAPISession._is_addressed()
  LiveAPISession._decide_gate()
  LiveAPISession._reset_gate()              ← 「自分に話しかけられたか」の応答ゲート
  LiveAPISession._v6_bridge_ws_loop()
  LiveAPISession._v6_bridge_enqueue()       ← V6ブリッジWebSocket
  class V6AudioUpperThread(threading.Thread) ← オーディオデバイス直接キャプチャ
```

- Socket.IO イベントも別系統（`mtg_doc_action`）
- `support_core.py` は 246行のみ（Chatty 907行）
- `api_integrations.py` が存在しない
- `agenda_loader.py` / `transcript_logger.py` / `transcript_recorder.py` という固有ファイルを持つ

**MTG の統合は「共有化」ではなく「作り直し」に近い規模。**
検討の結果として除外する判断もありうるが、判断は引継ぎ先に委ねる。

---

## 5. 統合の下地は既に出来ている（3つの発見）

### 発見① Chatty の CORS には既に Travel が入っている

```python
# chatty-base/app_customer_support.py:79-86
allowed_origins = [
    "https://gourmet-sp-two.vercel.app",
    "https://gourmet-sp.vercel.app",
    "https://gourmet-sp3.vercel.app",
    "https://travel-sp.vercel.app",      # ← すでに許可済み
    "https://chatty-sp.vercel.app",
    "http://localhost:4321"
]
```

### 発見② Chatty の `prompts/` には Travel のプロンプトも同梱されている

```
chatty-base/prompts/
  chatty_system_ja.txt   order_support_ja.txt          ← Chatty用
  concierge_ja.txt       lesson_ja.txt  concierge_en.txt  ← Travel用（すでに同梱）
  support_system_{ja,en,zh,ko}.txt

travel-sp/support-base/prompts/
  concierge_ja.txt  lesson_ja.txt  concierge_en.txt
  support_system_{ja,en,zh,ko}.txt
```

**Chatty 側は Travel のプロンプトを完全に含んでいる。**

### 発見③ フロントのバックエンド切替は環境変数1つ

```astro
// Chatty-sp/src/pages/concierge.astro:6
// Travel-sp/src/pages/concierge.astro:6   （完全に同一）
const apiBaseUrl = import.meta.env.PUBLIC_API_URL || '';
```

Vercel の `PUBLIC_API_URL` を差し替えるだけで、Travel のフロントを統合バックエンドに向けられる。

---

## 6. 統合作業として想定される項目（叩き台）

引継ぎ先で精査・修正してほしい。

| # | 作業 | 対象 |
|---|---|---|
| 1 | テナント識別子の追加 | フロントから `tenant: 'chatty' \| 'travel'` を `live_start` / `/api/session/start` のペイロードで送る |
| 2 | プロンプトファイル名の分岐 | `support_core.py:75-90`（GCS）、`:119-135`（ローカル）をテナントで切替 |
| 3 | 挨拶文の分岐 | `support_core.py:527-553` のハードコード挨拶をテナントで切替 |
| 4 | JSONパース経路の取り込み | Travel の concierge プロンプトは `json.loads` → `concierge_system` キー取得の分岐がある。Chatty には無いので統合側に取り込む |
| 5 | `shop_id` の扱い | Chatty のみの機能。Travel から渡されなければ空文字なので無害（要検証） |
| 6 | Vercel 環境変数切替 | Travel-sp の `PUBLIC_API_URL` を統合バックエンドのURLに |
| 7 | Travel リポジトリの扱い | `support-base/` をデプロイ対象から外す（workflow の `paths:` から除外 or workflow 自体を無効化）。フロントのみ残す |
| 8 | Cloud Run 設定変更 | `--min-instances=1` / `--max-instances=1` / 起動プローブを HTTP `/health` に |

---

## 7. `--max-instances=1` が必要な理由（3リポジトリ共通）

統合後も含め、**このアプリ群は1インスタンス前提の設計**。根拠4点：

### 根拠① Socket.IO が複数インスタンスをまたげない

```python
# 3リポジトリとも同一
socketio = SocketIO(app, cors_allowed_origins=allowed_origins,
                    async_mode='threading', logger=False, engineio_logger=False)
```
`message_queue=` が**3リポジトリのどこにも指定されていない**（grep 済み、ヒット0）。
Flask-SocketIO で複数インスタンスに跨るには Redis 等の message_queue が必須。

### 根拠② フロントが polling → WebSocket アップグレード方式

```typescript
// core-controller.ts:256-264
// ★修正: Socket.IO接続設定に再接続オプションを追加（transportsは削除）
this.socket = io(this.apiBase || window.location.origin, {
  reconnection: true, reconnectionDelay: 1000,
  reconnectionAttempts: 5, timeout: 10000
});
```
`transports` 未指定 = socket.io-client のデフォルト（polling先行）。
polling中の各HTTPリクエストが別インスタンスに振られると engine.io セッションが見つからず失敗。
デプロイコマンドに `--session-affinity` は無い。

### 根拠③ 状態がすべてプロセス内メモリ

| 変数 | Chatty | Travel | MTG |
|---|---|---|---|
| `active_live_sessions = {}` | `app:747` | `app:746` | `app:681` |
| `greeted_client_sids = set()` | `app:748` | `app:747` | なし |
| `active_streams = {}` | `app:1039` | `app:1008` | なし |
| `_SESSION_CACHE = {}` | `support_core:39` | `support_core:39` | `support_core:43` |

`SupportSession` クラスのコメントは「サポートセッション管理 (RAM版)」。

### 根拠④ 具体的な壊れ方

`greeted_client_sids` は初期挨拶の2重発火を防ぐ唯一の仕組み：

```python
# app_customer_support.py:946-949
if client_sid in greeted_client_sids:
    live_session.session_count = 1
else:
    greeted_client_sids.add(client_sid)
```

2台目に振られると空の set を見るため、**挨拶済みのクライアントが再度挨拶フローに入る**。
`_SESSION_CACHE` も同様で、`/api/session/start` を1台目、`/api/chat` を2台目が処理すると会話履歴が消える。

### 容量の上限

| 層 | 設定 | 同時処理数 |
|---|---|---|
| Cloud Run concurrency | 未指定＝既定80 | 80 |
| gunicorn | `--workers 1 --threads 8` | **8** |

`async_mode='threading'` のため WebSocket 1本 = gunicorn スレッド1本を占有し続ける。
**実質の同時接続上限は7〜8人。** Cloud Run は80まで捌けると思っているので2台目を立てず、
9人目以降はソケットの backlog で待たされる。
同時8人を超える見込みが出たら `--threads` を増やすか、Redis で `message_queue` 対応が必要。

---

## 8. コスト試算

### 単価（us-central1 = Tier 1、リクエストベース課金）

| 項目 | 単価 |
|---|---|
| CPU（アクティブ） | $0.000024 / vCPU秒 |
| メモリ（アクティブ） | $0.0000025 / GiB秒 |
| **CPU（アイドル＝min-instances）** | **$0.0000025 / vCPU秒** |
| **メモリ（アイドル）** | **$0.0000025 / GiB秒** |
| 無料枠 | 180,000 vCPU秒 / 360,000 GiB秒 / 200万リクエスト（月） |

> **単価は要再確認。** Google公式ページ（https://cloud.google.com/run/pricing）は
> WebFetch 時に truncate されたため、以下2ソースの突き合わせ値を採用している：
> - oneuptime（アイドル $0.00000250/vCPU秒・$0.00000250/GiB秒、1vCPU+512Mi で $0.0135/時）
> - cloudchipr（月 $10〜12）
> **請求前に GCP の料金計算ツールで確定させること。**

### 1サービスあたり（cpu=1 / memory=512Mi / 30日常駐）

```
常駐秒数 = 60 × 60 × 24 × 30 = 2,592,000 秒

CPU  : 2,592,000 vCPU秒 × $0.0000025 = $6.48
メモリ: 1,296,000 GiB秒  × $0.0000025 = $3.24
                            小計 = $9.72 / 月（無料枠適用前）
```

### 構成別の月額

**3サービスとも同一プロジェクト = 同一請求先のため、無料枠は1回しか引けない。**

| 構成 | サービス数 | 月額（無料枠適用後） |
|---|---|---|
| 統合せず3サービス個別に常駐 | 3 | **$27.81**（約4,200円） |
| Chatty + Travel を統合（MTGは別） | 2 | **$18.09**（約2,800円） |
| **3つすべて統合** | **1** | **$8.37**（約1,300円） |
| Chatty のみ常駐（他は据え置き） | 1 | $8.37（約1,300円） |

計算式（3サービスの場合）：
```
CPU  : 7,776,000 − 180,000（無料枠）= 7,596,000 × $0.0000025 = $18.99
メモリ: 3,888,000 − 360,000（無料枠）= 3,528,000 × $0.0000025 =  $8.82
                                                合計 = $27.81
```

### 見落としやすい変動費 — WebSocket 常時接続

リクエストベース課金では、開いている WebSocket は「処理中のリクエスト」＝**アクティブ課金**。

```
(1 vCPU × $0.000024) + (0.5 GiB × $0.0000025) = $0.0000253/秒 = $0.091 / 時
                                  min-instances のアイドル $0.0135/時 の 約6.7倍
```

タブを8時間開きっぱなしにすると **$0.73**（= min-instances 2日分より高い）。
`--timeout=3600` なので1リクエストは最大1時間だが、`reconnection: true` で再接続される。
**無操作N分後に `live_stop` + socket切断する仕組みが、min-instances より大きいコスト削減になりうる。**

---

## 9. コスト以外に効く統合のメリット

いま Chatty-sp で計画している起動時間短縮の修正は、**Travel-sp にも同じものが必要**。

| 修正項目 | Chatty | Travel | MTG |
|---|---|---|---|
| 2重 `resetAppContent()`（`core-controller.ts:94` と `:106`） | あり | **あり（同一行番号）** | なし（フロント構造が別） |
| 起動時TTS `_generate_cached_audio()` | `live_api_handler.py:101` | **`:96`** | **なし** |
| 重複 `load_system_prompts()` | `app:126` + `support_core:165` | **`app:125` + `support_core:175`** | `support_core:145` のみ |
| `from scipy.signal import resample_poly` | `:24` | `:19` | `:23` |
| 30秒ゲート `_greeting_trigger_event.wait(…, 30.0)` | **`:761`** | なし | なし |

**統合しなければ、同じ修正を2回実施し、2回検証することになる。**

---

## 10. 起動時間短縮の候補（統合とは独立に効く）

35.3秒に対する対策。**すべて追加コスト $0。**

| 対策 | 対象 | 見込み |
|---|---|---|
| `_generate_cached_audio()` をバックグラウンド化 | `live_api_handler.py:101` — TTS `synthesize_speech()` を4回**直列でネットワーク往復**している | 14.3秒区間から除去（幅は要計測） |
| legacy `google.generativeai` 撤去 | `support_core.py:16, 33, 34` — `:34` の `model` オブジェクトは全コードから未使用（grep確認済み） | 13.8秒区間の一部 |
| 重複 `load_system_prompts()` 削除 | `app_customer_support.py:126`（`support_core.py:165` と重複） | **−0.8秒（実測）** |
| GCS `blob.exists()` 廃止 | `download_as_text()` の例外で判定 → 往復が半減 | **−約2.6秒** |
| 起動プローブを HTTP `/health` に | workflow に `--startup-probe` 追加 | デプロイ時のコールド隠蔽 |

**訂正事項（誤解しやすい）**: `requirements.txt` の `anthropic` / `pyiceberg` / `firestore` は
どこからも import されていない（grep確認済み）。削除は**イメージサイズとビルド時間**には効くが、
**起動時の import 時間には効かない**（読み込まれていないため）。

---

## 11. 未確認事項 — 引継ぎ先で確認が必要

| # | 項目 | なぜ未確認か |
|---|---|---|
| 1 | **`PROMPTS_BUCKET_NAME` が3リポジトリで同一か** | GitHub Secrets のため値が読めない。別バケットなら統合時にプロンプトファイルの集約が必要 |
| 2 | Cloud Run 料金の正確な単価（特にアイドル単価） | 公式ページが WebFetch で truncate。料金計算ツールで確定させること |
| 3 | Travel-sp / AI-mtg の稼働状況 | α版テストに使っているか。使っていないサービスを常駐させる必要はない |
| 4 | 統合後の `shop_id` の挙動 | Travel から渡されない場合に空文字で無害か、実際に検証が必要 |
| 5 | A2E サービス（`audio2exp-onnx`）の min-instances 設定 | 同一プロジェクトなら無料枠を食い合う。別チャットで実証テスト中とのこと |
| 6 | `--concurrency` を明示すべきか | 現状は Cloud Run 既定80 vs gunicorn 8 のミスマッチ |

---

## 12. 既知の別問題（統合の判断材料。今回のスコープ外）

このセッションのログ調査で見つかったもの。**修正はしていない。**

| # | 問題 | 証拠 |
|---|---|---|
| 1 | **Supabase の DNS 解決が完全に失敗** | ログに `[ERROR] [LTM] ...: [Errno -2] Name or service not known`（2回とも）。長期記憶が全く機能していない |
| 2 | GCS プロンプトファイルが6本欠損 | `order_support_{en,zh,ko}.txt` / `chatty_system_{en,zh,ko}.txt`。concierge/lesson は実質 ja のみ |
| 3 | `[A2E Sync] frameIdx=169/170` が turn_complete 後 100秒以上固着 | ブラウザコンソールログ。WebGL警告256件 + "too many errors" |
| 4 | `/health` が `audio2exp: not configured` を返す | 環境変数名の不一致：workflow は `A2E_SERVICE_URL` を渡すが `app_customer_support.py:65` は `AUDIO2EXP_SERVICE_URL` を読む。表示のみの影響 |

---

## 13. このセッションで確定した「初期起動問題」の事実（参考）

統合の設計時に前提として知っておく必要があるため記載。**これらの修正は Chatty-sp 側のセッションで継続する。**

### 13-1. 実証済み（LiveAPI 22セッションの実測）

- **ダミーのユーザー発話は `gemini-3.1-flash-live-preview` で必須**
  ダミー無しの全ケース（T1/T2/T2a/T2b/T2c）で20秒間サーバーイベント0。
  ダミー有り（T3/T4）は約0.6秒で発話。
  公式ガイドの「include a prompt asking it to greet the user」は 3.1 では**効かない**。
  理由づけ型プロンプト（「なぜLLMから話す必要があるか」を説明する形）でも結果は同じ＝**仕組みの問題であって文言の問題ではない**。
- **固定の挨拶文は不要**
  T5/T5b は2/2で「田中さん」と名前を呼んだ。T5c は名前が無い場合に自然に名前を尋ねた。

### 13-2. 2重発火は「バグ」ではなくリップシンクを成立させている

`core-controller.ts:94` と `:106` の2回の `resetAppContent()` により LiveAPI セッションが2つ作られる。

| | セッションA（1回目） | セッションB（2回目） |
|---|---|---|
| 分岐 | `session_count == 1` → 初回挨拶ブランチ（`live_api_handler.py:755-764`） | `session_count` 1→2 → 再接続ブランチ（`:780`） |
| 30秒ゲート | 通る | **通らない** |
| `_is_initial_greeting_phase` | `True` → 壊れている `_send_a2e_ahead()` の一括送信パス | **`False` → 通常のストリーミングパス** |
| 最期 | `live_stop` で `stop()` される | 生き残る |
| ユーザーに聞こえるか | **聞こえない** | **これが挨拶** |

停止後は `live_api_handler.py:905` の `while not self.needs_reconnect and self.is_running:` が
回らないため、セッションAの音声は1バイトも届かない。
`room=self.client_sid` で emit しているので（21箇所すべて）、ユーザーが2重に聞くことはない。

### 13-3. 30秒ゲートは体感時間に寄与していない（が、無駄ではある）

`live_api_handler.py:754-764` は固定待機ではなく**上限30秒のタイムアウト**。
設計意図は「アバター準備完了を待ってから挨拶」。

しかし `greeting_trigger` を送るのは `concierge-controller.ts:71`（`linkLamAvatar()` 内）で、
これは `await super.init()`（= `resetAppContent()` ×2）が**完了した後**に呼ばれる。

```
セッションA: [30秒フル待機] ──タイムアウト──→ ダミー送信 ──→ is_running=False で破棄
セッションB: 待機なし ──即座に発話──→ ユーザーに届く（← これが挨拶）
greeting_trigger: ──────────────→ セッションB の、誰も待っていないイベントをセット
```

**「アバター準備完了を待ってから挨拶」という設計は一度も機能していない。**
体感45秒への寄与は**0秒**。ただし毎回30秒空回りしている。

### 13-4. 修正順序の制約（重要）

2重発火を先に消すとセッションAが唯一のセッションになり、
`_is_initial_greeting_phase = True` のまま壊れている一括送信パスに乗る＝**リップシンクが壊れる**。

```
Step 1  A2E経路の一本化
        live_api_handler.py:949-953 と :1020-1022 の
        _is_initial_greeting_phase 分岐を削除
        → 現状は無害（セッションBは False なので元から通っていない）
        → これが無いと Step 2 でリップシンクが壊れる
          ↓
Step 2  core-controller.ts:106 の2回目 resetAppContent() を削除
        → セッションが1つになる
        → 30秒ゲートが初めて正常動作する
          ↓
Step 3  30秒ゲートの扱いを決める
        → この時点で初めて「本当に不要か」を判断できる
```

---

## 14. 制約事項 — 必ず守ること

### CLAUDE.md の規定（`/home/user/Chatty-sp/CLAUDE.md`）

- **Gemini LiveAPI / LAM・A2E は Claude の知識ベース外。推論で語らない。コードと仕様書とユーザー確認のみ**
- **コード修正は必ずユーザーの許可を得てから**
- **フォールバック禁止**（キーワード検出による代替ロジックは絶対に不可）
- **1修正1コミット。2回修正して直らなかったら手を止めてユーザーに報告**
- **変更禁止ファイル**: `CLAUDE.md` / `docs/` 配下 / `DESIGN_SPEC_PHASE1.md` / `api_integrations.py` / `long_term_memory.py` / PWA設定 / `i18n.ts` / **`.github/workflows/`**

### デプロイの地雷

- `.github/workflows/deploy-cloud-run.yml` の trigger は
  `push: branches: [main, 'claude/*'] paths: ['chatty-base/**', '.github/workflows/deploy-cloud-run.yml']`
  → **`chatty-base/` 配下への push は即 Cloud Run 本番デプロイになる**
- `docs/` への push はデプロイをトリガーしない
- Vercel は `main` を Production Branch としてデプロイする
  （過去に `main` へのマージで本番が旧状態に巻き戻る事故が発生している）
- プロンプトは **GCS（REST API用）と Python ハードコード（LiveAPI用）の2系統**。片方だけ直すと本番に反映されない

---

## 15. 参照ファイル一覧

### Chatty-sp（`/home/user/Chatty-sp`、ブランチ `claude/initial-startup-improvement-sr72o3`）

```
CLAUDE.md                                     ← 開発ガイド（変更禁止）
docs/09_liveapi_migration_design_v6.md        ← V6統合仕様書（メイン）
docs/10_lam_audio2expression_spec.md          ← A2E仕様
docs/11_a2e_lipsync_implementation_guide.md
docs/13_a2e_lipsync_comprehensive_guide.md
docs/plan_20260822_startup_and_model_migration.md  ← 本セッションの改善計画（rev.2）
docs/handover_20260822_backend_consolidation.md    ← 本文書
DESIGN_SPEC_PHASE1.md
chatty-base/app_customer_support.py
chatty-base/support_core.py
chatty-base/live_api_handler.py
chatty-base/Dockerfile
.github/workflows/deploy-cloud-run.yml
src/scripts/chat/core-controller.ts
src/scripts/chat/concierge-controller.ts
src/scripts/chat/live-audio-manager.ts
tools/test_speak_first.py                     ← LiveAPI発話検証ハーネス
```

### 他リポジトリ（本セッションで clone 済み）

```
/home/user/mirai-gpro/travel-sp     ← mirai-gpro/Travel-sp（public、read-only clone）
/home/user/ai-mtg-assistant         ← mirai-gpro/AI-mtg-assistant（private、attached）
```

### 既知のバグ（本文書作成時点で未修正）

`tools/test_speak_first.py` の `receive_loop()` が `turn_complete` で return するため、
音声が途中で切れて計測値が0バイトになるケースがある（T5c/T5d で発生）。

---

## 16. 引継ぎ先への依頼まとめ

1. **3バックエンド統合の可否と設計を判断してほしい**
   - Chatty ⊃ Travel は確定（§4-1）。MTG を含めるかは判断が必要（§4-3）
   - §6 の作業項目は叩き台。精査・修正を前提としている
2. **統合後の常駐設計を決めてほしい**
   - `--min-instances=1` / `--max-instances=1` / 起動プローブ HTTP `/health`（§7, §2-3）
3. **起動時間短縮そのものも併せて検討してほしい**
   - §10 の5項目は追加コスト $0。統合と独立に効く
4. **コスト削減として WebSocket アイドル切断も検討してほしい**
   - min-instances より大きい削減になりうる（§8末尾）
5. **§11 の未確認事項を潰してほしい**
   - 特に `PROMPTS_BUCKET_NAME` の同一性は統合設計を左右する

**初期起動問題そのもの（§13 の Step 1〜3）は Chatty-sp 側のセッションで継続する。**
統合作業と競合する可能性があるため、着手前にユーザーに確認すること。
