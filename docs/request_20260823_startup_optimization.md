# 改善プラン依頼 — 初期起動の最適化（Zip先行読込 / 2重リセット / 30秒待機）

**作成日**: 2026-08-23
**対象リポジトリ**: `mirai-gpro/Chatty-sp`
**対象ブランチ**: `claude/initial-startup-improvement-sr72o3`

---

## 0. この文書の性質

**改善プランの提案を依頼するための資料。**

記載内容は **すべてコード・ログ・git履歴で確認した事実** に限定している。
作成者（別セッションのClaude）の推論・仮説・提案は**意図的に除外**した。
未確定・未特定の事項は §5 に明記した。

**事実と推論を混ぜないこと。** これは本プロジェクトの最重要ルール（`CLAUDE.md`）である。

---

## 1. 依頼事項

以下3点について、**改善プランを提案してほしい。**

### 依頼1: アバターZipの先行読込（起動時間短縮）

4MB のアバターZip のダウンロード開始が、初期化処理のすべての完了を待っている（§4-2）。
これを先行/並行化し、起動時間を短縮したい。

### 依頼2: 2重リセットの見直し

初期起動時に `resetAppContent()` を2回実行する暫定処置があった（2026-03-30 導入）。
2026-08-23 に削除したところ、初期あいさつの音声に不具合が発生した（§4-5）。
**「リロードすると正常化する」不具合への合理的な対処**を設計したい。

### 依頼3: 30秒待機の見直し

初期あいさつを最大30秒待つゲートがある（`live_api_handler.py:754-764`）。
現在は正常に機能している（実測 0.22秒 / 1.06秒で解除）が、設計として妥当か見直したい。

---

## 2. 遵守すべき制約

`CLAUDE.md`（リポジトリルート）を**必ず先に読むこと。** 要点のみ再掲する。

### 知識ベースの限界

| 技術 | Claudeの知識 |
|---|---|
| LAM/A2E (Audio2Expression) | **なし**（2025年10月論文） |
| Gemini LiveAPI | **なし**（2025年12月末プレビュー） |
| `gemini-3.1-flash-live-preview` | **なし** |

→ **推論での修正は禁止。コードを読む・仕様書を読む・ユーザーに聞く の3つのみ。**

### 絶対ルール

- **コード修正は必ずユーザーの許可を得てから**
- **フォールバック禁止**（キーワード検出等の代替ロジックは絶対不可）
- **1修正1コミット**
- **2回修正して直らなかったら手を止めてユーザーに報告**
- **変更禁止**: `CLAUDE.md` / `docs/` 配下 / `DESIGN_SPEC_PHASE1.md` / `api_integrations.py` / `long_term_memory.py` / PWA設定 / `i18n.ts` / `.github/workflows/`

### デプロイの地雷

- `.github/workflows/deploy-cloud-run.yml` の trigger は
  `push: branches: [main, 'claude/*'] paths: ['chatty-base/**', '.github/workflows/deploy-cloud-run.yml']`
  → **`chatty-base/` への push は即 Cloud Run 本番デプロイ**
- `src/` への push は Vercel のみ
- `docs/` への push はどちらもトリガーしない
- プロンプトは **GCS（REST API用）と Python ハードコード（LiveAPI用）の2系統**

### 参照すべき仕様書（優先順）

1. `docs/09_liveapi_migration_design_v6.md` — V6統合仕様書（メイン）
2. `DESIGN_SPEC_PHASE1.md`
3. `docs/10_lam_audio2expression_spec.md` / `11_a2e_lipsync_implementation_guide.md` / `13_a2e_lipsync_comprehensive_guide.md`

---

## 3. 経緯（git履歴で確認した事実）

### 3-1. 2026-03-10 — リポジトリ最初のコミット `464b0a0`

```
Phase1基盤: 現行安定版のベースコード配置 + LiveAPI移行設計書
- src/: gourmet-spフロントエンド(Astro)の安定版コード
```

前身プロジェクト（gourmet-sp）の REST API 時代のコードを丸ごと配置。
この時点で LiveAPI / アバター / A2E は未実装。

**この時点で `resetAppContent()` 内に `await new Promise(resolve => setTimeout(resolve, 300))` が既に存在。**
ただし当時の `init()` は `resetAppContent()` を経由していなかった。

```typescript
// 464b0a0 時点の init()
protected async init() {
    this.bindEvents();
    this.initSocket();
    setTimeout(..., 10000);
    await this.initializeSession();      // ← 直接呼んでいる
    this.updateUILanguage();
    setTimeout(..., 2000);
}
```

→ **300ms は初期起動パスに入っていなかった。**

### 3-2. 2026-03-30 — リップシンク不具合の試行錯誤（1日で13コミット）

初期起動時に初期あいさつのリップシンクが動かない。リロードすると正常化する。
原因が特定できず、以下の試行が連続した。

```
03/30 00:44  1452ae7  test: force isUserInteracted=true on init (hypothesis 1 test)
03/30 00:48  6380cc4  test: force AudioContext.resume() if suspended (hypothesis 2 test)
03/30 00:57  f1669da  test: wait for LAMAvatarController before linking (hypothesis 3 test)
03/30 01:04  89f82f2  revert: remove hypothesis 3 test code
03/30 01:43  94d4e0e  fix: delay greeting until avatar ready (greeting_trigger gate)   ← 30秒ゲート導入
03/30 01:54  5f58449  fix: use threading.Event instead of asyncio.Event for greeting_trigger
03/30 02:07  380ec7d  fix: reset firstChunkStartTime on live_expression chunk=0 arrival
03/30 02:31  fe9a9e6  fix: immediately clear firstChunkStartTime=0 on expression chunk=0
03/30 03:44  0798e70  test: call stopAllActivities() before initializeSession in init() (plan 1)
03/30 03:55  4d11266  test: call clearPlaybackQueue + onAiResponseEnded before init (plan 2)
03/30 05:28  b4a1948  案3: init()をresetAppContent()経由に変更し初期起動とソフトリセットのパスを統一
03/30 06:03  748b004  initializeSession()の二重呼び出しを解消しresetAppContent()に一本化
03/30 07:56  7d16730  init()完了後にresetAppContent()を追加実行しリップシンクを正常化   ← 解決
```

**`94d4e0e`（30秒ゲート導入、01:43）の後も6時間13分・10回以上の試行が続き、最終的に `7d16730`（07:56）の3行で解決した。**

`7d16730` の diff は3行のみ:
```diff
     console.log('[Core] Initialization completed');
+
+    // ★ 初期起動完了後にソフトリセットを自動実行（リップシンク正常化）
+    await this.resetAppContent();
```

`b4a1948`（案3）で `init()` が `resetAppContent()` 経由になった。
```diff
-    await this.initializeSession();
+    // ★ 案3: 初期起動もresetAppContent()経由で実行（ソフトリセットと同じパス）
+    await this.resetAppContent();
```

**これにより 300ms が初期起動パスに入った。** `b4a1948` の目的は「パスの統一」であり、300ms を入れることではない。
`7d16730` の追加により **300ms × 2 = 600ms** になった。

### 3-3. 2026-03-30 〜 2026-08-23（約5か月）

上記の状態で運用。**この不具合の再発報告はなかった**（ユーザー報告）。

### 3-4. 2026-08-23 — 本セッションでの変更

| コミット | 内容 |
|---|---|
| `2eb66bf` | **Step 1**: A2E送信経路を初期あいさつ／通常ターンで一本化（`_is_initial_greeting_phase` の分岐2箇所を削除） |
| `36d65df` | **Step 2**: 2回目の `resetAppContent()` を削除（`7d16730` の打ち消し） |
| `17ba5d4` | 計測ログ追加（Socket.IO transport / `live_audio` 到着） |

**Step 1 適用後の動作確認**: 初期あいさつ・リップシンクとも正常（ユーザー確認）。
**Step 2 適用後**: §4-5 の不具合が発生。

### 3-5. 別トラック（他セッション）で実施済み

- Cloud Run の保温（Cloud Scheduler で `/health` を8分間隔）を 2026-08-22 18:07Z から実施
- **保温開始後、デプロイ起因を除きコールドスタート0回**（`Starting new instance` のログで確認）
- A2E サービス（`audio2exp-onnx`）も min-instances=0 + 保温に移行済み

---

## 4. 実証で得た事実

### 4-1. 起動時間の実測

| 状態 | コールドスタート | アプリ処理 | 合計 |
|---|---|---|---|
| コールド（半日放置後） | **35.3秒** | 9.7秒 | **45秒** |
| ウォーム | 0秒 | **7.76秒** | **7.76秒** |

コールドスタート 35.3秒の内訳（Cloud Run ログ）:

| 区間 | 秒数 |
|---|---|
| gunicorn 起動 | 1.1s |
| import群 → `support_core.py:16` | 13.8s |
| GCSプロンプト読み込み（1回目） | 5.2s |
| `live_api_handler` import（scipy/numpy + TTS×4） | **14.3s** |
| GCSプロンプト読み込み（2回目・重複） | 0.8s |

区間別のコールド／ウォーム比較:

| 区間 | 内容 | コールド | ウォーム |
|---|---|---|---|
| A | インスタンス起動 → アプリ初期化完了 | 35.3秒 | 0秒 |
| B | WebSocket接続 → 挨拶発話 | 7.27秒 | 7.76秒 |

**区間B はコールド／ウォームでほぼ同一。**

### 4-2. アバターZip の読込開始までの経路

**Zip の DL を開始する箇所は1つだけ。**
`lam-websocket-manager.ts:67` の `GaussianSplatRenderer.getInstance(container, modelUrl, callbacks)`。

そこに至る唯一の経路:
`lesson-controller.ts:51` / `concierge-controller.ts:56` の `this.linkLamAvatar()`

```typescript
// lesson-controller.ts:26-51
protected async init() {
    await super.init();        // ← 完了まで待つ
    // ... els setup ...
    this.linkLamAvatar();      // ← ここで初めて DL 開始
}
```

**`await super.init()` 完了までに直列で走る処理:**

| # | 処理 | 場所 |
|---|---|---|
| 1 | `bindEvents()` / `initSocket()` | `core-controller.ts:83-84` |
| 2 | `stopAllActivities()` → `terminateLiveSession()` | `:120` |
| 3 | `await sleep(300)` | `:154` |
| 4 | `await fetch('/api/session/end')` | `initializeSession()` |
| 5 | `await fetch('/api/session/start')` | 同上（Cloud Run 往復） |
| 6 | socket 接続待ち（最大5秒） | `:634-648` |
| 7 | `await liveAudioManager.initialize(socket)` | `:657` |
| 7a | └ `new AudioContext({sampleRate:48000})` | `live-audio-manager.ts:79` |
| 7b | └ `await getUserMedia()`（マイク許可を含む） | `:83` |
| 7c | └ `await audioContext.audioWorklet.addModule(blobURL)` | `:136` |
| 8 | `emit('live_start')` | `:661` |
| 9 | `updateUILanguage()` / `scrollIntoView` | `:161-165` |

DL 開始直前にもう1つ `await` がある:
```typescript
// lam-websocket-manager.ts:63-67
const mode = window.location.pathname.includes('concierge') ? 'concierge' : 'lesson';
await ensureDefaultAvatarInStorage(mode);      // 新規ユーザーのみ fetch('/avatar/avatar-config.json')
this.renderer = await GaussianSplats3D.GaussianSplatRenderer.getInstance(...)
```

**先読みの仕組みは存在しない:**

| 項目 | 状態 |
|---|---|
| `<link rel="preload">` / `prefetch` / `modulepreload` | **リポジトリ全体で0件** |
| PWA precache（`astro.config.mjs:54`） | `globPatterns: ['**/*.{css,js,html,svg,png,ico,txt}']` → **zip 含まれず** |
| `runtimeCaching` | **設定なし** |
| `LAMAvatar.astro:247` の `new LAMAvatarController()` | コンストラクタは `document.getElementById` を3回呼ぶのみ。**DLしない** |

**アセット:**
```
public/avatar/  meruru.zip 4,093,593 bytes（lesson デフォルト）
                elf.zip    4,093,244 bytes（concierge デフォルト）
                他11個、いずれも約4MB
```

**その他の関連事実:**
- `LessonChat.astro:308` — socket.io を外部CDNから同期読み込み（`defer`/`async` なし）
- `LessonChat.astro:313` — `DOMContentLoaded` で `new LessonController()`
- `core-controller.ts:34` — `liveAudioManager` は**フィールド初期化子で生成**（コンストラクタ実行時点で存在）
- `audio-sync-player.ts:27-29` — `bindLiveAudioManager()` は参照代入のみ
- `AvatarSelector.astro:256-258` — アバター変更は `window.location.reload()`（フルリロード）

### 4-3. `sleep(300)` の実態

`core-controller.ts:154`、`initializeSession()` の直前、`resetAppContent()` 内に1箇所のみ。

- 直前の 147〜153行はすべて同期処理（配列代入・フラグ代入）
- 初期起動時は `/api/cancel`（124行）も実行されない（`oldSessionId` が null）
- **コメントなし。コミットメッセージにも `docs/` にも根拠の記載なし**
- 2026-03-10 の初回コミットから値・位置とも一度も変更されていない

### 4-4. 2重リセットとセッション分岐の関係

```python
# app_customer_support.py:942-946
if client_sid in greeted_client_sids:
    live_session.session_count = 1      # 2回目 → run()内で +1 → 2
else:
    greeted_client_sids.add(client_sid) # 1回目 → 0 → run()内で +1 → 1
```

```python
# live_api_handler.py
:586  self.session_count = 0
:737  self.session_count += 1      # run() のループ先頭
:753  if self.session_count == 1:  # 初回挨拶ブランチ
:755      self._is_initial_greeting_phase = True
:756      emit('live_ready')
:761      threading.Event.wait(30.0) で greeting_trigger を待つ
:780  else:                        # 再接続ブランチ
:780      self._is_initial_greeting_phase = False
:797      send_realtime_input(resume_text)   # ゲートを通らず即発話
```

| | Step 2 前（2重リセット） | Step 2 後 |
|---|---|---|
| `live_start` | 2回 | 1回 |
| セッションA | `session_count` 0→1 → 初回挨拶ブランチ → 30秒ゲートで待機 → `live_stop` で停止 | 同左（ただし停止されない） |
| セッションB | `session_count` 1→2 → 再接続ブランチ → **ゲートを通らず即発話** | 存在しない |
| 実際に発話するセッション | **B** | **A** |
| 30秒ゲートの機能 | 空回り（セッションAは停止済みで音声が転送されない） | **正常動作** |

**停止済みセッションの音声が転送されない根拠:**
```python
:689-692  def stop(self): self.is_running = False      # フラグを立てるだけ
:905      while not self.needs_reconnect and self.is_running:   # ループが回らない
```

**`greeting_trigger` の送信タイミング:**
```typescript
// lesson-controller.ts:55-72（concierge-controller.ts:60-78 も同一構造）
private async linkLamAvatar(): Promise<void> {
    const controller = (window as any).__lamAvatarController;
    if (controller) {
        try {
            await controller.initialize(this.liveAudioManager);   // ← 4MB DL + パース + 描画開始
            if (this.socket && this.socket.connected) {
                this.socket.emit('greeting_trigger');              // ← ここ
            }
        } catch (e) { ... }
    }
}
```

`linkLamAvatar()` は `await super.init()` の**後**に呼ばれる。
→ Step 2 前は、セッションBの発話が `greeting_trigger` 送信より**前**に起きていた。

**サーバー側の受信:**
```python
# app_customer_support.py:978-984
@socketio.on('greeting_trigger')
def handle_greeting_trigger():
    client_sid = request.sid
    live_session = active_live_sessions.get(client_sid)
    if live_session:                       # セッション未作成なら
        live_session.on_greeting_trigger() # 何もせず終了（ログも出ない）
```

```python
# app_customer_support.py
:951  active_live_sessions[client_sid] = live_session   # セッション登録
      ...thread.start()...
:971  emit('live_ready', {'status': 'connected'})       # その後に emit
```
→ **`live_ready` 受信時点でサーバー側にセッションが存在することが保証される。**

### 4-5. Step 2 後に発生した2つの不具合

いずれも **リロードすると正常化する。再現性は低い**（同じブラウザでも再現しないことがある）。

#### 不具合A: 初期あいさつの音声が出ない（新規ブラウザ、2026-08-23 00:47）

**サーバー側は完全に正常:**
```
00:47:03.288  live_ready送信 → greeting_trigger待機  is_set=False  Thread-294
00:47:04.351  greeting_trigger受信: アバター準備完了  Thread-295
00:47:04.351  greeting_trigger待機終了 triggered=True 経過=1.06s
00:47:04.353  初期あいさつトリガー送信: 'こんにちは。'
00:47:05.208  [A2E] chunk 0: 6 frames送信
00:47:05.394  [A2E] chunk 1: 27 frames送信
00:47:07.222  [A2E] chunk 2: 140 frames送信
00:47:07.574  [A2E] chunk 3: 38 frames送信
00:47:07.884  [A2E] chunk 4: 45 frames送信
00:47:13.439  AI: こんにちは、Lisaです。あなたの相談相手、おしゃべりの相棒です。…
00:47:13.440  greeting_done送信
```

**ブラウザ側:**
- `[LiveAPI] turn_complete` は出力された
  → `turn_complete` ハンドラは `console.log` **より前**に `if (!this.isLiveMode) return;` があるため、**`isLiveMode === true` が確定**
- **`[A2E] live_expression受信`（`core-controller.ts:307`）が1行も出ていない**
- **`[A2E Buffer] chunk=...`（`live-audio-manager.ts:305`）が1行も出ていない**
- **`[Sync] StartTime reset to:`（`live-audio-manager.ts:192`）が1行も出ていない**
- チャットには挨拶テキストが表示された（`ai_transcript` 由来。`initializeSession()` は `initial_message` を表示しない）

`live_expression` / `live_audio` のガードは `isLiveMode` のみ（`live_audio` は加えて `isTTSEnabled`、これは `core-controller.ts:21` で `true` 固定、スピーカーボタンでのみ変化）。

**サーバー側の emit は `ai_transcript` と同一の `room=self.client_sid`:**
```python
:1968  self.socketio.emit('live_expression', {...}, room=self.client_sid)   # 未達
:1005  self.socketio.emit('live_audio', {'data': audio_b64}, room=self.client_sid)  # 未達
       self.socketio.emit('ai_transcript', {'text': text}, room=self.client_sid)    # 到達
```
`ai_transcript` と `live_audio` は `_receive_and_forward` 内の数行違い。同一スレッド・同一ループ。

**インフラ側の確認:**
- リビジョンは1つのみ（`chatty-sp-base-00033-657`、00:15:28 作成）
- `Starting new instance` の最終記録は 00:15:45（失敗は 00:47:01）
→ **単一リビジョン・単一インスタンスが処理していた。**

#### 不具合B: 初期あいさつの音声がブツブツ途切れる（既存ブラウザ、2026-08-23）

リップシンクも同時に途切れる。

**ブラウザログ（抜粋）:**
```
[LessonController] greeting_trigger送信
256performance warning: READ-usage buffer was written, then fenced, ...
[Sync] StartTime reset to: 2.312
[A2E] live_expression受信: chunk=0, frames=5, names=52, fps=30
[Sync] live_expression chunk=0 受信 → StartTime=0にクリア、次のPCMで再設定
[A2E Buffer] chunk=0, +5frames, total=5, ..., firstChunkStartTime=0.000
[Sync] StartTime reset to: 2.461
[A2E] live_expression受信: chunk=1, frames=20
[A2E Buffer] chunk=1, +20frames, total=25, ..., firstChunkStartTime=2.461
[A2E] chunk=2, frames=36 → total=61
[A2E Sync] offsetMs=979, frameIdx=29/61, jawOpen=0.015
[A2E] chunk=3, frames=40 → total=101
[A2E] chunk=4, frames=56 → total=157
[A2E Sync] offsetMs=1979, frameIdx=59/157
[A2E Sync] offsetMs=2987, frameIdx=89/157
[A2E Sync] offsetMs=3984, frameIdx=119/157
[LiveAPI] turn_complete
[A2E Sync] offsetMs=4981, frameIdx=149/157
[A2E Sync] offsetMs=5979, frameIdx=156/157, jawOpen=0.000
[A2E Sync] offsetMs=6979, frameIdx=156/157     ← 以降ずっと 156/157
   ...（30秒以上継続）...
WebGL: too many errors, no more errors will be reported to the console for this context.
[A2E Sync] offsetMs=36229, frameIdx=156/157
```

**音声再生のコード（ジッタ吸収なし）:**
```typescript
// live-audio-manager.ts:212-224
private _scheduleBuffer(buffer: AudioBuffer): void {
    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audioContext.destination);
    const now = this.audioContext.currentTime;
    const startTime = Math.max(now + 0.005, this.nextPlayTime);
    source.start(startTime);
    this.nextPlayTime = startTime + buffer.duration;
    ...
}
```
- チャンクが `nextPlayTime` より前に届けば隙間なく連結
- `now + 0.005 > nextPlayTime` になると `startTime` が飛び、その差分が無音になる
- **先読み・ジッタバッファは存在しない**

**表情フレームの参照:**
```typescript
// live-audio-manager.ts:252-253
const frameIndex = Math.floor((offsetMs / 1000) * this.expressionFrameRate);
const clampedIndex = Math.min(frameIndex, this.expressionFrameBuffer.length - 1);
```
→ バッファが伸びないと上限に張り付く。

**実効フレームレート**（`[A2E Sync]` は60レンダリングフレームごとに1行出力、`live-audio-manager.ts:260-261`）:

| offsetMs 区間 | 経過 | 実効fps | 挨拶再生中か |
|---|---|---|---|
| 979 → 1979 | 1000ms | 60.0 | ✅ |
| 1979 → 2987 | 1008ms | 59.5 | ✅ |
| 2987 → 3984 | 997ms | 60.2 | ✅ |
| 3984 → 4981 | 997ms | 60.2 | ✅ |
| 4981 → 5979 | 998ms | 60.1 | ✅（末尾） |
| 17000 → 18091 | 1091ms | 55.0 | 終了後 |
| 18091 → 19840 | 1749ms | **34.3** | 終了後 |
| 19840 → 21160 | 1320ms | 45.5 | 終了後 |
| 31771 → 33219 | 1448ms | 41.4 | 終了後 |

**挨拶再生中（0〜6秒）は 60fps で安定していた。** fps低下は再生終了の約12秒後から。

### 4-6. LiveAPI の実証テスト結果（22セッション、`tools/test_speak_first.py`）

`gemini-3.1-flash-live-preview` に対する実測。

| ケース | ダミー発話 | 結果 |
|---|---|---|
| T1 / T2 / T2a / T2b / T2c | なし | **20秒間サーバーイベント0（無音）** |
| T3 / T4 | あり | **約0.6秒で発話** |

- 公式ガイドの「include a prompt asking it to greet the user」は 3.1 では効かない
- 理由づけ型プロンプト（「なぜLLMから話す必要があるか」を説明）でも結果は同じ
- **固定の挨拶文は不要**（T5/T5b は2/2で「田中さん」と名前を呼んだ）

### 4-7. 現在の Cloud Run 構成

`.github/workflows/deploy-cloud-run.yml:71-75`

```
--memory=512Mi --cpu=1 --min-instances=0 --max-instances=3 --timeout=3600
（--session-affinity なし、--concurrency 未指定＝既定80、--cpu-boost なし）
```

`Dockerfile`:
```
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app_customer_support:app
```

`app_customer_support.py:89-95`:
```python
socketio = SocketIO(app, cors_allowed_origins=allowed_origins,
                    async_mode='threading', logger=False, engineio_logger=False)
```
- **`message_queue` の指定なし**（grep でヒット0）
- `max_http_buffer_size` / `ping_timeout` / `ping_interval` の指定なし

`core-controller.ts:256-264`:
```typescript
this.socket = io(this.apiBase || window.location.origin, {
  reconnection: true, reconnectionDelay: 1000,
  reconnectionAttempts: 5, timeout: 10000
});
```
- **`transports` の指定なし**（polling 先行 → WebSocket アップグレード）
- コメントに「★修正: Socket.IO接続設定に再接続オプションを追加（transportsは削除）」

プロセス内グローバル状態:
```
app_customer_support.py:747  active_live_sessions = {}
app_customer_support.py:748  greeted_client_sids = set()
app_customer_support.py:1039 active_streams = {}
support_core.py:39           _SESSION_CACHE = {}   （クラスコメント「サポートセッション管理 (RAM版)」）
```

### 4-8. A2E のバッファ閾値（仕様書で変更禁止と明記）

```python
# live_api_handler.py:37-39
A2E_MIN_BUFFER_BYTES  = 4800      # 0.1秒
A2E_FIRST_FLUSH_BYTES = 4800      # 初回フラッシュ閾値（0.1秒）
A2E_AUTO_FLUSH_BYTES  = 240000    # 2回目以降（5秒）
```

`docs/09_liveapi_migration_design_v6.md` §4.3 に「**実証テスト済み、変更禁止**」と明記。
根拠は「初回レイテンシ最小化」「品質優先（短すぎると表情が不安定）」。

### 4-9. アバターの表示演出

**3Dアバター自体にフェード指定は存在しない。**
`LAMAvatar.astro` の `.lam-avatar-container` にも canvas にも `transition` / `opacity` / `animation` の指定なし。
`.lam-loading.hidden` は `display: none` の即時切り替え。
`transition: opacity 0.3s` があるのは `.lam-avatar-fallback`（WebGL非対応時の静止画）のみ。

**観測されるフェードインはスプラッシュのフェードアウト。**
```css
/* LessonChat.astro:280-282（Concierge.astro:266 にも同一） */
.splash-overlay { position: absolute; ... z-index: 9999;
                  transition: opacity 0.8s ease-out; }
.splash-overlay.fade-out { opacity: 0; pointer-events: none; }
.splash-overlay.hidden { display: none; }
```

```typescript
// core-controller.ts:86-102
setTimeout(() => { ...fade-out...; setTimeout(() => hidden, 800); }, 10000);  // ①10秒後
await this.resetAppContent();
setTimeout(() => { ...fade-out...; setTimeout(() => hidden, 800); }, 2000);   // ②reset完了の2秒後
```

**スプラッシュが消えるタイミングはタイマーのみで、アバターの準備完了と連動していない。**

### 4-10. 既存の別問題（Step 1/2 以前から存在）

#### `expressionFrameBuffer` がターン終了後もクリアされない
`live-audio-manager.ts:365` `onAiResponseEnded()` は `isAiSpeaking = false` と最終フレームの jawOpen を0にするが、**バッファをクリアしない**。
→ `getCurrentExpressionFrame()` が最後のフレームを返し続け、`_getExpressionData()`（52要素の計算）が毎レンダリングフレーム回り続ける。
→ ログ上、30秒以上 `frameIdx=156/157` で固着。

#### `chunk_index === 0` の処理がパス2前提
```typescript
// live-audio-manager.ts:290-295
if (data.chunk_index === 0) {
    this.firstChunkStartTime = 0;
    this._shouldResetStartTime = true;
}
```
コメントに明記:
```
* A2E先行方式: resetForNewSegment() → live_expression → live_audio の順で到着するため、
```
仕様書 §4.3 の**パス2（同期一括：キャッシュ音声・ショップ説明）前提**。
**パス1（ストリーミング）では `live_audio` が先に到着する。**
不具合Bのログでは、既に始まっている再生の同期基準が 2.312 → 2.461 に 0.149秒ずれた。

#### その他
- Supabase の DNS 解決が失敗（`[LTM] ...: [Errno -2] Name or service not known`）。長期記憶が機能していない
- GCS プロンプトファイルが6本欠損（`order_support_{en,zh,ko}.txt` / `chatty_system_{en,zh,ko}.txt`）
- `/health` が `audio2exp: not configured` を返す（workflow は `A2E_SERVICE_URL` を渡すが `app_customer_support.py:65` は `AUDIO2EXP_SERVICE_URL` を読む）

---

## 5. 未特定・未確認の事項

**以下は事実として確定していない。断定しないこと。**

| # | 項目 | 状態 |
|---|---|---|
| 1 | **不具合A で `live_expression` / `live_audio` がブラウザに届かなかった理由** | **未特定**。サーバーは emit 済み、同一 room の `ai_transcript` は到達、単一インスタンス・単一リビジョン |
| 2 | **不具合B でチャンク到着が遅れた理由** | **未特定**。`_scheduleBuffer` にログがなく、隙間の発生時刻・長さ・回数が記録されていない |
| 3 | 2重リセットが不具合を防いでいたか（因果） | **未証明**。5か月間の無報告という相関のみ |
| 4 | `sleep(300)` の意図 | **不明**。コード・コミット・仕様書に記載なし |
| 5 | `live_api_handler` import 14.3秒の内訳（scipy/numpy と TTS×4 の比率） | **未計測** |
| 6 | `GaussianSplatRenderer.getInstance()` の内部（DL / 解凍 / パースの時間配分、シングルトンか否か） | **未確認**。外部ライブラリ `gaussian-splat-renderer-for-lam@0.0.9-alpha.1` |
| 7 | `WebGL: too many errors` の発生源と影響 | **未特定**。Step 1/2 以前の正常動作時のログにも出ている |
| 8 | 本番の Socket.IO が polling / WebSocket のどちらで動いているか | **未確認** |
| 9 | Vercel の zip 配信キャッシュヘッダ | **未確認** |

---

## 6. 依頼のかたち

以下を含む改善プランを提案してほしい。

1. **各案について、変更箇所を `file:line` で特定すること**
2. **各案の根拠を、本文書の事実（§3・§4）または自分で読んだコードで示すこと**
3. **推論に基づく部分は「推定」と明示すること**
4. **効果測定の方法を併記すること**（本件は再現性が低く、体感では判定できない）
5. **1修正1コミットで実行できる粒度に分けること**
6. **各案のリスクと巻き戻し方法を書くこと**
7. **依頼1〜3の相互依存関係を明示すること**（同じ箇所を触る案は統合設計が必要）

**実装は行わないこと。** プランの提示のみ。ユーザーが承認してから着手する。

---

## 7. 参照ファイル

### リポジトリ
```
CLAUDE.md                                      ← 最初に読む（変更禁止）
DESIGN_SPEC_PHASE1.md                          ← 変更禁止
docs/09_liveapi_migration_design_v6.md         ← V6統合仕様書（変更禁止）
docs/10_lam_audio2expression_spec.md           ← A2E仕様（変更禁止）
docs/11_a2e_lipsync_implementation_guide.md
docs/12_shop_audio_a2e_sync_fix_spec.md
docs/13_a2e_lipsync_comprehensive_guide.md
docs/handover_20260822_backend_consolidation.md  ← バックエンド統合の別依頼
docs/request_20260823_startup_optimization.md    ← 本文書

src/scripts/chat/core-controller.ts
src/scripts/chat/lesson-controller.ts
src/scripts/chat/concierge-controller.ts
src/scripts/chat/live-audio-manager.ts
src/scripts/chat/lam-websocket-manager.ts
src/scripts/chat/audio-sync-player.ts
src/config/avatar-config.ts
src/components/LAMAvatar.astro
src/components/LessonChat.astro
src/components/Concierge.astro
src/components/AvatarSelector.astro
astro.config.mjs

chatty-base/app_customer_support.py
chatty-base/live_api_handler.py
chatty-base/support_core.py
chatty-base/Dockerfile
.github/workflows/deploy-cloud-run.yml         ← 変更禁止
```

### 主要コミット
```
464b0a0  2026-03-10 14:44  リポジトリ最初のコミット（300ms を含む既存コードの配置）
94d4e0e  2026-03-30 01:43  30秒ゲート導入
b4a1948  2026-03-30 05:28  init() を resetAppContent() 経由に（300ms が起動パスに入る）
7d16730  2026-03-30 07:56  2回目の resetAppContent() 追加（リップシンク正常化）
2eb66bf  2026-08-23        Step 1: A2E経路の一本化
36d65df  2026-08-23        Step 2: 2回目の resetAppContent() 削除
17ba5d4  2026-08-23        計測ログ追加
```
