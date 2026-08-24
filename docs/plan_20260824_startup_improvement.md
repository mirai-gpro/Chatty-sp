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
- ONNX 化と保温でバックエンドが高速化した結果、その偶然は崩れた
  - **実測（対照実験）**: トリガー送信 → `[A2E] chunk 0` が **0.77〜1.28 秒**（アームB 9回）/ **0.78〜0.85 秒**（アームA 正常3回）
  - **ユーザー報告**（実測値ではない）: アプリ起動 3〜5 秒で挨拶が始まり、セリフが短いとアバター出現前に喋り終わる
  - ONNX 化の速度差は AI-mtg-assistant 側の A/B 実測（同一 responseSize 168,570 bytes で PyTorch 1.316 秒 → ONNX 0.908 秒、−31%）。**当リポジトリでは未検証**
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
| **P1** | `greeting_trigger` 送信経路の確実化 | **socket 未接続経路の制御を保証**＋他2経路の待ち時間を30秒削る（§3参照） | `lesson-controller.ts` / `concierge-controller.ts` | 小 |
| **P2** | アバター zip の先行読込（preload） | アバター準備を速くする（待ち時間短縮） | `LAMAvatar.astro` | 3行 |
| ~~P3~~ | ~~`expressionFrameBuffer` のターン終了時クリア~~ | **却下。**実装するとリップシンクが約1秒早く止まる（§3 で検証）→ 方向D へ | — | — |

### 順序の根拠

- **P1 が最優先。** ユーザーの主眼は「準備完了まで流さない制御」であり、それを**保証**するのが P1。
  P2（速度）より P1（正しさ）が先。
- **P3 は却下**（§3 で実害を確認）。残課題 §4 方向D に移す。**今回の実装対象は P1・P2 の2件のみ。**

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

**適用範囲（重要・期待値を正しく置く）**: 3経路のうち UX が改善するのは1つだけ。

| 経路 | P1 適用後 | UX |
|---|---|---|
| `socket.connected === false` | `once('connect')` で送られる | **改善する。**一時的失敗で、接続後は正常動作 |
| `controller` が undefined | 即座に送られる | **改善しない。**アバターが無く rAF ループも無い |
| `initialize()` が throw | 即座に送られる | **改善しない。**`_showFallback()` で静止画に落ちる |

後2つは「制御が破れる」のではなく「**アバターが使えない**」状態。
P1 は *30秒待ってから壊れる* を *即座に壊れる* に変えるだけで、リップシンクは動かない。
**ただし無音30秒より即座に音声のほうが良いので、P1 は妥当。**

**リスク**: アバター初期化に失敗した場合、準備完了前に挨拶が始まりうる。
ただし**現状も30秒後にどのみち始まる**（フェイルオープン）ので、新しい挙動の追加ではない。
**巻き戻しは1コミットの revert。**

**効果測定**: **`reason` の内訳を見る。**
`[LiveAPI] greeting_trigger タイムアウト（30秒）` の件数では**測れない** —
対照実験のアームA 5回でゲート解除は 0.19 / 0.50 秒、**タイムアウトは元から0件**のため。

| 観測 | 意味 |
|---|---|
| `reason=ready` のみ | 3失敗経路は現実には踏まれていない。**P1 は保険のまま**（それでよい） |
| `reason=error` / `no-controller` が出る | アバター初期化が実際に失敗している。**別問題として追う価値がある** |
| socket 未接続からの遅延送信が出る | **P1 が実際に救っている** |

**位置づけ**: P1 は「まだ起きていない失敗への保険」。測るのは「効いたか」ではなく
「**その経路が現実に踏まれるか**」。

**実装単位**: `lesson-controller.ts` と `concierge-controller.ts` は同一構造。
片方だけ直すと同じ穴が残るため、**2ファイルを1コミットにまとめる**。

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

### P3: `expressionFrameBuffer` のクリア — **当初案は却下。設計やり直し**

**当初案**: `onAiResponseEnded()`（＝`turn_complete` 受信時）でバッファをクリアする。

**却下する。実害が確認されたため。**

#### 検証1: レビューの懸念（口が開いたまま固まる）は成立しない

`_getExpressionData()` の null 分岐を読んだ（`lam-websocket-manager.ts:168-174`）。

```typescript
if (!this.currentExpression) {
    // 静止状態: 全て0
    for (const name of this.expressionNames) { result[name] = 0; }
    return result;
}
```

**全52要素がゼロになる。** 既存の口閉じ対策（jawOpen 系4個のゼロ化）より完全であり、
バッファをクリアしても口は閉じる。**この懸念は棄却。**

#### 検証2: しかし `turn_complete` 時点で音声はまだ再生中 — こちらが実害

`turn_complete` は「サーバが送り終えた」合図であって「再生し終えた」合図ではない。
再生は `nextPlayTime` まで先行スケジュール済みで、まだ続いている。

**実測（runE 挨拶ターン）**:

```
[A2E Sync] offsetMs=7960, frameIdx=238/268   ← turn_complete の直前
[LiveAPI] turn_complete                       ← ここでクリアすると…
[A2E Sync] offsetMs=8960, frameIdx=267/268   ← 本来はここまで再生する
```

expression は 268 フレーム＝8.933 秒分。`turn_complete` 時点で `frameIdx=238`。
→ **残り約30フレーム＝1.0秒分のリップシンクが未再生。**

**ここでクリアすると、音声が約1秒残っているのに口が閉じる。** 明確な退行。

#### 結論と扱い

- **当初案（`onAiResponseEnded()` でクリア）は実装しない**
- レビュー提案の案A（最終フレーム1個だけ残す）も、**空回り自体は残る**ため費用対効果が薄い
- そもそも P3 が解こうとしていたのは「52要素の計算が毎フレーム空回りする」という**軽微な性能問題**であり、
  リップシンクを1秒削るリスクに見合わない
- **正しく解くなら「再生が実際に終わった時点」でクリアする設計が要る**（`nextPlayTime` と
  `audioContext.currentTime` の比較など）。**これは別途設計が必要**

→ **P3 は近い将来の実装対象から外し、§4 の残課題（方向D）へ移す。**
　`CLAUDE.md`「『ついで』の修正はやるな」に照らしても、今やる理由がない。

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

### 方向D: `expressionFrameBuffer` の解放（P3 から降格）

- **区分: 軽微な性能問題。** ターン終了後も `getCurrentExpressionFrame()` が最終フレームを返し続け、
  52要素の計算が毎レンダリングフレーム空回りする（実測 `frameIdx=142/143` / `267/268` の固着）
- **`turn_complete` でのクリアは不可**（§3 P3 で検証：音声が約1秒残っているのに口が閉じる）
- **正しくは「再生が実際に終わった時点」で解放する必要がある。**
  `nextPlayTime` と `audioContext.currentTime` の比較などが要るが、**設計は未着手**
- 優先度は低い。P1・P2 が落ち着いてから単独で扱う

### 方向C: 起動時間そのものの短縮

- コールドスタートは保温で解消済み（min-instances=1）
- P2（zip 先行）が初回訪問の起動短縮に寄与
- 追加の短縮余地（`sleep(300)` の意図確認など）は優先度低

---

## 5. 検証方法

対照実験と同じ方式。**本番に一切触れない。**

- `git worktree` で対象ブランチを別フォルダに展開
- `.env` に1行（秘密情報ではない。公開エンドポイント）:
  `PUBLIC_API_URL=https://chatty-sp-base-fmfxldo6kq-uc.a.run.app`
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
| F9 | `_getExpressionData()` の null 分岐は全52要素を0にする | `lam-websocket-manager.ts:168-174` |
| F10 | `turn_complete` 時点で再生は未完了（runE: `frameIdx=238/268`、残り約1.0秒） | runE ログ |
| F11 | アームA でゲート解除は 0.19 / 0.50 秒。タイムアウトは0件 | 対照実験 |

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
| ~~5~~ | ~~本番 `PUBLIC_API_URL`~~ | **解決。**`https://chatty-sp-base-fmfxldo6kq-uc.a.run.app`（対照実験 計14回で実証済み）。取得は `gcloud run services describe chatty-sp-base --project ai-avator-492205 --region us-central1 --format="value(status.url)"` |
| 6 | `sleep(300)` の意図 | 不明。優先度低 |
