# 引継ぎメモ: Chatty-sp 起動時 30秒待機 + 2回発火問題

**作成日**: 2026-05-24
**元セッション**: Opus 4.7 (`claude-opus-4-7[1m]`, 知識カットオフ 2026-01)
**用途**: 別モデル（Fable 5 / Opus 5 等）で再考・プランニングを依頼するための引継ぎ

---

## 0. まず最初に読むこと（絶対）

このプロジェクトには **`/home/user/Chatty-sp/CLAUDE.md`** があります。**最初に必ず全文を読んでから、以下の指示に着手してください。**

CLAUDE.md の核心ルール（要約、原文で必ず確認）：

1. **知識ベース外の技術に対して推論するな。** LAM/A2E（アリババ研究所、2025年10月論文）と Gemini LiveAPI（2025年12月末）は Claude の知識ベース外。「一般的には○○」で答えると必ず外す。
2. **仕様書を先に読め**（`docs/09_liveapi_migration_design_v6.md` メイン、`docs/旧版仕様書/` 参考）
3. **勝手に修正するな**（コード修正はユーザー許可必須）
4. **フォールバック禁止**（本プロジェクト最大の地雷。「動かないから昔の方式で代替」は絶対NG）
5. **2回修正して直らなかったら手を止めてユーザーに相談**
6. **「気を利かせる」な。指示された通りにやれ**
7. Claude の役割は「道具」。分析・診断・改善提案は Claude にやらせない。修正指示はユーザーが出す。

**過去に Claude が「気を利かせて推論した」結果、累計20日間・300時間超の泥沼化を引き起こした実績があります。これがまさに繰り返しかけている状況です。**

---

## 1. プロジェクト概要

- **アプリ**: Chatty-sp（グルメAIコンシェルジュ + 派生アプリ Travel-SP 等）
- **フロント**: Astro + TypeScript（Vercel）
- **バック**: Flask + Socket.IO / Python（Cloud Run）
- **AI**: Gemini LiveAPI（音声）、Gemini REST API（テキスト）
- **アバター**: LAM/A2E（Audio2Expression）— 52個のblendshape係数で低遅延リップシンク
- **A2E サービス**: 別 Cloud Run（`audio2exp-service`）、コールドスタート約65分（モデルロード）
- **リポジトリ**: `mirai-gpro/chatty-sp`
- **GCP プロジェクトID**: `ai-avator-492205`（プロジェクト番号: 281169010109）

---

## 2. 現在解決したい問題

### 2-1. 問題の症状
**Chatty-sp を起動すると、毎回きっかり 30 秒のコールドスタート待機が発生する。**

### 2-2. 特定済みの直接原因

#### 原因A: バックエンドの 30 秒 greeting_trigger ゲート
- **ファイル**: `chatty-base/live_api_handler.py:729-733`
- **コード**:
  ```python
  # ★ 案B: アバター準備完了を待つ（最大30秒、threading.Event）
  triggered = await asyncio.get_event_loop().run_in_executor(
      None, self._greeting_trigger_event.wait, 30.0
  )
  if not triggered:
      logger.warning("[LiveAPI] greeting_trigger タイムアウト（30秒）、greeting発火します")
  ```
- **導入コミット**: `94d4e0e` (2026-03-30 01:43 UTC)
  「fix: delay greeting until avatar ready (greeting_trigger gate)」
- **仕組み**: バックエンドは `live_ready` 送信後、フロントの `greeting_trigger` を最大30秒待つ。届かなければタイムアウトして挨拶発火。

#### 原因B: フロントの `resetAppContent()` 2回呼び
- **ファイル**: `src/scripts/chat/core-controller.ts:94, 106`
- **コード（該当箇所）**:
  ```typescript
  await this.resetAppContent();      // 94行目: 1回目
  ...
  console.log('[Core] Initialization completed');
  // ★ 初期起動完了後にソフトリセットを自動実行（リップシンク正常化）
  await this.resetAppContent();      // 106行目: 2回目
  ```
- **導入コミット**: `7d16730` (2026-03-30 07:56 UTC)
  「init()完了後にresetAppContent()を追加実行しリップシンクを正常化」
- **仕組み**: `resetAppContent()` は内部で `initializeSession()` → `socket.emit('live_start')` を呼ぶ。結果として起動時に `live_start` が 2 回発火し、バックエンドで LiveAPI セッションが 2 回作られる。

### 2-3. 現在の仮説（未確定）

「resetAppContent 2回呼び」により Session A → Session B と切替わる過程で、フロントの `greeting_trigger` emit が **切替のスキマ**に落ちて `active_live_sessions[client_sid]` に登録されていないセッションに送られる → Session B の `_greeting_trigger_event` が set されず → 毎回 30 秒タイムアウトに突入。

**この仮説は Cloud Run ログで簡単に検証可能:**
```powershell
gcloud logging read `
  "resource.type=cloud_run_revision AND resource.labels.service_name=chatty-sp-base AND (textPayload:'live_ready' OR textPayload:'greeting_trigger' OR textPayload:'INITIAL_GREETING')" `
  --project=ai-avator-492205 `
  --limit=50 `
  --format="value(timestamp,textPayload,jsonPayload.message)" `
  --freshness=1h
```
- `greeting_trigger受信` のログが**出ていなければ仮説確定**
- `live_ready送信` → 30秒後 → `greeting_trigger タイムアウト（30秒）` の順で並ぶはず

---

## 3. なぜ暫定処置になったか（重要な背景）

### 経緯（2026-03-27〜03-30、Git履歴で確認済み）

**フェーズ1〜2: リップシンク不具合の対処（3/28〜3/29）**
- jawOpen 閾値調整、句読点フラッシュ、A2E先行方式、bisect（二分探索的リバート）等を多数試すも根本原因に到達できず

**フェーズ3: 初期起動とリロードのフローの違いを追う（3/30 00:44〜05:28）**
- hypothesis 1（isUserInteracted 強制）
- hypothesis 2（AudioContext.resume 強制）
- hypothesis 3（LAMAvatarController 待機）
- 30秒ゲート導入（`94d4e0e`）
- threading.Event 修正（`5f58449`）
- firstChunkStartTime 調整（`380ec7d`, `fe9a9e6`）
- stopAllActivities 前置（`0798e70`）
- clearPlaybackQueue 前置（`4d11266`）
- 「init を resetAppContent 経由に統一」試行（`b4a1948`）

**フェーズ4: 暫定処置に妥協（3/30 05:51〜07:56）**
- `f870511` init完了後にresetAppContent自動実行 → 差異ゼロ化を試みる
- `748b004` initializeSession の二重呼び出しを解消（一時的に整理）
- **`7d16730` init完了後にresetAppContent追加実行 → 現在残っている「2回発火」に到達**

「リロード時は問題が出ない」というユーザーの発見から、「初期起動フローにリロードフローを強引に追加する」ことで症状を隠した。根本原因は未解明のまま。

### なぜ根本解決できなかったか
1. LAM/A2E も Gemini LiveAPI も Claude の知識ベース外
2. Claude が推論で診断すると悉く外れる（例: 「構造的レイテンシ2-4秒」と診断 → 実測ゼロ、公式デモにも遅延なし）
3. 気を利かせた「修正」が新技術の設計思想に反し、動かなくなる → 推論で原因究明 → さらに外す → 泥沼化

**CLAUDE.md はこの失敗を受けて整備された。**

---

## 4. 現在のフェーズ

- **α版テストに進むタイミング**
- 暫定処置（30秒待機 + 2回発火）は明らかに無駄なので、**抜本改善が必要**
- ただし推論主導で進めれば同じ泥沼を再現する高いリスク
- Claude の役割は事実収集・整理・記録に限定、判断はユーザー

---

## 5. 既に提案済みの改善アプローチ（4案）

### 案A: 計測駆動アプローチ（前セッションで推奨）
1. 初期化シーケンス各段階にタイムスタンプ付きログを仕込む
2. 初期起動 と リロード の両方を実測
3. 時刻差分から根本原因を「時系列で」可視化
4. 判明後ユーザーが修正箇所を決定

### 案B: 最小再現ハーネス
1. アプリロジックを剥がした最小HTMLを作成
2. `greeting_trigger` タイミングを手動で変えて不具合の再現条件を特定
3. 特定できた条件を回避する設計をユーザーが決定

### 案C: 外部LLM / 一次資料クロスチェック
1. アリババLAM/A2E公式GitHub / 論文からタイミング仕様を収集
2. Gemini LiveAPI 公式ドキュメント / SDKソースから状態遷移仕様を収集
3. 複数LLM（Gemini 最新版等）にクロス質問
4. 複数ソース一致部分のみ信頼

### 案D: 暫定処置を順番に外す
1. `core-controller.ts:106` の resetAppContent 2回目呼び を外して観察 → revert
2. `live_api_handler.py:729` の 30秒ゲート を外して観察 → revert
3. 両方外して観察
4. 実測結果から本当に必要なものを分別

**前セッションの推奨: 案A → 案D の順。案Bはバックアップ、案Cは補完。**

---

## 6. ユーザーへの依頼事項（次セッションの目的）

**このプランニングを別モデル（Fable 5 想定）で再考してほしい。**

具体的には：
1. 上記4案（A/B/C/D）の妥当性を再評価
2. より良い案があれば追加提案
3. **CLAUDE.md ルールを厳密に守った上で**、根本原因の仮説と検証方針を再構築
4. **Claude 自身が「気を利かせて」修正を提案しない**（案の提示のみ）

---

## 7. 重要ファイル一覧（次セッションで最初に読むべき）

| 優先度 | ファイル | 用途 |
|---|---|---|
| 最優先 | `/home/user/Chatty-sp/CLAUDE.md` | プロジェクト規約・禁止事項 |
| 高 | `chatty-base/live_api_handler.py`（特に L570-800 周辺） | 30秒ゲート、A2E、greeting_trigger機構 |
| 高 | `src/scripts/chat/core-controller.ts`（特に L80-170, 280-330） | resetAppContent 2回呼び、live_ready リスナー |
| 高 | `src/scripts/chat/concierge-controller.ts`（L60-80） | linkLamAvatar → greeting_trigger emit |
| 高 | `src/scripts/chat/lesson-controller.ts`（L64-70） | 同上（別モード） |
| 中 | `chatty-base/app_customer_support.py`（L960-990） | Socket.IO greeting_trigger ハンドラ、CORS 設定 |
| 中 | `docs/09_liveapi_migration_design_v6.md` | V6統合仕様書（メイン） |
| 参考 | `docs/旧版仕様書/` | V1〜V5、設計判断の履歴 |

---

## 8. 関連コミットの一覧（時系列）

```
2026-03-30 01:43 UTC  94d4e0e  fix: delay greeting until avatar ready (greeting_trigger gate)   ← 30秒ゲート導入
2026-03-30 01:54 UTC  5f58449  fix: use threading.Event instead of asyncio.Event
2026-03-30 02:07 UTC  380ec7d  fix: reset firstChunkStartTime on live_expression chunk=0 arrival
2026-03-30 02:31 UTC  fe9a9e6  fix: immediately clear firstChunkStartTime=0 on expression chunk=0
2026-03-30 03:44 UTC  0798e70  test: call stopAllActivities() before initializeSession
2026-03-30 03:55 UTC  4d11266  test: call clearPlaybackQueue + onAiResponseEnded before init
2026-03-30 05:28 UTC  b4a1948  案3: init()をresetAppContent()経由に変更しパスを統一
2026-03-30 05:51 UTC  f870511  init()完了後にresetAppContent()を自動実行し差異をゼロにする
2026-03-30 06:03 UTC  748b004  initializeSession()の二重呼び出しを解消しresetAppContent()に一本化
2026-03-30 07:56 UTC  7d16730  init()完了後にresetAppContent()を追加実行しリップシンクを正常化   ← 現在残っている2回発火
```

---

## 9. 環境情報（次セッションで役立つ）

- **作業ブランチ**: `claude/planning-app-dev-cu8PX`
- **GitHub MCP スコープ**: `mirai-gpro/chatty-sp` のみ（他リポジトリは触れない）
- **Cloud Run バックエンドURL**:
  - Chatty: `https://chatty-sp-base-281169010109.us-central1.run.app`
  - Travel: `https://travel-sp-base-fmfxldo6kq-uc.a.run.app`
  - A2E: `https://audio2exp-service-281169010109.us-central1.run.app`
- **フロントデプロイ**:
  - Chatty: `https://chatty-sp.vercel.app`
  - Travel: `https://travel-sp.vercel.app`
- **CORS 許可オリジン設定**: `chatty-base/app_customer_support.py:79-86`

---

## 10. 派生プロジェクト（別件、参考情報）

- **Scan-Chat-AI**（`https://github.com/mirai-gpro/Scan-Chat-AI`）
  - Chatty-sp をベースにした医療AI問診アプリのパイロット
  - Astro + Vercel + Supabase 構成
  - スケルトンは前セッションで tar.gz 配布済み
  - 本件（30秒問題）とは無関係

---

## 11. 現在の状況サマリ

| 項目 | 状態 |
|---|---|
| Cloud Run（chatty-sp-base） | ✅ 復旧済（GCP請求問題解決後） |
| Cloud Run（travel-sp-base） | ✅ 復旧済 |
| A2E サービス | ✅ 起動完了（コールドスタート65分要した） |
| 30秒コールドスタート問題 | ❌ 未解決（本引継ぎの対象） |
| 2回発火（resetAppContent） | ❌ 未解決（本引継ぎの対象） |
| リップシンク不具合の根本原因 | ❌ 未特定（暫定処置で症状を隠蔽中） |

---

## 12. 次セッションへの指示テンプレート

以下を新セッションの最初のプロンプトとしてお使いください：

```
このプロジェクト（/home/user/Chatty-sp）で作業する前に、まず必ず
/home/user/Chatty-sp/CLAUDE.md を全文読んでください。

その上で、以下の引継ぎメモを読み、書かれている問題（30秒コールドスタート +
2回発火の暫定処置）の抜本改善案を再考してください。

引継ぎメモ: [このファイルの内容を貼り付け]

制約:
- CLAUDE.md のルールを厳密に守ってください
- 特に「推論するな。確認しろ」「フォールバック禁止」を最優先
- 分析・診断・改善提案は「案の提示」のみ。実装は指示待ち
- LAM/A2E および Gemini LiveAPI について推論で語らない
- わからないことは「わかりません」と言う

まず既存の4案（A/B/C/D）を再評価し、その後に代替案または補強案を
提示してください。
```

---

## 補足

- 前セッション（Opus 4.7）での作業ログは Claude Code のセッション履歴に残っています
- 該当セッションURL（過去の暫定処置導入時）:
  - `https://claude.ai/code/session_01HyyDikjCs9ac1i1Lf9eSch`（94d4e0e / 30秒ゲート導入時）
  - `https://claude.ai/code/session_01JVc932CQzardzCzkV2GBAQ`（7d16730 / 2回発火導入時）

以上。
