# 初期起動 改善プラン

**作成日**: 2026-08-24
**対象ブランチ**: `claude/initial-startup-improvement-sr72o3`
**位置づけ**: 対照実験（`report_20260824_ab_experiment_results.md`）で方向が確定した後の実装プラン

---

## 0. 確定した方針 — Step 2 を維持する

対照実験（アームA=Step2 / アームB=旧フロー、各条件で実測）とコード精査により、以下が確定した。

| # | 確定事項 | 区分 |
|---|---|---|
| 1 | 2重リセット（`7d16730`）は**戻さない** | **方針決定**（ユーザー合意済み） |
| 2 | Step 2（`36d65df`、2重リセット削除）は**正しい方向** | 同上 |
| 3 | 挨拶は「アバター準備完了まで発生源で止める」ゲートで制御されている | **事実**（コード） |
| 4 | 旧フローがリップシンクを壊すのは、再接続ブランチに③のゲートが**無い**から | **事実**（コード） |

### 背景（なぜ Step 2 が正しいか）

- 5か月前、旧フロー（2重リセット）が機能していたのは、**バックエンドが遅く、
  アバター初期化が音声より先に間に合っていたから**（アバターがレースに勝っていた）
- ONNX 化と保温でバックエンドが高速化（アプリ起動 3〜5 秒で挨拶開始）した結果、その偶然は崩れた
- 旧フローに戻すと、アバター準備前に音声が始まり、**リップシンクが構造的に動かなくなる**
  （アームBで実測：フレームは溜まるが rAF ループが未起動で誰も読まない）

---

## 1. 制御機構の現状（事実・コード確認済み）

「アバター準備完了まで A2E と音声をフロントに流さない」制御は、**既に存在する。**
しかも発生源（バックエンド）で止めており、フロント側バッファより堅牢である。

```
初回挨拶（session_count==1）:
  emit('live_ready')
  _greeting_trigger_event.wait(30秒)          ← live_api_handler.py:789
  send_client_content(挨拶)                    ← 待機が解けて初めて Gemini に生成させる
```

- `greeting_trigger` は、フロントの `linkLamAvatar()` が `controller.initialize()`
  （アバター準備）を await し終えてから送信（`lesson-controller.ts:60-68` / `concierge-controller.ts`）
- アバター準備前は Gemini に挨拶を生成させないため、**音声も A2E も生成されず、流れようがない**

### この制御の穴（改善対象）

`greeting_trigger` の送信には**失敗経路が3つあり、リトライがない**（`lesson-controller.ts:55-72`）。

| 失敗経路 | 現状の挙動 |
|---|---|
| `window.__lamAvatarController` が undefined | `console.warn` のみ。emit されない |
| `socket.connected === false` | else 節が無い |
| `controller.initialize()` が throw | catch でログのみ |

→ いずれかで `greeting_trigger` が届かないと、ゲートは30秒でタイムアウトし、
　**アバター未準備のまま挨拶が発火する。**制御が破れる。

---

## 2. 改善プラン（優先順位付き）

**すべて `src/` 配下。Cloud Run デプロイは走らない（実証済み）。1修正1コミット。**

| 順 | 施策 | 目的 | 変更箇所 | 変更量 |
|---|---|---|---|---|
| **P1** | `greeting_trigger` 送信経路の確実化 | **制御を保証する**（穴を塞ぐ） | `lesson-controller.ts` / `concierge-controller.ts` | 小 |
| **P2** | アバター zip の先行読込（preload） | アバター準備を速くする（待ち時間短縮） | `LAMAvatar.astro` | 3行 |
| **P3** | `expressionFrameBuffer` のターン終了時クリア | 固着した expression の空回りを止める | `live-audio-manager.ts` | 小 |

### 順序の根拠

- **P1 が最優先。** ユーザーの主眼は「準備完了まで流さない制御」であり、それを**保証**するのが P1。
  P2（速度）より P1（正しさ）が先。
- **P3 は P1・P2 と同時に入れない**（効果の切り分けができなくなる）。P1・P2 の効果確認後に単独で。

---

## 3. 各施策の詳細

### P1: `greeting_trigger` 送信経路の確実化

**対象**: `src/scripts/chat/lesson-controller.ts:55-72`、`concierge-controller.ts`（同構造）

**内容**: `linkLamAvatar()` の**成功時・catch時・controller不在時のすべて**から
`greeting_trigger` を送る。socket 未接続なら `once('connect')` で送る。送信理由をログに残す。

- サーバの `on_greeting_trigger()` は `_greeting_trigger_event.set()` のみで**冪等**（`live_api_handler.py:713-715`）。
  多重送信は無害
- **`reason` をログに残すのが要点。** catch 経路から送ると失敗が見えなくなり、
  `CLAUDE.md` 第4項が禁じる「問題の隠蔽」に近づく。どの経路から送ったかが残れば失敗は可視のまま

**リスク**: アバター初期化に失敗した場合、準備完了前に挨拶が始まりうる。
ただし**現状も30秒後にどのみち始まる**（フェイルオープン）ので、新しい挙動の追加ではない。
**巻き戻しは1コミットの revert。**

**効果測定**: サーバログ `[LiveAPI] greeting_trigger タイムアウト（30秒）` の発生がゼロになること。

### P2: アバター zip の先行読込（preload）

**対象**: `src/components/LAMAvatar.astro:115-120`（`define:vars` スクリプト、HTMLパース時に同期実行）

**内容**: `<link rel="preload" as="fetch">` を3行で注入し、zip のダウンロードを
**現状より数秒早く**開始する（現状は `controller.initialize()` 到達時＝socket/セッション設定後に開始）。

- `crossOrigin` は付けない（同一オリジン。付けると素の fetch と不一致で二重取得を招く）

**効きの範囲（事実）**:

| ケース | 効果 |
|---|---|
| 初回訪問（未キャッシュ・4MB DL） | ダウンロードがボトルネック。**数秒早く用意でき、効果大** |
| 2回目以降（キャッシュ済み） | zip は `cache-control: public, max-age=0, must-revalidate`（実測）。
  毎回 1RTT の再検証。**効果は 1RTT 程度** |

**リスク**: `as`/`credentials` 不一致による二重取得。DevTools Network の `.zip` 行数で判定
（1回=成功、2回=失敗）。**巻き戻しは3行削除。**

**効果測定**: `performance.getEntriesByType('resource')` の `.zip` の `startTime`/`duration` と、
`[LAMAvatar] 3Dアバター初期化完了` の時刻、サーバの `greeting_trigger待機終了 経過=`。

### P3: `expressionFrameBuffer` のターン終了時クリア

**対象**: `src/scripts/chat/live-audio-manager.ts` の `onAiResponseEnded()`

**内容**: 現状 `onAiResponseEnded()` は `isAiSpeaking=false` と最終フレームの jawOpen ゼロ化のみで、
**バッファをクリアしない**。その結果 `getCurrentExpressionFrame()` が最終フレームを返し続け、
52要素の計算が毎レンダリングフレーム空回りする（実測で `frameIdx=142/143` の固着を観測）。

- **Step 1/2 以前から存在する別問題。** P1・P2 と**同時に入れない**（切り分け不能になる）

---

## 4. この修正後の方向性（残課題）

P1〜P3 は「アバターが間に合わない」問題への対処である。以下は**別系統の未解決課題**として残す。

### 方向A: アームA の 2/5 異常（Gemini が音声を返さない / 26秒遅延）

- **区分: 未特定（上流）。** サーバの `sc.model_turn.parts` に音声パートが来ない、
  または26秒遅れる事象が、Step 2 適用後の4実行中2回で観測された
- **P1〜P3 では直らない**（これはアバターの問題ではなく Gemini 応答の問題）
- **方針**: まず「更に考察と仮説 → 検証」が必要（ユーザー認識）。当面は**検出のみ**行う
  （サーバログで `初期あいさつトリガー送信` の直後1秒以内に `[A2E] chunk 0` が続くかを見る。
  コード変更・デプロイ不要）
- **自動リトライは入れない**（原因未特定のまま再送で覆うのは `CLAUDE.md` 第4項のフォールバックに該当）
- P1〜P3 投入後、この頻度が**変わらないこと**を確認する（変わったら、それ自体が手がかり）

### 方向B: リップシンクのタイムライン基準ずれ（独立事項）

- **区分: 事実（仕様と実装の不一致）。** 仕様 `docs/13` §2.2 は
  「`firstChunkStartTime` が音声再生開始時刻と一致」を要件とするが、
  実装は `live_expression` chunk=0 到着時に基準を再設定するため、A2E の HTTP 往復分だけ後ろにずれる
- 実測（挨拶ターン）: 2.4〜9.3 フレーム（@30fps）の遅れ。ユーザー評価「1〜2フレは許容、3以上は違和感」
- **本件（アバター準備）とは独立。** P1〜P3 が落ち着いてから単独で扱う

### 方向C: 起動時間そのものの短縮

- コールドスタートは保温で解消済み（min-instances=1）
- P2（zip 先行）が初回訪問の起動短縮に寄与
- 追加の短縮余地（`sleep(300)` の意図確認など）は優先度低

---

## 5. 検証方法

対照実験と同じ方式。**本番に一切触れない。**

- `git worktree` で対象ブランチを別フォルダに展開
- `.env` に `PUBLIC_API_URL=<本番 Cloud Run の URL>` を1行（※URLは要確認。リポジトリに一次資料なし）
- `npm run build && npm run preview -- --port 4321`（`npm run dev` ではなく preview。本番と同じバンドルで測る）
- `http://localhost:4321` は `app_customer_support.py:85` の CORS 許可リストに既存
- **ポートは必ず 4321**（`127.0.0.1:4321` は別オリジン扱いで通らない）
- Console は「Preserve log」有効で全文保存

### 記録項目（1起動1行）

| 項目 | 用途 |
|---|---|
| 条件（初回 / キャッシュ済み） | P2 の効きの切り分け |
| `[Socket] connect transport=` / `upgrade →` | 配送層の確認 |
| `[LAMAvatar] 3Dアバター初期化完了` の時刻 | アバター準備完了時刻 |
| `greeting_trigger待機終了 経過=`（サーバ） | ゲート解除タイミング |
| 挨拶ターンの `[Sync] GAP dist max=…` | 音声途切れの有無 |
| アバターが挨拶終了前に画面に出たか | UX の主観（主目的の判定） |

---

## 6. 制約・禁止事項（CLAUDE.md 準拠）

| 項目 | 内容 |
|---|---|
| コード修正 | **必ずユーザーの許可を得てから。** 1修正1コミット。2回直らなければ手を止めて報告 |
| 変更禁止ファイル | `CLAUDE.md` / `docs/`（本プラン等の新規作成は可） / `DESIGN_SPEC_PHASE1.md` /
  `api_integrations.py` / `long_term_memory.py` / PWA設定（`astro.config.mjs` の workbox） / `i18n.ts` / `.github/workflows/` |
| フォールバック禁止 | 原因未特定のまま再送・代替ロジックで覆わない（方向A のリトライを入れない理由） |
| デプロイ | `chatty-base/**` への push = 即 Cloud Run 本番デプロイ。`src/` のみ = Vercel のみ |
| A2E パラメータ | バッファ閾値（`docs/09` §4.3）は実証済み・変更禁止 |
| 知識ベース外 | Gemini LiveAPI / LAM・A2E は推論での断定禁止 |

---

## 7. 事実と仮説の分離

### 事実（一次資料あり）

| # | 内容 | 出所 |
|---|---|---|
| F1 | 挨拶は `greeting_trigger` ゲートで発生源制御されている | `live_api_handler.py:789` |
| F2 | `greeting_trigger` は controller.initialize() 完了後に送信 | `lesson-controller.ts:60-68` |
| F3 | 送信に3失敗経路・リトライなし | `lesson-controller.ts:55-72` |
| F4 | 再接続ブランチにはゲートが無い | `live_api_handler.py:816-834` |
| F5 | `onAiResponseEnded` はバッファをクリアしない | `live-audio-manager.ts` |
| F6 | rAF ループはアバター初期化後に開始 | `LAMAvatar.astro:177` / `audio-sync-player.ts` |
| F7 | zip は `max-age=0, must-revalidate` | 実測（レスポンスヘッダ） |
| F8 | Step 2 適用後4実行中2回で音声欠落/遅延 | 対照実験の生ログ |

### 仮説（未実証）

| # | 内容 | 状態 |
|---|---|---|
| H1 | 旧フローが効いていたのはバックエンドが遅かったから | 機構はコードと整合。ONNX速度値は当リポジトリで未検証 |
| H2 | GAP 1059ms はアバター読込とのメインスレッド競合 | 1サンプル。断定不可 |
| H3 | アームA の 2/5 は上流（Gemini）の問題 | 症状は上流を示すが原因未特定 |
| H4 | P2 は初回訪問で症状に効く／2回目以降は効果限定 | 効きの範囲は事実だが、症状への効果は要実測 |

---

## 8. 未解決一覧

| # | 項目 | 状態 |
|---|---|---|
| 1 | アームA の 2/5 異常 | **未特定**（上流）。方向A で検出のみ |
| 2 | GAP がアバター競合か | **未確認**（1サンプル） |
| 3 | `getInstance()` 内部（DL/展開/GPU の配分） | **未確認**。P2 の効果予測に影響 |
| 4 | リップシンク基準ずれ | **事実（仕様不一致）**。方向B で別途 |
| 5 | 本番 `PUBLIC_API_URL` の URL | 検証に必要。リポジトリに一次資料なし。要ユーザー確認 |
| 6 | `sleep(300)` の意図 | 不明。優先度低 |
