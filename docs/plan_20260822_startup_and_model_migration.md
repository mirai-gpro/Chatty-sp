# 初期起動改善 + LLMモデル移行 実行計画

**作成日**: 2026-08-22
**対象ブランチ**: `claude/initial-startup-improvement-sr72o3`
**対象リポジトリ**: `mirai-gpro/Chatty-sp`

---

## 0. 本書の位置づけと作業ルール

### 位置づけ
α版テストに進むにあたり、初期起動の暫定処置（30秒待機・2回発火）を抜本改善する。
併せて、LLMモデルの世代移行を実施する。

### 横展開の予定

本修正は Chatty-sp で検証したのち、以下の派生プロジェクトへも同様に適用する予定。

- **Travel-sp**（バックエンド `travel-sp-base` / フロント `https://travel-sp.vercel.app`）
- **ai-mtg-assistant**

このため、各 Phase の**変更内容・確認項目・判定結果は、他プロジェクトへ転用できる粒度で記録する**。
Chatty-sp 固有の事情に依存する判断があれば、その旨を明記すること。

横展開時の注意:
- 各プロジェクトでファイルパス・行番号は異なる。本書の行番号は Chatty-sp のもの
- モデル定数の定義箇所は各プロジェクトで個別に確認すること
- 横展開は Chatty-sp での検証完了後。並行実施はしない

### 本作業で厳守するルール

CLAUDE.md に加え、本セッションで合意した運用ルール。

1. **診断ログ・診断コードを入れる前に、コード読みで答えが出るか先に問う。** 読めば分かるなら読む
2. **ログを入れる場合は、確認したい未確認点を1つに絞ってから提案する。** 「とりあえず可視化」はしない
3. **効かなかった修正は、次を試す前に必ず戻す。** 変数を同時に2つ動かさない
4. **症状を隠すガード・フォールバックは提案しない**（CLAUDE.md §4）
5. **2回試して直らなかったら止めて報告する**
6. **1修正1コミット。** 各修正後にユーザーが動作確認する
7. **原因の特定・修正内容の決定はユーザー。** Claude は事実収集・整理・実行に限定

---

## 1. 背景 ― 確定している事実

### 1-1. 現在の症状

- Chatty-sp 起動時、毎回きっかり **30秒** のコールドスタート待機が発生する
- 初期起動時に `live_start` が **2回** 発火し、LiveAPI セッションが2つ作られる

### 1-2. 直接原因となっている2つの暫定処置

| # | 内容 | 場所 | 導入コミット |
|---|---|---|---|
| A | 30秒 `greeting_trigger` ゲート | `chatty-base/live_api_handler.py:729-733` | `94d4e0e` (2026-03-30 01:43 UTC) |
| B | `init()` 完了後の `resetAppContent()` 追加実行 | `src/scripts/chat/core-controller.ts:106` | `7d16730` (2026-03-30 07:56 UTC) |

**両方とも、初期あいさつのリップシンク不具合への対処として導入された。**
コミットメッセージがそれを示している。

- `94d4e0e`: "delay greeting until avatar ready (greeting_trigger gate)"
- `7d16730`: "init()完了後にresetAppContent()を追加実行し**リップシンクを正常化**"

### 1-3. 経緯（git履歴で確認済み）

```
03-28〜03-29  リップシンク不具合の対処
              jawOpen閾値 0.001→0.005→0.015、スムージング無効化、
              句読点フラッシュ、A2E先行方式、bisect（二分探索リバート）
              → 効果なし

03-30 00:44〜01:04  初期起動とリロードのフロー差を追う
              hypothesis 1 (isUserInteracted強制)  1452ae7
              hypothesis 2 (AudioContext.resume強制) 6380cc4
              hypothesis 3 (LAMAvatarController待機) f1669da → 89f82f2 で撤去
              → 4〜9分間隔。仮説の検証が成立していない

03-30 01:43   30秒ゲート導入  94d4e0e   ★現存

03-30 05:28〜07:56  暫定処置に妥協
              b4a1948  init()をresetAppContent()経由に統一
              f870511  init()完了後にresetAppContent()自動実行
              748b004  initializeSession()の二重呼び出しを解消（一度は整理）
              7d16730  init()完了後にresetAppContent()を追加実行  ★現存＝2回発火
```

`748b004` で一度「二重呼び出しを解消」しているが、`7d16730` で**再追加**されて現在に至る。

---

## 2. 根本原因の候補 ― コード読みで導出（実測未実施）

### 2-1. 初期あいさつだけ A2E 経路が別になっている

`_is_initial_greeting_phase` は**本来1つの目的**で作られたフラグ。

`live_api_handler.py:548-550`
```python
# 初期あいさつフェーズ（ダミーメッセージのinput_transcriptionを非表示）
# （仕様書02 セクション4.5.5）
self._is_initial_greeting_phase = True
```

`be0d9ce`（03-29 04:06「初期あいさつをA2E先行方式で一括処理」）で、
**同じフラグが A2E 経路の分岐にも流用された**。

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

音声の emit（`live_api_handler.py:995-999`）は分岐の外にあるため、
**初期あいさつでは音声だけが先に流れ、係数はターン完了後にまとめて届く。**

### 2-2. フロント側で起きること（決定論的）

`_send_a2e_ahead()` は `chunk_index=0` 固定で送信する（`live_api_handler.py:1030`）。

`src/scripts/chat/live-audio-manager.ts:290-294`
```typescript
if (data.chunk_index === 0) {
    this.firstChunkStartTime = 0;          // 同期の基準時刻をクリア
    this._shouldResetStartTime = true;     // 「次のPCMで再設定する」
}
```

`firstChunkStartTime` に**非0を設定する箇所はコード全体で1箇所のみ**（grep 全出現確認済み）。
`playPcmAudio()` の中（`live-audio-manager.ts:190-191`）。

**→ 再アンカーには「次のPCMチャンク」が必要。しかし挨拶は既に喋り終わっており、PCMはもう来ない。**

`live-audio-manager.ts:240-242`
```typescript
getCurrentPlaybackOffset(): number {
    if (this.firstChunkStartTime === 0) return 0;   // ← ここに落ち続ける
```
→ `getCurrentExpressionFrame()` で `frameIndex = Math.floor(0/1000 * fps) = 0`
→ **常に先頭フレームだけを返し続ける＝口が固まる**（`live-audio-manager.ts:252-259`）

### 2-3. 修正の順序が逆転している

```
03-29 04:06  be0d9ce  初期あいさつを turn_complete 一括送信に変更
03-30 02:07  380ec7d  chunk=0 到着で firstChunkStartTime をリセット
03-30 02:31  fe9a9e6  chunk=0 到着で即座に 0 クリア
```

**後から入れた `380ec7d` / `fe9a9e6` が、先に入れた `be0d9ce` の経路を壊している。**

### 2-4. 仕様書自身が「不可能」と記載している

`docs/12_shop_audio_a2e_sync_fix_spec.md:163-168`
> **1軒目はLiveAPIからストリーミングで音声が到着するため、
> `_emit_cached_audio` / `_emit_collected_shop` のような一括先行は不可能。**

`_send_a2e_ahead()` は**キャッシュ済み音声（ショップ読み上げ）用**に設計されたもので、
仕様書は「ストリーミング音声には使えない」と明記している。
**初期あいさつは、まさにそのストリーミング音声のケース。**

### 2-5. ★未解決の矛盾（重要）

上記2-1〜2-4とは別に、**コード読みと症状が食い違う点がある。**

`live_start` が2回・同一sid と仮定すると：
- **セッションA**: 30秒待機 → Gemini に挨拶トリガー送信 → しかし `stop()` により
  `is_running=False` → `_receive_and_forward` の while 条件が偽 → **応答をブラウザに転送しない**
  （`live_api_handler.py:691, 905`）
- **セッションB**: `greeted_client_sids` ガードで `session_count=2` → **挨拶をスキップ**
  （`app_customer_support.py:941-944` / `live_api_handler.py:706, 711, 722`）

→ **どちらも喋らない＝挨拶が一切鳴らないはず。しかし実際は30秒後に鳴る。**

**この矛盾は Phase 2 の実測で解消する。**

---

## 3. 未確認事項

| # | 未確認点 | 解消手段 |
|---|---|---|
| U1 | `greeting_trigger` が実際に emit されているか（`concierge-controller.ts:69-73` の `if (this.socket && this.socket.connected)` ガードを通過しているか。失敗時のリトライもログもない） | Console ログ |
| U2 | 30秒後に挨拶を発話しているのがセッションAなのかBなのか、あるいは第3の経路か | Cloud Run ログ |
| U3 | 2回目の `resetAppContent()` を外すとリップシンク不具合が再発するか | Phase 4 で検証 |
| U4 | 3.1 で `_build_config()` の各設定キーが有効か | Phase 1 で検証 |

### Phase 2 で判別する3仮説

| 予測される観測 | H1 | H2 | H3 |
|---|---|---|---|
| サーバ `live_ready送信 → greeting_trigger待機` 回数 | 1回 | 2回 | 1回 |
| サーバ `greeting_trigger タイムアウト（30秒）` 回数 | 1回 | 1〜2回 | 1回 |
| サーバ `greeting_trigger受信` | 無し | 無し | 有無どちらも可 |
| Console `[Reset] Starting soft reset...` 回数 | 2回 | 2回 | 2回 |
| Console `[LiveAPI] startLiveMode完了` 回数 | 1回 | 2回 | 2回 |
| Console `Socket未接続、startLiveMode中止` / `startLiveModeエラー` | 有り | 無し | 無し |

- **H1**: `live_start` は実は1回しか飛んでいない（1回目がマイク取得失敗 or socket未接続で中止）
- **H2**: 2回飛んでいるが `greeted_client_sids` ガードが効いていない
- **H3**: 停止済みセッションでも音声が転送される経路がある（2-5 の読みが誤り）

---

## 4. 全体方針

### 4-1. 順序の根拠

初期起動問題の原因を、モデル依存性で分解した結果：

| 問題 | 発生場所 | モデル依存か |
|---|---|---|
| A2Eリップシンク凍結（2-2） | フロントの `live-audio-manager.ts` 同期ロジック | **完全に非依存** |
| 30秒ゲート | サーバ。A2E問題への対処 | 非依存 |
| 2回発火 | フロント。同じくA2E問題への対処 | 非依存 |
| ダミー問い掛けの要否 | LiveAPI の仕様 | **モデル依存** |

**→ 元凶と特定した部分はモデルに依存しない。**
モデル切替で起動問題が直ることは期待できないし、切替で調査が無駄になることもない。

**モデル切替（Phase 1）を先に行う理由:**
初期起動問題について、**まだ一度も実測していない**。
ここで 2.5 のままベースラインを取り、後から 3.1 に切り替えると実測を捨てることになる。
α版で 3.1 で出すなら、ベースラインは 3.1 で取るべき。

### 4-2. 実行順序

```
Phase 1  LiveAPI モデル切替（gemini-3.1-flash-live-preview）
Phase 2  初期起動ベースライン実測（3.1上、コード変更なし）
Phase 3  初期あいさつ同期設計の決定（ユーザー判断）
Phase 4  初期起動の実装
Phase 5  REST モデル切替（gemini-3.5-flash-lite）
Phase 6  Google検索の LiveAPI 移行（設計検討から）
```

---

## 5. Phase 詳細

### Phase 1 — LiveAPI モデル切替

**目的**: 使用モデルを `gemini-3.1-flash-live-preview` に切り替え、後続の実測・対策を移行後モデル上で行う。

**変更箇所（1箇所のみ）**

`chatty-base/live_api_handler.py:42-43`
```python
# stt_stream.py から転記（変更禁止）
LIVE_API_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
```
↓
```python
LIVE_API_MODEL = "gemini-3.1-flash-live-preview"
```

**⚠️ 未決定事項**: 42行目の `# stt_stream.py から転記（変更禁止）` コメントの扱い（残す / 更新 / 削除）→ **ユーザー指示待ち**

**参照箇所**: `live_api_handler.py:718`（メインセッション）、`live_api_handler.py:1490`（ショップ紹介用セッション）。両方この定数を参照するため、1行変更で両方切り替わる。

**公式確認済みの前提**
- `gemini-3.1-flash-live-preview` は Preview、リリース 2026-03-11
- deprecations ページで `gemini-2.5-flash-native-audio-preview-12-2025` の**推奨移行先**として指定されている
- 3.1 の非対応機能（Proactive audio / Affective dialogue / Async function calling）は**現行コードで1つも使用していない**（grep で 0件確認済み）
- Function calling は 3.1 では sequential のみ。現行コードは既に sequential 実装
- 出力トークン上限: 8,192 → 65,536

**確認項目（Phase 1 の合否判定）**

| # | 項目 | 合格基準 |
|---|---|---|
| 1 | 会話が成立するか | ユーザー発話 → AI音声応答が往復する |
| 2 | Function calling が発火するか | `search_shops`（chat/conciergeモード）、`recommend_menu`（注文サポート） |
| 3 | A2E リップシンクが動くか | **2ターン目以降**で口が動く（初期あいさつは既知の不具合があるため対象外） |
| 4 | `_build_config()` の設定キーがエラーにならないか | `realtime_input_config` / `context_window_compression` / `input_audio_transcription` / `output_audio_transcription` でエラーが出ない |

**記録のみ（合否判定に使わない）**
- 起動時の症状（30秒待機・挨拶の有無）が今と同じか、変わったか
  → 変化した場合、それ自体が Phase 2 の手がかりになる

**切り戻し**: 1行 revert

**やらないこと**
- `_build_config()` の設定変更
- `api_version` / `http_options` の追加
- プロンプトの変更
- Phase 2 以降の作業

---

### Phase 2 — 初期起動ベースライン実測

**目的**: §3 の H1/H2/H3 を判別し、§2-5 の矛盾を解消する。

**コード変更**: **なし。新規診断コードは入れない。**

**観測に使う既存ログ**

サーバ（Cloud Run）:
| ログ文言 | 場所 |
|---|---|
| `[LiveAPI] live_ready送信 → greeting_trigger待機` | `live_api_handler.py:726` |
| `[LiveAPI] greeting_trigger受信: アバター準備完了` | `live_api_handler.py:671` |
| `[LiveAPI] greeting_trigger タイムアウト（30秒）、greeting発火します` | `live_api_handler.py:733` |
| `[LiveAPI] 初期あいさつトリガー送信: '...'` | `live_api_handler.py:746` |
| `[A2E] 初期あいさつA2E先行送信: N bytes` | `live_api_handler.py:925` |
| `[LiveAPI] greeting_done送信` | `live_api_handler.py:941` |

フロント（ブラウザ Console）:
| ログ文言 | 場所 |
|---|---|
| `[Reset] Starting soft reset...` | `core-controller.ts:121` |
| `[LiveAPI] Socket接続完了` | `core-controller.ts:643` |
| `[LiveAPI] Socket未接続、startLiveMode中止` | `core-controller.ts:651` |
| `[LiveAPI] startLiveMode完了` | `core-controller.ts:672` |
| `[ConciergeController] greeting_trigger送信` | `concierge-controller.ts:72` |
| `[Sync] StartTime reset to: N` | `live-audio-manager.ts:193` |
| `[Sync] live_expression chunk=0 受信 → StartTime=0にクリア` | `live-audio-manager.ts:293` |
| `[A2E Buffer] chunk=N, +Nframes, total=N, ...` | `live-audio-manager.ts:307` |
| `[A2E Sync] offsetMs=N, frameIdx=N/N, jawOpen=N` | `live-audio-manager.ts:268` |

**手順**
1. ブラウザ Console を開いた状態でアプリを起動（1回）
2. 初期あいさつが終わるまで待つ
3. Console ログを全量取得
4. 同時刻の Cloud Run ログを取得

```powershell
gcloud logging read `
  "resource.type=cloud_run_revision AND resource.labels.service_name=chatty-sp-base" `
  --project=ai-avator-492205 `
  --limit=100 `
  --format="value(timestamp,textPayload,jsonPayload.message)" `
  --freshness=10m
```

**判定**: §3 の表と突き合わせて H1/H2/H3 を確定する。

**この Phase の成果物**: どの仮説が正しいかの確定。**修正はしない。**

---

### Phase 3 — 初期あいさつ同期設計の決定

**目的**: 症状への対処ではなく、「初期あいさつはどう動くのが正しいか」を仕様として決める。

**決めること（すべてユーザー判断。Claude は選択肢と事実の提示のみ）**

| # | 決定事項 | 論点 |
|---|---|---|
| D1 | 音声と expression の同期をどう取るか | 初期あいさつも通常ターンと同じストリーミング経路にするか。それとも音声側の再生開始を待たせるか |
| D2 | ダミー問い掛け（`INITIAL_GREETING_TRIGGERS`）は必要か | 公式は "Live API expects user input before it responds" と明記。一方で公式推奨は「プロンプトで挨拶を指示」。3.1 での実挙動は未検証 |
| D3 | プロンプト側の固定文指定（`live_api_handler.py:348-360, 385-399`）は残すか | 公式推奨は「挨拶するよう指示」であって「この文言を喋れ」ではない |
| D4 | 30秒ゲートは必要か | D1 の結論次第で不要になる可能性 |
| D5 | 2回発火は廃止してよいか | U3（リップシンク再発）の検証が前提 |

**公式ドキュメントの根拠（確認済み）**
- "Live API expects user input before it responds."
- "To have Live API initiate the conversation, include a prompt asking it to greet the user or begin the conversation. Include information about the user to have Live API personalize that greeting."
- Proactive audio は「応答しないことを能動的に判断する」機能であり、speak-first 機能ではない。かつ **3.1 では非対応**

**現場報告（一次資料ではない）**
- 旧モデルではダミー発話が機能したが、`gemini-2.5-flash-native-audio-preview-09-2025` では「the model never said a word」との報告あり（Google AI Developers Forum / python-genai issue #1533）。**いずれも未解決**

---

### Phase 4 — 初期起動の実装

**目的**: Phase 3 の決定を実装する。

**進め方**
- **1修正1コミット**
- 各修正後にユーザーが動作確認
- **効かなかった修正は次を試す前に戻す**
- **2回試して直らなければ止めて報告**

**変更対象になりうるファイル**（Phase 3 の決定次第）
- `chatty-base/live_api_handler.py`（A2E経路、30秒ゲート、ダミー発話、プロンプト固定文）
- `src/scripts/chat/live-audio-manager.ts`（同期ロジック）
- `src/scripts/chat/core-controller.ts`（`resetAppContent()` 2回呼び）
- `chatty-base/app_customer_support.py`（`greeted_client_sids` ガード）

**禁止事項**
- 症状を隠すガード・フォールバックの追加
- 複数ファイルの同時変更（影響範囲が追えなくなるため）
- 「ついで」の修正

---

### Phase 5 — REST モデル切替

**目的**: REST API のモデルを `gemini-2.5-flash` → `gemini-3.5-flash-lite` に切り替える。

**lite を選ぶ根拠（ユーザーの実証結果）**
> 他プロジェクトで 3.7 は余計なことまで気が回りハルシネーションが強い傾向があり、
> 定型作業に近い場合は lite の方がシュアーなテスト結果が出た。

**→ 本計画では lite を第一候補として検証する。**

**公式確認済みの前提**
- `gemini-3.5-flash-lite` は **Stable**
- 入力 1,048,576 / 出力 65,536 トークン
- **Search grounding ✓ / Function calling ✓ / Structured outputs ✓ / Thinking ✓**
- Live API は非対応（REST 専用。本用途では問題なし）
- 参考: 公式は 3.5 世代を "legacy" と表記。最新 Stable は `gemini-3.7-flash`

**変更箇所（本番4箇所）**

| # | ファイル:行 | 用途 | リスク |
|---|---|---|---|
| 5-1 | `chatty-base/support_core.py:772` | 最終サマリー生成 | 低（ツールなし・要約のみ） |
| 5-2 | `chatty-base/support_core.py:894` | 会話要約生成 | 低（ツールなし・要約のみ） |
| 5-3 | `chatty-base/support_core.py:678` | テキストチャット本体 | 中（Google検索グラウンディング使用） |
| 5-4 | `chatty-base/app_customer_support.py:872` | ショップ検索（案C） | **高（Google検索 + 5軒の厳密なJSON生成）** |

**進め方**: **リスクの低い順に、1箇所ずつ。** 5-1 → 5-2 → 5-3 → 5-4

**5-4 の重点検証項目**
1. Google検索グラウンディングが動作するか
2. **5軒が返るか**（`SEARCH_ONLY_PROMPT` の「必ず5軒」指示への追従）
3. **JSON構造が仕様通りか**（`docs/07_shop_card_json_spec.md`）
4. 「検索できません」等の拒否が出ないか（`SEARCH_ONLY_PROMPT` の絶対遵守ルール1）
5. ショップカードが正しく表示されるか

**既知の制約（コード内コメント）**

`support_core.py:666-669`
```python
# 【重要】configパラメータの設定
# Google検索(tools)を使う場合は、response_mime_type="application/json" を
# 指定してはいけません（400エラーの原因になります）。
```
→ この制約が 3.5-flash-lite でも同じか要確認。

**5-4 が不合格だった場合の選択肢**（ユーザー判断）
- ショップ検索のみ上位モデル（`gemini-3.5-flash` / `gemini-3.6-flash` / `gemini-3.7-flash`）
- ショップ検索のみ現行維持（`gemini-2.5-flash`）
- プロンプト側の調整

**付随事項**

`chatty-base/support_core.py:34`
```python
model = genai_legacy.GenerativeModel('gemini-2.5-flash')
```
この変数は**どこからも参照されていない**（grep 確認済み）。旧SDK（`google-generativeai==0.8.6`）の初期化のみが残っている状態。
**扱いはユーザー判断**（残す / 削除）。本計画では原則として触らない。

**対象外**
- 開発ツール（`extract_menu.py` / `match_images.py` / `upload_and_match_images.py`）。Cloud Run にデプロイされない
- TTS（`ja-JP-Chirp3-HD-Leda`）。Google Cloud TTS であり Gemini とは別系統

---

### Phase 6 — Google検索の LiveAPI 移行（設計検討）

**目的**: 現在 REST 迂回になっているショップ検索を、LiveAPI 内蔵の Google検索グラウンディングに移行できるか検討する。

**現行の構造**
```
LiveAPI（音声）
  └→ search_shops FC 発火
       └→ shop_search_callback（app_customer_support.py:800付近）
            └→ REST API（Gemini + Google検索）
                 └→ SEARCH_ONLY_PROMPT で【5軒をJSON形式で】返す
                      └→ ショップカード表示
```

**技術的な可否（公式確認済み）**

Live API で Google検索は使用可能。自前の function_declarations と**併用も可能**。
```python
tools = [{"google_search": {}}, {"function_declarations": [...]}]
```
Search は 3.1 Flash Live / 2.5 Flash Live **両方で対応**。

**未解決の設計課題**

| # | 課題 |
|---|---|
| Q1 | ショップカードJSON（`docs/07_shop_card_json_spec.md`）を誰が生成するのか。LiveAPI は `response_modalities: ["AUDIO"]` で音声出力 |
| Q2 | CLAUDE.md「JSON出力はショップカード表示時のみ。通常の会話・深掘りは自然な文章」との整合 |
| Q3 | 過去に LiveAPI と JSON の組み合わせで問題が出ている（`b07dfbf` で concierge_ja.txt から JSON ルール削除 → `f3b06e5` で完全復元） |
| Q4 | 公式が「Live API はツール応答の自動処理に非対応」と明記している点の影響 |

**→ Phase 1〜5 が完了してから、独立した設計検討として着手する。本計画では着手しない。**

---

## 6. 変更対象ファイル一覧

| Phase | ファイル | 行 | 変更内容 |
|---|---|---|---|
| 1 | `chatty-base/live_api_handler.py` | 43 | `LIVE_API_MODEL` 定数 |
| 1 | 同上 | 42 | コメントの扱い（未決定） |
| 2 | — | — | **変更なし** |
| 3 | — | — | **変更なし（設計決定のみ）** |
| 4 | Phase 3 の決定次第 | | |
| 5-1 | `chatty-base/support_core.py` | 772 | モデル名 |
| 5-2 | `chatty-base/support_core.py` | 894 | モデル名 |
| 5-3 | `chatty-base/support_core.py` | 678 | モデル名 |
| 5-4 | `chatty-base/app_customer_support.py` | 872 | モデル名 |
| 6 | 未定 | | |

---

## 7. 本計画で「やらないこと」

- `CLAUDE.md` の編集（CLAUDE.md により禁止）
- `docs/` 配下の編集（同上）
- `DESIGN_SPEC_PHASE1.md` の編集（同上）
- `.github/workflows/` の編集（同上）
- `api_integrations.py` / `long_term_memory.py` の編集（同上）
- 症状を隠すガード・フォールバックの追加
- 開発ツール（`extract_menu.py` 等）のモデル変更
- TTS 設定の変更
- 複数 Phase の同時実行
- 「ついで」の修正

---

## 8. 参照資料

### プロジェクト内
- `CLAUDE.md` — プロジェクト規約
- `docs/09_liveapi_migration_design_v6.md` — V6統合仕様書
- `docs/12_shop_audio_a2e_sync_fix_spec.md` — A2E同期仕様（§3.1.3, §3.1.4）
- `docs/07_shop_card_json_spec.md` — ショップカードJSON仕様
- `docs/handover_20260524_30s_and_double_reset.md` — 前セッションからの引継ぎ

### 公式ドキュメント（本計画作成時に確認）
- Models | Gemini API — https://ai.google.dev/gemini-api/docs/models
- Gemini 3.1 Flash live preview — https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview
- Gemini 2.5 Flash Live Preview — https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-native-audio-preview-12-2025
- Gemini 3.5 Flash-Lite — https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- Gemini deprecations — https://ai.google.dev/gemini-api/docs/deprecations
- Live API best practices — https://ai.google.dev/gemini-api/docs/live-api/best-practices
- Live API capabilities guide — https://ai.google.dev/gemini-api/docs/live-api/capabilities
- Tool use with Live API — https://ai.google.dev/gemini-api/docs/live-api/tools

### 参考（一次資料ではない・未解決）
- Google AI Developers Forum: "Can't make the model start speaking with Gemini Live and the latest model"
- googleapis/python-genai issue #1533: "Gemini 2.5 Flash Live API native audio - model can't initiate the conversation"

---

## 9. 着手前の確認事項（2026-08-22 決定済み）

| # | 確認事項 | 決定 |
|---|---|---|
| C1 | 本計画書の配置場所 | **`docs/` に配置**（ユーザー承認済み） |
| C2 | `live_api_handler.py:42` の「変更禁止」コメントの扱い | **残すが、レガシー扱いの参考注釈に修正** |
| C3 | Phase 1 の実行承認 | **承認済み。着手** |

---

## 10. 進捗記録

| Phase | 状態 | 実施日 | 備考 |
|---|---|---|---|
| 計画書作成 | 完了 | 2026-08-22 | 本書 |
| Phase 1 LiveAPIモデル切替 | 実装完了・**動作確認待ち** | 2026-08-22 | `live_api_handler.py:42-43` |
| Phase 2 ベースライン実測 | 未着手 | | Phase 1 の確認後 |
| Phase 3 同期設計の決定 | 未着手 | | |
| Phase 4 初期起動の実装 | 未着手 | | |
| Phase 5 RESTモデル切替 | 未着手 | | |
| Phase 6 Google検索のLiveAPI移行 | 未着手 | | 本計画では着手しない |

