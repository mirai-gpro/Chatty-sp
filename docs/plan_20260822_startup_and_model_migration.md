# 初期起動改善 実行計画（改訂版 rev.2）

**初版**: 2026-08-22
**改訂**: 2026-08-22（rev.2 — 全面改訂）
**対象ブランチ**: `claude/initial-startup-improvement-sr72o3`（`main` = `fe21436` ベース）
**対象リポジトリ**: `mirai-gpro/Chatty-sp`

---

## 0. rev.2 で何が変わったか

初版は **`main`（4/7 時点）しか見ずに作成した**ため、前提が誤っていた。
以下の事実が判明したため、全面改訂する。

| # | 初版の前提 | 判明した事実 |
|---|---|---|
| 1 | 30秒待機の機構は未確定（H1/H2/H3 の仮説） | **8/21 に実測で確定済み**。Event が別インスタンス（13/13 で再現） |
| 2 | 2回発火は症状隠しの暫定処置 | **意図的に入れられたもの**。マイク取得が2回走る |
| 3 | 30秒は純粋な無駄 | **初回リップシンクを偶然カバーしている疑い**（8/21 に Revert された理由） |
| 4 | LiveAPI モデル切替は未実施 | **4/27 に実施済み**（`000981f`） |
| 5 | Google検索の LiveAPI 移行は検討対象 | **4/27 に試行 → 1011 エラーで撤退。5/3 に FC 回避策で決着済み** |
| 6 | `main` が最新 | **`main` は 4/7 で停止しており、実開発は別ブランチにあった** |

---

## 1. 作業ルール（厳守）

CLAUDE.md に加え、本作業で合意した運用ルール。

1. **着手前にリモートブランチを全確認する。** 既存の記録・実測結果を探すことを、作業の最初に必ず行う
2. **診断ログを入れる前に、コード読みで答えが出るか先に問う。** 読めば分かるなら読む
3. **ログを入れる場合は、確認したい未確認点を1つに絞る。**「とりあえず可視化」はしない
4. **効かなかった修正は、次を試す前に必ず戻す。** 変数を同時に2つ動かさない
5. **症状を隠すガード・フォールバックは提案しない**（CLAUDE.md §4）
6. **2回試して直らなかったら止めて報告する**
7. **1修正1コミット。** 各修正後にユーザーが動作確認する
8. **原因の特定・修正内容の決定はユーザー。** Claude は事実収集・整理・実行に限定

---

## 2. デプロイ構成と事故要因（最重要・再発防止）

### 2-1. 実際の構成

| 対象 | 配信元 | トリガー |
|---|---|---|
| フロント（`https://chatty-sp.vercel.app`） | Vercel | Production Branch への push |
| バックエンド（`chatty-sp-base`） | Cloud Run | `.github/workflows/deploy-cloud-run.yml` |

`.github/workflows/deploy-cloud-run.yml:4-8`
```yaml
on:
  push:
    branches: [main, 'claude/*']      # ← claude/* も対象
    paths:
      - 'chatty-base/**'
```

### 2-2. ⚠️ 事故要因（2026-08-22 に実際に発生）

**`claude/*` のどのブランチでも、`chatty-base/**` を変更して push すると、確認なしで本番 Cloud Run にデプロイされる。**
ブランチごとの分離はなく、**最後に push したものが本番になる。**

さらに、`main` が 4/7 で停止していたため、`main` ベースの作業ブランチを push した結果、
**フロント・バックエンドの両方が 4/7 時点へ退行した**（アバター消失・サイズ退行・SDK 巻き戻り）。

### 2-3. 復旧内容（2026-08-22 完了）

```
main (aef7867) ← claude/update-avatar-startup-512p2 をマージ → fe21436
```
- 衝突は1箇所（`live_api_handler.py:42` のコメント）。**元の「変更禁止」に復元**
- 結果の中身は `claude/update-avatar-startup-512p2` と一致（差分は本計画書のみ）
- 実測で復旧確認: `/avatar/yui2.zip` = 200 / `avatar-config.json` = 10体 / CSS に `scale(1.43)` あり

### 2-4. 本作業中の運用ルール

- **`chatty-base/**` を含む push の前に、必ずユーザーの承認を得る**（push = 本番デプロイのため）
- **作業ブランチは常に `main` の最新から作り直す**
- **フロントのみの変更（`chatty-base/**` 以外）は Cloud Run をトリガーしない**

---

## 3. 現在の状態（`main` = `fe21436`）

| 項目 | 値 |
|---|---|
| LiveAPI モデル | `gemini-3.1-flash-live-preview`（4/27 に切替済み） |
| REST API モデル | `gemini-2.5-flash`（本番4箇所） |
| google-genai SDK | `1.73.1` |
| 30秒 greeting_trigger ゲート | **存在する**（`live_api_handler.py:729-733`） |
| `resetAppContent()` 2回呼び | **存在する**（`core-controller.ts:94, 106`） |
| 8/21 の診断ログ | **`main` には入っていない**（`claude/greeting-trigger-diagnostics` に未マージで残存） |
| Google検索 | LiveAPI の `google_search` は不使用。**FC 経由で REST API を呼ぶ回避策が稼働中**（`60408d4`） |

### 3-1. 未マージブランチ

| ブランチ | 内容 | 件数 | 最終 |
|---|---|---|---|
| `claude/greeting-trigger-diagnostics` | **30秒問題の診断ログ + 修正試行 + Revert** | 3 | 08-21 |
| `claude/help-with-fixes-cBYme` | 注文サポートの機能追加（KFCメニュー、セット選択モーダル等） | 9 | 04-02 |
| `claude/planning-app-dev-cu8PX` | 引継ぎメモ | 1 | 08-22 |

---

## 4. 確定している事実

### 4-1. 30秒待機の機構（8/21 実測により確定）

Cloud Run ログ13セッション分の突き合わせ:

| 計測 | 値 |
|---|---|
| `live_ready` → `greeting_trigger` 受信 | **1.08 〜 3.63 秒** |
| `live_ready` → あいさつトリガー送信 | **30.002 〜 30.009 秒（13/13）** |

診断ログの実測（2026-08-21 17:05）:
```
17:05:35.819  待機開始     sid=sOuXrx_KDhQvrzkOAAAB  ev=140324800933520  Thread-13
17:05:36.936  trigger受信  sid=sOuXrx_KDhQvrzkOAAAB  ev=140324801037776  Thread-16
17:06:05.821  待機終了     triggered=False  経過=30.00s  is_set=False  ev=140324800933520
```

**同一 sid なのに Event オブジェクトが別。** `set()` は届いていたが、待っているのとは別インスタンスだった。

機構（コード読みと実測が一致）:

```
1回目 live_start  セッションA生成。greeted_client_sids に sid 追加 → A が挨拶担当。
                  live_ready 送信 → Event(A) で最大30秒待機に入る
2回目 live_start  old_session.stop() で A を止めるが、Event.wait(30.0) は中断されない。
                  セッションB生成。sid が既に greeted_client_sids にあるため
                  session_count=1 → run() 内で 2 になり、B は挨拶分岐をスキップ。
                  active_live_sessions は B に差し替わる
greeting_trigger  辞書を引いて B を取得し Event(B) を set()。A は起きない
30秒後            A がタイムアウトして挨拶を発火
```

`live_ready送信` のログが1行しか出ないのは、B が挨拶分岐を通らないため。**観測とすべて整合する。**

**関連コード**
- `live_api_handler.py:577` — `_greeting_trigger_event` はセッションごとの新規インスタンス
- `live_api_handler.py:689-692` — `stop()` は `is_running=False` を立てるだけ。`wait()` は中断されない
- `app_customer_support.py:762-765, 926, 941-946` — `live_start` で旧セッション停止 → 新セッション生成 → `greeted_client_sids` ガード
- `app_customer_support.py:973-979` — `handle_greeting_trigger` は `active_live_sessions[client_sid]`（最新セッション）にのみ `set()`

### 4-2. 2回発火の経路（要確定・rev.2 で見解が分かれている）

**8/21 の記録（`f77bebe`）の主張:**
```
core-controller.ts:503 initializeSession() → :534 startLiveMode()
core-controller.ts:541 toggleRecording()   → :589 startLiveMode()
2回目は liveAudioManager.initialize() でマイクを取得するため
```

**本セッションでのコード読みの結論:** 2回とも `initializeSession():534` 経由。
`init()` が `resetAppContent()` を2回呼ぶことが原因（`core-controller.ts:94, 106`）。

根拠:
1. `toggleRecording()` の呼び出し元は `micBtn` の click 等3箇所のみ。**起動時には走らない**
2. `toggleRecording()` は `if (this.isLiveMode) { ... return; }` で早期 return する（`core-controller.ts:546-559`）。
   `startLiveMode()` 完了時に `isLiveMode = true` になるため、以降マイクを押しても `startLiveMode()` に到達しない
3. **ユーザー操作なしの Console ログで `[Reset] Starting soft reset...` が2回、
   各々に `[LiveAPI] startLiveMode完了` が1回ずつ対応**していた

**→ Phase 2 で確定させる。**

**なお、どちらの経路であっても以下は変わらない:**
- `startLiveMode()` は毎回 `liveAudioManager.initialize()`（マイク取得）を呼ぶ（`core-controller.ts:659`）
- 2回目の `resetAppContent()` は `7d16730`「init()完了後にresetAppContent()を追加実行し**リップシンクを正常化**」で**意図的に追加された**
- **クライアント側に多重起動ガードを入れる案は、マイク取得を塞ぐため 8/21 に却下済み**

### 4-3. 初期あいさつの A2E 経路（コード読み・実測未確認）

`_is_initial_greeting_phase` は本来「ダミーメッセージの `input_transcription` を非表示にする」ためのフラグだった
（`live_api_handler.py:548-550`、仕様書02 §4.5.5）。

`be0d9ce`（3/29）で、**同じフラグが A2E 経路の分岐にも流用された**。

`live_api_handler.py:993-1001`
```python
if self._is_initial_greeting_phase:
    self._greeting_pcm_buffer.extend(part.inline_data.data)   # 溜めるだけ、送らない
else:
    self._buffer_for_a2e(part.inline_data.data)               # 閾値でストリーミング送信
```

| | 音声 `live_audio` | blendshape係数 `live_expression` |
|---|---|---|
| 通常ターン | 到着ごとに即 emit | 閾値・句読点でストリーミング emit |
| **初期あいさつ** | **到着ごとに即 emit（分岐の外）** | **turn_complete まで一切送らない** |

**フロント側で導かれる帰結:**

`_send_a2e_ahead()` は `chunk_index=0` 固定で送信（`live_api_handler.py:1030`）。

`live-audio-manager.ts:290-294`
```typescript
if (data.chunk_index === 0) {
    this.firstChunkStartTime = 0;
    this._shouldResetStartTime = true;     // 「次のPCMで再設定する」
}
```

`firstChunkStartTime` に**非0を設定する箇所はコード全体で1箇所のみ** — `playPcmAudio()`（`live-audio-manager.ts:190-191`）。
**再アンカーには次のPCMチャンクが必要だが、挨拶は既に喋り終わっており PCM はもう来ない。**

`live-audio-manager.ts:240-242`
```typescript
getCurrentPlaybackOffset(): number {
    if (this.firstChunkStartTime === 0) return 0;   // ← ここに落ち続ける
```
→ `frameIndex = Math.floor(0/1000 * fps) = 0` → **常に先頭フレームだけを返す＝口が固まる**

**修正の順序が逆転している:**
```
03-29 04:06  be0d9ce  初期あいさつを turn_complete 一括送信に変更
03-30 02:07  380ec7d  chunk=0 到着で firstChunkStartTime をリセット
03-30 02:31  fe9a9e6  chunk=0 到着で即座に 0 クリア
```
後から入れた `380ec7d` / `fe9a9e6` が、先に入れた `be0d9ce` の経路を壊している。

**仕様書自身の記載**（`docs/12_shop_audio_a2e_sync_fix_spec.md:163-168`）:
> 1軒目はLiveAPIからストリーミングで音声が到着するため、
> `_emit_cached_audio` / `_emit_collected_shop` のような一括先行は**不可能**。

`_send_a2e_ahead` はキャッシュ済み音声（ショップ読み上げ）用に設計されたもので、
仕様書は「ストリーミング音声には使えない」と明記している。**初期あいさつはそのストリーミング音声のケース。**

### 4-4. ⚠️ 30秒がリップシンクを成立させている疑い

`9e384fd`（8/21 の Revert）の記述:

> 30秒の待ちが、初回あいさつのリップシンクを成立させるために**意図せず効いている可能性が高い**。
>
> 「初回あいさつだけリップシンクが動かない」「リロードすると直る」という問題は、
> **診断ログ50箇所以上・テスト300回以上**を投じても根本原因が特定できず、
> 暫定対処として初回起動時に処理を重ねる形で回避された経緯がある。
> 上手くいったと思っても再発を繰り返しており、**単一の原因ではなく起動シーケンス全体の競合状態が疑われる領域**。
>
> この状況で「1回テストして動いたから大丈夫」とは言えない。

**→ 30秒ゲートと2回発火は、どちらも単独では外せない。**
両方が初回リップシンクの成立に寄与している可能性がある。

### 4-5. LiveAPI と Google検索（決着済み・再挑戦しない）

`claude/update-avatar-startup-512p2` の 4/27 の試行記録:
```
17:16  f1420fb  Add Google Search SDK to LiveAPI tools config
17:37  90a5677  Fix LiveAPI tools config: use dict style per official docs
17:47  c179026  Revert "Fix LiveAPI tools config..."
17:47  1a48266  Revert "Add Google Search SDK to LiveAPI tools config"
18:12  14b3369  Update google-genai SDK from 1.68.0 to 1.73.1
18:24  5dcffb6  Re-add google_search to LiveAPI tools (SDK 1.73.1 + dict style)
18:30  fce36dc  Revert google_search from LiveAPI tools (causes 1011 error)  ★
18:36  d3815f8  Test: google_search only (no function_declarations) for isolation
18:43  f8f31ef  Revert to stable: google_search single test also fails
05-03  60408d4  Add Google Search via Function Calling (REST API workaround)  ★決着
```

**LiveAPI に `google_search` を入れると 1011 エラーになるという実証結果が出ている。**
現在は `GOOGLE_SEARCH_DECLARATION` の Function Calling 経由で `gemini-2.5-flash` の REST API を呼ぶ回避策が稼働中。

**→ この件は決着済み。本計画では再挑戦しない。**

---

## 5. 未確認事項

| # | 未確認点 | 解消手段 |
|---|---|---|
| U1 | 2回発火の経路（`resetAppContent()` 2回 か `toggleRecording()` か） | Phase 2 の実測 |
| U2 | 30秒ゲートを外すと初回リップシンクが壊れるか | Phase 4 の検証（単独では試さない） |
| U3 | 2回目の `resetAppContent()` を外すとリップシンクが再発するか | Phase 4 の検証 |
| U4 | 3.1 で `_build_config()` の各設定キーが有効か（`realtime_input_config` / `context_window_compression` 等） | 4/27 以降 本番稼働中のため実質検証済み。エラー有無をログで確認 |
| U5 | §4-3 の A2E 凍結連鎖が実機で起きているか | Phase 2 の Console ログ |

### 5-1. 既知の不一致（今回の作業とは無関係）

`/health` が `audio2exp: not configured` を返す。

- `app_customer_support.py:65` — `AUDIO2EXP_SERVICE_URL` を読む（**ワークフローは設定していない**）
- `live_api_handler.py:33` — `A2E_SERVICE_URL` を読む（**ワークフローが設定している**。デフォルト値もあり）
- `.github/workflows/deploy-cloud-run.yml:80` — `A2E_SERVICE_URL` のみ渡している

**環境変数名の不一致。A2E の実処理は `live_api_handler.py` 側なので動作には影響しないが、`/health` の表示だけが誤る。**
今回の復旧作業で生じたものではない。**本計画では触らない。**

---

## 6. 実行順序

```
Phase 0  復旧（完了）
Phase 1  事実の再確認（コード読み。ほぼ完了）
Phase 2  残った未確認点の実測 ── 1回の起動で U1 / U5 を確定
Phase 3  初期あいさつ同期設計の決定（ユーザー判断）
Phase 4  実装（1修正1コミット）
Phase 5  REST モデル切替（gemini-3.5-flash-lite）
```

**Phase 6（Google検索の LiveAPI 移行）は削除。** §4-5 のとおり決着済み。

---

## 7. Phase 詳細

### Phase 0 — 復旧（完了）

2026-08-22 完了。§2-3 参照。

### Phase 1 — 事実の再確認（ほぼ完了）

§4 に記載のとおり。残る論点は §5 の U1 / U5。**コード変更なし。**

### Phase 2 — 残った未確認点の実測

**目的**: U1（2回発火の経路）と U5（A2E 凍結連鎖）を、**1回の起動**で確定する。

**コード変更**: **なし。新規診断コードは入れない。**

`main` には 8/21 の診断ログ（`54e1749`）が入っていないが、
**30秒の機構は既に確定しているため、再投入の必要はない。**

**観測に使う既存ログ（フロント Console）**

| ログ文言 | 場所 | 何が分かるか |
|---|---|---|
| `[Reset] Starting soft reset...` | `core-controller.ts:121` | `resetAppContent()` の回数 |
| `[LiveAPI] startLiveMode完了` | `core-controller.ts:672` | `live_start` の回数 |
| `[LiveAPI] Socket未接続、startLiveMode中止` | `core-controller.ts:651` | 中止の有無 |
| `[ConciergeController] greeting_trigger送信` | `concierge-controller.ts:72` | emit の有無と時刻 |
| `[LessonController] greeting_trigger送信` | `lesson-controller.ts:67` | 同上（レッスンモード） |
| `[Sync] StartTime reset to: N` | `live-audio-manager.ts:193` | 同期の再アンカー |
| `[Sync] live_expression chunk=0 受信 → StartTime=0にクリア` | `live-audio-manager.ts:293` | chunk=0 到着 |
| `[A2E Buffer] chunk=N, +Nframes, total=N, firstChunkStartTime=N` | `live-audio-manager.ts:307` | **凍結の直接証拠** |
| `[A2E Sync] offsetMs=N, frameIdx=N/N, jawOpen=N` | `live-audio-manager.ts:268` | **frameIdx が 0 で固定なら凍結** |

**観測に使う既存ログ（Cloud Run）**

| ログ文言 | 場所 |
|---|---|
| `[LiveAPI] live_ready送信 → greeting_trigger待機` | `live_api_handler.py:726` |
| `[LiveAPI] greeting_trigger受信: アバター準備完了` | `live_api_handler.py:671` |
| `[LiveAPI] greeting_trigger タイムアウト（30秒）、greeting発火します` | `live_api_handler.py:733` |
| `[A2E] 初期あいさつA2E先行送信: N bytes` | `live_api_handler.py:925` |
| `[LiveAPI] greeting_done送信` | `live_api_handler.py:941` |

**判定基準**

U1（2回発火の経路）:

| 観測 | 結論 |
|---|---|
| `[Reset] Starting soft reset...` が2回、各々に `startLiveMode完了` が1回ずつ | **`resetAppContent()` 2回呼びが原因** |
| `[Reset]` が1回で `startLiveMode完了` が2回 | **別経路。8/21 の記録が正しい** |

U5（A2E 凍結連鎖）:

| 観測 | 結論 |
|---|---|
| 初回あいさつで `chunk=0` の後に `chunk=1` 以降が来ない、かつ `[A2E Sync] frameIdx=0/N` が固定 | **§4-3 の連鎖が実機で起きている** |
| `chunk=0` の後に `[Sync] StartTime reset to:` が出て `chunk=1` 以降が続く | **連鎖は起きていない。読みが誤り** |

**手順**
1. **シークレットウィンドウ**でブラウザ Console を開く
2. アプリを起動（**ユーザー操作は一切しない**）
3. 初期あいさつが終わるまで待つ
4. Console ログを全量取得
5. 同時刻の Cloud Run ログを取得

```powershell
gcloud logging read `
  "resource.type=cloud_run_revision AND resource.labels.service_name=chatty-sp-base" `
  --project=ai-avator-492205 `
  --limit=150 `
  --format="value(timestamp,textPayload,jsonPayload.message)" `
  --freshness=10m
```

**この Phase の成果物**: U1 / U5 の確定。**修正はしない。**

### Phase 3 — 初期あいさつ同期設計の決定

**目的**: 症状への対処ではなく、「初期あいさつはどう動くのが正しいか」を仕様として決める。

**決めること（すべてユーザー判断。Claude は選択肢と事実の提示のみ）**

| # | 決定事項 | 論点 |
|---|---|---|
| D1 | 音声と expression の同期をどう取るか | 初期あいさつも通常ターンと同じストリーミング経路にするか。それとも音声側の再生開始を待たせるか |
| D2 | ダミー問い掛け（`INITIAL_GREETING_TRIGGERS`）は必要か | 公式は "Live API expects user input before it responds" と明記。3.1 での実挙動は未検証 |
| D3 | プロンプト側の固定文指定（`live_api_handler.py:348-360, 385-399`）は残すか | 公式推奨は「挨拶するよう指示」であって「この文言を喋れ」ではない |
| D4 | 30秒ゲートは必要か | **単独では外せない**（§4-4）。D1 の結論とセットで判断 |
| D5 | 2回発火は廃止してよいか | **マイク取得を塞がない形でのみ可**（8/21 に却下済みの案あり）。U3 の検証が前提 |

**公式ドキュメントの根拠（確認済み）**
- "Live API expects user input before it responds."
- "To have Live API initiate the conversation, include a prompt asking it to greet the user or begin the conversation. Include information about the user to have Live API personalize that greeting."
- Proactive audio は「応答しないことを能動的に判断する」機能であり speak-first 機能ではない。かつ **3.1 では非対応**

**現場報告（一次資料ではない・未解決）**
- Google AI Developers Forum / python-genai issue #1533:
  native-audio preview モデルでプロンプトのみでは喋り出さないという報告

**⚠️ D1・D4・D5 は互いに依存する。個別に決めず、セットで決めること。**

### Phase 4 — 実装

**目的**: Phase 3 の決定を実装する。

**進め方**
- **1修正1コミット**
- 各修正後にユーザーが動作確認
- **効かなかった修正は次を試す前に戻す**
- **2回試して直らなければ止めて報告**
- **`chatty-base/**` を含む push は、事前にユーザーの承認を得る**（本番デプロイのため）

**変更対象になりうるファイル**（Phase 3 の決定次第）
- `chatty-base/live_api_handler.py`（A2E経路、30秒ゲート、ダミー発話、プロンプト固定文）
- `src/scripts/chat/live-audio-manager.ts`（同期ロジック）
- `src/scripts/chat/core-controller.ts`（`resetAppContent()` 2回呼び）
- `chatty-base/app_customer_support.py`（`greeted_client_sids` ガード）

**禁止事項**
- 症状を隠すガード・フォールバックの追加
- 複数ファイルの同時変更
- 「ついで」の修正
- **リップシンクの検証を1回のテストで済ませること**（§4-4 の警告）

### Phase 5 — REST モデル切替

**目的**: REST API のモデルを `gemini-2.5-flash` → `gemini-3.5-flash-lite` に切り替える。

**lite を選ぶ根拠（ユーザーの実証結果）**
> 他プロジェクトで 3.7 は余計なことまで気が回りハルシネーションが強い傾向があり、
> 定型作業に近い場合は lite の方がシュアーなテスト結果が出た。

**公式確認済みの前提**
- `gemini-3.5-flash-lite` は **Stable**
- 入力 1,048,576 / 出力 65,536 トークン
- **Search grounding ✓ / Function calling ✓ / Structured outputs ✓ / Thinking ✓**
- Live API 非対応（REST 専用。本用途では問題なし）
- 参考: 公式は 3.5 世代を "legacy" と表記。最新 Stable は `gemini-3.7-flash`

**変更箇所（本番4箇所）— リスクの低い順に1箇所ずつ**

| # | ファイル:行 | 用途 | リスク |
|---|---|---|---|
| 5-1 | `chatty-base/support_core.py:772` | 最終サマリー生成 | 低（ツールなし） |
| 5-2 | `chatty-base/support_core.py:894` | 会話要約生成 | 低（ツールなし） |
| 5-3 | `chatty-base/support_core.py:678` | テキストチャット本体 | 中（Google検索グラウンディング使用） |
| 5-4 | `chatty-base/app_customer_support.py:872` | ショップ検索（案C） | **高（検索 + 5軒の厳密なJSON生成）** |

**⚠️ 追加の対象候補**: `live_api_handler.py` の `_handle_google_search()`（`60408d4`）も
`gemini-2.5-flash` を呼んでいる可能性がある。Phase 5 着手時に確認すること。

**5-4 の重点検証項目**
1. Google検索グラウンディングが動作するか
2. **5軒が返るか**（`SEARCH_ONLY_PROMPT` の「必ず5軒」指示への追従）
3. **JSON構造が仕様通りか**（`docs/07_shop_card_json_spec.md`）
4. 「検索できません」等の拒否が出ないか
5. ショップカードが正しく表示されるか

**既知の制約**（`support_core.py:666-669`）
```python
# Google検索(tools)を使う場合は、response_mime_type="application/json" を
# 指定してはいけません（400エラーの原因になります）。
```
→ 3.5-flash-lite でも同じか要確認。

**5-4 が不合格だった場合の選択肢**（ユーザー判断）
- ショップ検索のみ上位モデル（`gemini-3.5-flash` / `3.6-flash` / `3.7-flash`）
- ショップ検索のみ現行維持（`gemini-2.5-flash`）
- プロンプト側の調整

**対象外**
- 開発ツール（`extract_menu.py` / `match_images.py` / `upload_and_match_images.py`）
- TTS（`ja-JP-Chirp3-HD-Leda`。Google Cloud TTS で Gemini とは別系統）
- 未使用の旧SDK初期化（`support_core.py:34`。参照箇所0件）

---

## 8. 横展開の予定

Chatty-sp で検証したのち、以下へも適用する予定。

- **Travel-sp**（`travel-sp-base` / `https://travel-sp.vercel.app`）
- **ai-mtg-assistant**

各 Phase の**変更内容・確認項目・判定結果は、他プロジェクトへ転用できる粒度で記録する**。

横展開時の注意:
- 各プロジェクトでファイルパス・行番号は異なる。本書の行番号は Chatty-sp のもの
- **同じ基底クラス（`core-controller.ts` の `initializeSession` / `toggleRecording`）を使うため、同じ問題がある可能性が高い**（8/21 の記録より）
- **各プロジェクトのデプロイ構成（トリガーブランチ）を先に確認すること**。§2 の事故は横展開先でも起こりうる
- 横展開は Chatty-sp での検証完了後。並行実施はしない

---

## 9. 本計画で「やらないこと」

- `CLAUDE.md` の編集（CLAUDE.md により禁止）
- `docs/` 配下の既存仕様書の編集（同上。本計画書の更新は許可済み）
- `DESIGN_SPEC_PHASE1.md` の編集（同上）
- `.github/workflows/` の編集（同上）
- `api_integrations.py` / `long_term_memory.py` の編集（同上）
- 症状を隠すガード・フォールバックの追加
- **Google検索の LiveAPI 移行の再挑戦**（§4-5 で決着済み）
- `/health` の `audio2exp` 環境変数名の不一致の修正（§5-1。別件）
- 未マージブランチのマージ・破棄（ユーザー判断待ち）
- 複数 Phase の同時実行
- 「ついで」の修正

---

## 10. 参照資料

### プロジェクト内
- `CLAUDE.md` — プロジェクト規約
- `docs/09_liveapi_migration_design_v6.md` — V6統合仕様書
- `docs/12_shop_audio_a2e_sync_fix_spec.md` — A2E同期仕様（§3.1.3, §3.1.4）
- `docs/07_shop_card_json_spec.md` — ショップカードJSON仕様
- `docs/handover_20260524_30s_and_double_reset.md` — 引継ぎメモ（`claude/planning-app-dev-cu8PX`）

### 重要コミット
| コミット | 日付 | 内容 |
|---|---|---|
| `94d4e0e` | 03-30 | 30秒 greeting_trigger ゲート導入 |
| `be0d9ce` | 03-29 | 初期あいさつを A2E 一括処理に変更 |
| `380ec7d` / `fe9a9e6` | 03-30 | chunk=0 で firstChunkStartTime をクリア |
| `7d16730` | 03-30 | `init()` 完了後に `resetAppContent()` 追加実行（2回発火） |
| `000981f` | 04-27 | LiveAPI モデルを 3.1 に切替 |
| `fce36dc` | 04-27 | LiveAPI の google_search を撤退（1011エラー） |
| `60408d4` | 05-03 | Google検索を FC 経由の REST API 呼び出しで実装 |
| `54e1749` | 08-21 | 30秒問題の診断ログ（**未マージ**） |
| `f77bebe` | 08-21 | Event 共有による修正（**Revert 済み**） |
| `9e384fd` | 08-21 | 上記の Revert（理由の記述が重要） |
| `fe21436` | 08-22 | 本番復旧マージ |

### 公式ドキュメント
- Models | Gemini API — https://ai.google.dev/gemini-api/docs/models
- Gemini 3.1 Flash live preview — https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview
- Gemini 3.5 Flash-Lite — https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- Gemini deprecations — https://ai.google.dev/gemini-api/docs/deprecations
- Live API best practices — https://ai.google.dev/gemini-api/docs/live-api/best-practices
- Live API capabilities guide — https://ai.google.dev/gemini-api/docs/live-api/capabilities
- Tool use with Live API — https://ai.google.dev/gemini-api/docs/live-api/tools

---

## 11. 進捗記録

| Phase | 状態 | 実施日 | 備考 |
|---|---|---|---|
| 計画書 初版 | 完了 | 2026-08-22 | 前提に誤りあり |
| Phase 1 LiveAPIモデル切替（初版） | **取消** | 2026-08-22 | 4/27 に実施済みだった。復旧マージで元のコメントに復元 |
| **本番退行と復旧** | **完了** | 2026-08-22 | §2-2 / §2-3 |
| 計画書 rev.2 | 完了 | 2026-08-22 | 本書 |
| Phase 2 実測 | **未着手（次はここ）** | | U1 / U5 の確定 |
| Phase 3 同期設計の決定 | 未着手 | | |
| Phase 4 実装 | 未着手 | | |
| Phase 5 RESTモデル切替 | 未着手 | | |
