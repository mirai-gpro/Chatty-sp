# A2E リップシンク包括的実装ガイド

**作成日**: 2026-03-20
**前提ドキュメント**: docs/11（実装ルール）, docs/12（修正案C仕様）を統合
**対象コード**: `live_api_handler.py`, `live-audio-manager.ts`, `core-controller.ts`, `lam-websocket-manager.ts`

---

## 1. A2Eの基本特性（公式リポジトリ準拠）

### 1.1 入出力の決定論的対応

| 入力 | 出力 | 根拠 |
|------|------|------|
| 16,000サンプル（1秒 @ 16kHz） | 30フレーム（1秒 @ 30fps） | `frame_length = math.ceil(audio.shape[0] / ssr * 30)` |
| N秒の音声 | N × 30 フレーム | 線形対応。例外なし |

参照: https://github.com/aigc3d/LAM_Audio2Expression `engines/infer.py`

### 1.2 推論レイテンシ = 事実上ゼロ

公式デモで確認済み。「A2Eの処理時間が遅延の原因」と推測してはならない。
同期がズレている場合、原因は**常にアプリケーション側のコードロジック**。

### 1.3 ストリーミングcontext

```python
context = {
    'previous_audio': ...,       # 前チャンクの音声波形（オーバーラップ用）
    'previous_expression': ...,  # 前チャンクの出力blendshape
    'previous_volume': ...,      # 前チャンクの音量（無音判定用）
    'is_initial_input': False    # 初回フラグ
}
```

- `is_start=True` → context リセット（新しい音声セグメント開始）
- `is_start=False` → 前チャンクとの連続性保持（スライディングウィンドウ）
- **意味的に独立した音声**（別のショップ説明、キャッシュ音声）は `is_start=True` で切る

### 1.4 後処理パイプライン（A2Eサービス内部で完結）

1. `smooth_mouth_movements()` — 無音区間の口パクパク抑制
2. `apply_frame_blending()` — チャンク境界の線形補間
3. `apply_savitzky_golay_smoothing()` — 時間軸の多項式平滑化
4. `symmetrize_blendshapes()` — 左右20ペアの対称化
5. `apply_random_eye_blinks_context()` — 手続き的まばたき生成
6. `apply_random_brow_movement()` — 音声RMSに基づく眉の動き

**アプリケーション側で再実装してはならない。**

---

## 2. 同期メカニズムの全体像

### 2.1 データフロー（4コンポーネント）

```
┌──────────────────────────────────────────────────────────────┐
│ バックエンド: live_api_handler.py                              │
│                                                              │
│  LiveAPI → PCM音声チャンク到着                                  │
│    ├── socketio.emit('live_audio')     → [フロントへ]          │
│    └── _buffer_for_a2e(pcm)                                   │
│          └── _flush_a2e_buffer()                              │
│                └── _send_to_a2e(pcm, chunk_index, is_final)   │
│                      └── 24kHz→16kHz リサンプリング             │
│                      └── HTTP POST → A2Eサービス               │
│                      └── socketio.emit('live_expression')     │
│                            → [フロントへ]                      │
└──────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│ フロントエンド: core-controller.ts                             │
│                                                              │
│  socket.on('live_audio')                                      │
│    → liveAudioManager.onAiResponseStarted()                   │
│    → liveAudioManager.playPcmAudio(data)                      │
│                                                              │
│  socket.on('live_expression')                                 │
│    → liveAudioManager.onExpressionReceived(data)              │
│                                                              │
│  socket.on('live_expression_reset')                           │
│    → liveAudioManager.resetForNewSegment()                    │
└──────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌─────────────────────────┐  ┌─────────────────────────────────┐
│ live-audio-manager.ts   │  │ lam-websocket-manager.ts        │
│                         │  │                                 │
│ playPcmAudio():         │  │ レンダリングループ（毎フレーム）:    │
│   AudioContext再生       │  │   frame = liveAudioManager      │
│   firstChunkStartTime   │  │     .getCurrentExpressionFrame() │
│   _scheduleBuffer()     │  │   updateExpression(frame)        │
│                         │  │   → blendshapeに反映              │
│ getCurrentExpression     │  │                                 │
│   Frame():              │  │ _getExpressionData():            │
│   offsetMs計算           │  │   currentExpression.values       │
│   frameIndex算出         │  │   → ARKit 52 blendshape map     │
│   バッファから取得        │  │                                 │
└─────────────────────────┘  └─────────────────────────────────┘
```

### 2.2 同期の3条件（全て必須）

| 条件 | 説明 |
|------|------|
| **条件1: 時間ベースの一致** | `firstChunkStartTime` が音声再生開始時刻と一致 |
| **条件2: フレーム数の一致** | `expressionFrameBuffer` のフレーム数 = 再生音声の秒数 × 30 |
| **条件3: ギャップの不在** | `firstChunkStartTime` から現在まで、音声もフレームもない空白期間がないこと |

**条件3が最重要。** `audioContext.currentTime` は音声が鳴っていなくても進む。

---

## 3. 音声パス別の同期方式

### 3.1 正常パス: 通常会話（`_receive_and_forward`）

**方式**: インターリーブ（音声とExpressionが交互に到着）

```
live_audio → playPcmAudio() → firstChunkStartTime設定
↕ 同時進行
_buffer_for_a2e → A2Eサービス → live_expression → バッファ追加
↕ 繰り返し
turn_complete → リセット
```

**なぜ動くか**: LiveAPIが音声を連続ストリーミング → 空白期間なし → 3条件充足

**コード位置**: `live_api_handler.py` L630-713 `_receive_and_forward()`

### 3.2 ショップ1軒目: ストリーミング（`_stream_single_shop` + `_receive_shop_description`）

**方式**: インターリーブ（正常パスと同等）

```
live_expression_reset → resetForNewSegment()
  ↓
新LiveAPIセッション → ストリーミング受信
  live_audio + _buffer_for_a2e（正常パスと同じインターリーブ）
  ↓
turn_complete → フラッシュ
```

**コード位置**: `live_api_handler.py` L917-960 `_stream_single_shop()`、L1052-1110 `_receive_shop_description()`

### 3.3 ショップ2軒目以降: A2E先行方式（`_emit_collected_shop`）

**方式**: A2E先行（Expression全フレームが先着 → 音声再生開始）

```
live_expression_reset → resetForNewSegment()
  ↓
_send_a2e_ahead(全PCM結合) → live_expression（全フレーム先着）
  ↓
sleep(50ms) → 到着マージン
  ↓
live_audio × N chunks → 再生開始
```

**コード位置**: `live_api_handler.py` L1029-1051 `_emit_collected_shop()`

### 3.4 キャッシュ音声: A2E先行方式（`_emit_cached_audio`）

**方式**: A2E先行（3.3と同じ）

```
live_expression_reset → resetForNewSegment()
  ↓
_send_a2e_ahead(PCM) → live_expression（全フレーム先着）
  ↓
sleep(50ms) → 到着マージン
  ↓
live_audio × N chunks → 再生開始
```

**コード位置**: `live_api_handler.py` L1116-1146 `_emit_cached_audio()`

**現在の状態**: L729-737でコメントアウト（切り分けテスト用に無効化中）

---

## 4. セグメント境界リセットの仕組み

### 4.1 `live_expression_reset` イベントフロー

```
バックエンド                           フロントエンド
────────                           ──────────
socketio.emit                      core-controller.ts L305:
  ('live_expression_reset')   →      socket.on('live_expression_reset')
                                       → liveAudioManager.resetForNewSegment()

                                   live-audio-manager.ts L340-358:
                                     resetForNewSegment():
                                       nextPlayTime = 0
                                       scheduledSources → 全stop
                                       expressionFrameBuffer = []
                                       firstChunkStartTime = 0
                                       isAiSpeaking = true  ← 維持！
```

### 4.2 なぜ `isAiSpeaking = true` を維持するか

```
× もし isAiSpeaking = false にした場合:
  live_expression_reset → isAiSpeaking = false
  _send_a2e_ahead → live_expression → バッファにフレーム追加
  live_audio → onAiResponseStarted()
    isAiSpeaking was false → リセット実行！
    expressionFrameBuffer = []  ← A2E先行で追加したフレームが消える！

✓ isAiSpeaking = true を維持した場合:
  live_expression_reset → isAiSpeaking = true（維持）
  _send_a2e_ahead → live_expression → バッファにフレーム追加
  live_audio → onAiResponseStarted()
    isAiSpeaking was true → リセット不実行！
    expressionFrameBuffer 保持！ ← A2E先行のフレームが保持される
  playPcmAudio()
    firstChunkStartTime = audioContext.currentTime ← 設定
    → 同期成立
```

### 4.3 リセットが必要なタイミング一覧

| タイミング | 信号 | コード位置 |
|-----------|------|-----------|
| 通常会話のターン完了 | `turn_complete` | L650-663 |
| ユーザー割り込み | `interrupted` | L666-673 |
| キャッシュ音声の前 | `live_expression_reset` | `_emit_cached_audio()` L1130 |
| 1軒目ストリーミングの前 | `live_expression_reset` | `_describe_shops_via_live()` L882 |
| 2軒目以降 collected の前 | `live_expression_reset` | `_emit_collected_shop()` L1038 |

---

## 5. ショップ検索フロー全体のタイムライン

```
LLM発話 → tool_call: search_shops
  ↓
shop_search_start送信 (L725)
  ↓
[キャッシュ音声は現在無効化 L729-737]
  ↓
REST API検索 → shop_search_result送信 (L797)
  ↓
_describe_shops_via_live() (L860):
  ├── 2軒目以降の並行生成をasyncio.create_task (L876-879)
  ├── live_expression_reset (L882) ← 1軒目前のリセット
  ├── _a2e_chunk_index = 0, _a2e_audio_buffer クリア (L883-884)
  ├── _stream_single_shop() (L887) ← 1軒目ストリーミング
  │     └── _receive_shop_description() ← インターリーブ方式
  ├── sleep(1軒目の音声再生時間) (L890-893)
  └── 2軒目以降を順次再生 (L896-909):
        ├── _emit_collected_shop() ← A2E先行方式
        └── sleep(音声再生時間) ← 各ショップ間
  ↓
会話履歴に追加 (L912-913)
needs_reconnect = True → 通常会話に復帰 (L915)
```

---

## 6. バッファリング定数

| 定数 | 値 | 意味 | コード位置 |
|------|-----|------|-----------|
| `A2E_MIN_BUFFER_BYTES` | 4,800 | 最低バッファサイズ（0.1秒 @ 24kHz 16bit mono） | L31 |
| `A2E_FIRST_FLUSH_BYTES` | 4,800 | 初回フラッシュ閾値（低遅延優先） | L32 |
| `A2E_AUTO_FLUSH_BYTES` | 240,000 | 2回目以降フラッシュ閾値（5秒分、品質優先） | L33 |
| `A2E_EXPRESSION_FPS` | 30 | Expression フレームレート | L34 |
| A2E先行後のsleep | 50ms | Socket.IO emit→フロント処理の往復マージン | `_emit_cached_audio` L1136 |

**これらの値は実証テスト済み。変更するな。**

---

## 7. リサンプリング（24kHz → 16kHz）

`_send_to_a2e()` L1215-1268:

```python
# LiveAPIの出力: 24kHz 16bit mono PCM
# A2Eの入力: 16kHz 16bit mono PCM
int16_array = np.frombuffer(pcm_data, dtype=np.int16)
resampled = resample_poly(int16_array.astype(np.float32), up=2, down=3)  # 24→16kHz
int16_resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
audio_b64 = base64.b64encode(int16_resampled.tobytes()).decode('utf-8')
```

A2EサービスのAPIパラメータ:
- `audio_base64`: raw int16 PCM のbase64
- `audio_format`: `"pcm"`
- `session_id`: セッション識別子
- `is_start`: 新セグメント開始
- `is_final`: セグメント最終チャンク

---

## 8. フロントエンドのExpression適用パス

### 8.1 `getCurrentExpressionFrame()` (live-audio-manager.ts L237-270)

```typescript
offsetMs = (audioContext.currentTime - firstChunkStartTime) * 1000
frameIndex = Math.floor((offsetMs / 1000) * expressionFrameRate)  // = offsetMs * 30 / 1000
clampedIndex = Math.min(frameIndex, expressionFrameBuffer.length - 1)
return expressionFrameBuffer[clampedIndex]
```

### 8.2 LAMレンダラーへの適用 (lam-websocket-manager.ts)

```
GaussianSplatRenderer コールバック:
  getExpressionData()
    → currentExpression.values を ARKit 52 blendshape map に変換
    → レンダラーが毎フレーム呼び出し
```

レンダリングループ（concierge-controller.ts から linkLamAvatar() 経由）:
```
毎フレーム:
  frame = liveAudioManager.getCurrentExpressionFrame()
  lamWebSocketManager.updateExpression(frame)
```

---

## 9. 現在の残課題

### 9.1 キャッシュ音声の再有効化

L729-737でコメントアウト中。A2Eバッファ汚染の切り分けテスト用に無効化されている。
A2E先行方式（`_emit_cached_audio`）が正常動作すれば、コメントアウトを解除して再有効化できる。

### 9.2 ショップ間のsleep値の最適化

`_describe_shops_via_live()` L890-907:
- 1軒目再生待ち: `_last_stream_pcm_bytes / 48000` 秒
- 2軒目以降再生待ち: `len(all_pcm) / 48000` 秒

これらのsleep値は「前セグメントの音声が再生し終わるまで待つ」ための概算値。
音声再生とA2Eフレーム消費が完全に同期していれば、次セグメントの `live_expression_reset` で安全にリセットできるため、厳密なsleep値は不要。

---

## 10. 語尾もごもご・口開きっぱなし対策（A-1 + A-2）

**作成日**: 2026-03-24
**根拠**: Gemini / ChatGPT 両LLMの分析結果に基づく。Claude独自の推論は含まない。

### 10.1 問題の現象

- 発話の語尾で「もごもご」する（blendshape値が不安定に小さくなる）
- 発話終了後に口が開いたまま固定される（最終フレームの貼り付き）
- 4〜5回に1回程度の頻度で発生

### 10.2 原因分析（Gemini + ChatGPT共通見解）

| 原因 | 説明 | 出典 |
|------|------|------|
| 最終チャンクが短すぎる | `turn_complete` 時の残存バッファが数十ms程度だと、Wav2Vecエンコーダのコンテキスト（受容野）が不足し、特徴量を正しく抽出できない | Gemini + ChatGPT |
| 終端の文脈不在 | 最後の有声区間の直後に何もないと、モデルが「発話が終わった」ことを認識できず、blendshape値がニュートラルに収束しない | Gemini + ChatGPT |
| A2E後処理による末尾減衰 | `smooth_mouth_movements`, `apply_savitzky_golay_smoothing` 等の後処理が、末尾の短い有声区間や小さいRMSをさらに弱める | ChatGPT |

### 10.3 改善案 A-1: 最終チャンクの最小長制限

**方針**: `turn_complete` 時の残存バッファが短すぎる場合（100〜200ms未満）、単独でflushせず直前チャンクに吸収する。

**根拠**:
- ChatGPT: 「数百bytesしかない最終chunkだと、実質1フレーム未満の情報しかないので、まともな口形を期待しにくい」「最低150ms、できれば250〜500msは欲しい」
- Gemini: 「数ミリ秒〜数十ミリ秒の極端に短い最終チャンクは、モデルにとって意味のないノイズに見えてしまう」

**対象コード**: `live_api_handler.py` `_flush_a2e_buffer()` の `is_final=True` 時の処理

**実装方針**:
- `turn_complete` 時に `_a2e_audio_buffer` の残量が最小閾値（例: 100〜200ms相当のバイト数）未満であれば、単独flush**しない**
- 代わりに、直前チャンクに吸収するか、A-2の無音paddingと組み合わせて送信する

### 10.4 改善案 A-2: 最終チャンクへの無音パディング

**方針**: 最終チャンク（`is_final=True`）の末尾に、デジタルゼロ（無音）のPCMデータを150〜250ms分連結してからA2Eに送信する。

**根拠**:
- Gemini: 「末尾に200〜300ms分のデジタルゼロ（無音）のPCMデータを強制的に連結して推論にかける。モデルが『発話が終わった後の無音状態』を認識できるため、blendshape値が自然に0（ニュートラル）へ収束しやすくなる」
- ChatGPT: 「残存PCM + 150〜250ms silenceを結合してからA2Eに送信。口閉じ方向への遷移が安定する」「見た目は閉じやすくなるのに、音声自体は引き延ばさないので使いやすい」

**対象コード**: `live_api_handler.py` `_send_to_a2e()` の `is_final=True` 時の処理

**実装方針**:
- `is_final=True` の場合、PCMデータの末尾に無音（ゼロ値）を200ms分追加
- 200ms @ 24kHz 16bit mono = 9,600 bytes（リサンプリング前の値）
- A2Eから返却されたexpressionフレームはそのまま使用（無音部分のフレームは口閉じ方向に収束するため有用）

### 10.5 A-1 + A-2 の組み合わせ

```
turn_complete 発生
  ↓
残存バッファの長さを確認
  ├── 最小閾値以上 → そのまま is_final=True で flush（A-2: 無音padding付与）
  └── 最小閾値未満 → 直前チャンクの残り + 残存バッファを結合 → is_final=True で flush（A-2: 無音padding付与）
  ↓
A2Eサービスへ送信
  ↓
返却フレーム: 末尾が自然にニュートラル方向へ収束
```

### 10.6 未採用案（今回は見送り、効果不十分時の次善策）

| 案 | 内容 | 出典 | 見送り理由 |
|-----|------|------|-----------|
| A-3: Look-back Padding | 最終チャンクに直前チャンク末尾200msを結合→返却expressionから付与分を捨てる | Geminiのみ | A-2と目的が重複。A-2で不十分な場合に検討 |
| A-4: 句読点flush条件の厳格化 | 句読点検出flushに最低チャンク長・音量条件を追加 | ChatGPTのみ | 現コードに句読点flushロジックがあるか未確認 |

### 10.7 フロント側対策（別途検討）

サーバー側（A-1 + A-2）で改善が不十分な場合の追加対策候補。今回は未実施。

| 案 | 内容 | 出典 |
|-----|------|------|
| B-1: clamp廃止 → endTime管理 | `Math.min(frameIndex, length-1)` が最終フレーム永久保持の直接原因。endTime超過後はholdしない | Gemini + ChatGPT |
| B-2: decay-to-neutral | endTime超過後、80〜150msかけてlerp→0で自然に口を閉じる | Gemini + ChatGPT |
| B-3: ニュートラルフレーム自動追加 | 受信expressionの末尾に全0フレームを3〜5個push | Geminiのみ |

---

## 11. A2Eサービス側 context 持ち回し改修（案A: セッション辞書方式）

**作成日**: 2026-03-24
**根拠**: Gemini / ChatGPT 両LLMの分析 + 実コード確認に基づく。Claude独自の推論は含まない。

### 11.1 問題の事実

`a2e_engine.py` の `_process_with_infer()` は、毎回の HTTP POST で `context = None` から推論を開始している。

```python
# 現行コード（a2e_engine.py L403-428）
def _process_with_infer(self, audio_pcm, duration):
    context = None  # ← 毎回リセット。前チャンクのcontextは破棄される

    for start in range(0, len(audio_pcm), chunk_samples):
        result, context = self._infer.infer_streaming_audio(
            audio=chunk, ssr=INFER_INPUT_SAMPLE_RATE, context=context
        )
```

また `app.py` は `session_id` / `is_start` / `is_final` をリクエストから読み取ってはいるが、`engine.process()` に渡していない。

```python
# 現行コード（app.py L96-108）
session_id = data.get('session_id', 'unknown')   # ← ログ用のみ
result = engine.process(audio_base64, audio_format=audio_format)  # ← session_id未使用
```

### 11.2 影響範囲

| モード | POST回数 | context | 症状 |
|--------|----------|---------|------|
| A2E Ahead（お店説明2軒目以降） | 1回（全PCM一括） | POST内で1秒チャンク間を引き継ぎ → **正常** | なし |
| ストリーミング（通常会話） | 複数回（0.1秒→5秒→句読点flush→残り） | **各POSTが `context=None` から開始** | 語尾もごもご・境界不安定 |

### 11.3 修正方針: セッション辞書方式

`session_id` をキーにcontextを辞書で管理し、POST間でcontextを持ち回す。

- `is_start=True` → contextリセット（新ターン開始）
- `is_start=False` → 前回contextを引き継ぎ
- `is_final=True` → 推論後にcontextを破棄

### 11.4 修正対象ファイルと変更内容

#### (1) `a2e_engine.py` — エンジン側

**`process()` メソッドのシグネチャ変更**:
```python
def process(self, audio_base64, audio_format="mp3",
            session_id="unknown", is_start=False, is_final=False):
    audio_pcm = self._decode_audio(audio_base64, audio_format)
    duration = len(audio_pcm) / INFER_INPUT_SAMPLE_RATE

    if self._use_infer:
        return self._process_with_infer(
            audio_pcm, duration, session_id, is_start, is_final)
    else:
        return self._process_with_fallback(audio_pcm, duration)
```

**`__init__` に辞書追加**:
```python
self._session_contexts = {}  # {session_id: context}
```

**`_process_with_infer()` のcontext管理**:
```python
def _process_with_infer(self, audio_pcm, duration,
                        session_id, is_start, is_final):
    chunk_samples = INFER_INPUT_SAMPLE_RATE
    all_expressions = []

    # context取得: is_start=True or 未知セッション → None
    if is_start or session_id not in self._session_contexts:
        context = None
    else:
        context = self._session_contexts[session_id]

    for start in range(0, len(audio_pcm), chunk_samples):
        end = min(start + chunk_samples, len(audio_pcm))
        chunk = audio_pcm[start:end]
        if len(chunk) < INFER_INPUT_SAMPLE_RATE // 10:
            continue
        result, context = self._infer.infer_streaming_audio(
            audio=chunk, ssr=INFER_INPUT_SAMPLE_RATE, context=context)
        expr = result.get("expression")
        if expr is not None:
            all_expressions.append(expr.astype(np.float32))

    # context保存 or 破棄
    if is_final:
        self._session_contexts.pop(session_id, None)
    else:
        self._session_contexts[session_id] = context

    # ... 以降は既存と同じ（expression結合・フレーム変換）
```

#### (2) `app.py` — APIエンドポイント側

**`session_id` / `is_start` / `is_final` を `engine.process()` に渡す**:
```python
result = engine.process(
    audio_base64,
    audio_format=audio_format,
    session_id=session_id,
    is_start=data.get('is_start', False),
    is_final=data.get('is_final', False),
)
```

### 11.5 `live_api_handler.py` 側の変更: なし

バックエンド（`live_api_handler.py`）は既に `session_id`, `is_start`, `is_final` をHTTP POSTのJSONに含めて送信している（L1364-1374）。A2Eサービス側がこれらを受け取って使うようになれば、バックエンド側の変更は不要。

### 11.6 期待される効果

```
修正前:
  POST#0 (0.1秒, is_start=True)  → context=None → 推論 → context破棄
  POST#1 (5秒, is_start=False)   → context=None → 推論 → context破棄  ← 境界不連続
  POST#2 (残り, is_final=True)   → context=None → 推論 → context破棄  ← 境界不連続

修正後:
  POST#0 (0.1秒, is_start=True)  → context=None → 推論 → context保存
  POST#1 (5秒, is_start=False)   → context復元  → 推論 → context保存  ← 連続
  POST#2 (残り, is_final=True)   → context復元  → 推論 → context破棄  ← 連続
```

### 11.7 セクション10（A-1 + A-2）との関係

- セクション10の A-1（最終チャンク最小長制限）と A-2（無音パディング）は**本改修と独立**
- A-1 + A-2 は最終チャンク単体の品質改善、本改修はチャンク間の連続性確保
- **両方を併用**することで、ストリーミング全体の品質が向上する

---

## 12. 実装の必須ルール（チェックリスト）

新たに `live_audio` を送信するコードパスを作る場合:

- [ ] セグメント開始前に `live_expression_reset` を送っているか
- [ ] 音声チャンクごとに `_buffer_for_a2e()` を呼んでいるか（インターリーブ方式の場合）
- [ ] または `_send_a2e_ahead()` でExpression先行送信しているか（A2E先行方式の場合）
- [ ] セグメント終了時に `_flush_a2e_buffer(force=True, is_final=True)` を呼んでいるか
- [ ] セグメント終了時に `_a2e_chunk_index = 0` にリセットしているか
- [ ] 無音ギャップが発生する場合、前後でリセットしているか

---

## 13. 禁止事項

1. **A2Eの推論遅延を仮定するな** — ゼロレイテンシ。ズレの原因はアプリ側
2. **A2Eの後処理を再実装するな** — サービス内部で完結
3. **フロントの同期メカニズムを迂回するな** — `firstChunkStartTime` + `expressionFrameBuffer` は実証済み
4. **正常パスのコードを表面だけコピーするな** — `turn_complete` リセットが欠落すれば同期崩壊
5. **バッファ閾値を変更するな** — 実証テスト済みの値

---

## 14. A2E表情チャンク順序ずれ改善（通常会話フロー）

**作成日**: 2026-03-24
**根拠**: Gemini / ChatGPT 両LLMの分析結果を精査・統合。Claude独自の推論は含まない。

### 14.1 問題の現象

通常会話フロー（`_receive_and_forward`）において、A2Eの表情フレームが音声の時間軸とずれる。

### 14.2 原因

`_buffer_for_a2e()` (L1237) で `asyncio.ensure_future(_flush_a2e_buffer)` により A2E HTTP POST が**並列実行**される。レスポンス到着順は保証されないが、フロントエンドの `onExpressionReceived()` は到着順に `push` しているため、**音声の時間軸と表情フレームの対応が壊れる**。

```
chunk_index=1 (句読点flush, 2秒分) → HTTP POST → レスポンス遅延
chunk_index=2 (句読点flush, 1秒分) → HTTP POST → レスポンス先着 ★
chunk_index=3 (句読点flush, 3秒分) → HTTP POST → レスポンス先着 ★

フロントのバッファ: [chunk2のframes][chunk3のframes][chunk1のframes]
音声の時間軸:        [chunk1の音声  ][chunk2の音声  ][chunk3の音声  ]
→ 完全にずれている
```

### 14.3 ショップ説明フローとの違い

| | 通常会話 | ショップ説明（A2E先行方式） |
|---|---------|--------------------------|
| 音声到着 | リアルタイム逐次 | 事前に全collect済み |
| A2E送信 | 複数回・並列HTTP POST | **1回・一括** (`_precompute_a2e_expressions`) |
| 順序保証 | **なし（本セクションの問題）** | あり（1回なので自明） |
| Expression到着 | 音声の後（後追い） | **音声の前（先行）** |
| 本改善の必要性 | **必要** | 不要 |

### 14.4 A2Eフラッシュのトリガー（通常会話）

| # | トリガー | 閾値 | 秒数換算 | コード位置 |
|---|---------|------|---------|-----------|
| 1 | 初回バイト数超過 | `A2E_FIRST_FLUSH_BYTES` = 4,800 | **0.1秒** | `_buffer_for_a2e()` L1235-1237 |
| 2 | 2回目以降バイト数超過 | `A2E_AUTO_FLUSH_BYTES` = 240,000 | **5秒** | `_buffer_for_a2e()` L1235-1237 |
| 3 | 句読点検出（。？！?!） | 可変（文の長さ次第） | 大体2〜4秒 | `_on_output_transcription()` L1239-1246 |
| 4 | ターン完了 | 残存バッファ全量 | 可変 | `_receive_and_forward()` L597-599 |

2回目以降は**句読点トリガーが5秒閾値より先に発火**するケースが大半。短い文が連続すると（例: 「はい。お探しします。少々お待ちください。」）、複数のHTTP POSTがほぼ同時に飛び、順序ずれが起きやすい。

### 14.5 改善方針

Gemini・ChatGPT両者が一致した「**フロントエンドで `start_frame` ベースの絶対位置管理**」を本命とする。加えてバックエンド側で `start_frame` メタデータを付与する。

**v2 更新（2026-03-24）**: 初回実装後のデプロイテストで以下の2つの問題が判明し、Gemini・ChatGPTに再分析を依頼。両者の回答を統合して§14.6〜14.8を改訂。

#### v2 で判明した問題

**問題1: `estimated_frames` と A2E実レスポンスのフレーム数不一致**

```
Backend:  chunk 0: 30 frames送信 (start_frame=0)
Backend:  chunk 1: 89 frames送信 (start_frame=32)  ← estimated_frames=32だがA2E実返却=30
→ Mapにフレーム30, 31が存在しない穴が生まれる
```

原因: `estimated_frames = int((len(pcm_data) / 2) / 24000 * FPS)` はリサンプリング前のPCM長基準。A2Eサービスはリサンプリング後（16kHz）+ パディング後の音声に対してフレームを生成するため、推定値と実値がずれる。

**問題2: 再生ヘッドがexpression供給を常に先行し、全フレーム hit=false**

```
firstChunkStartTime=3.040
[A2E Sync] offsetMs=1211, frameIdx=36/29, hit=false  ← chunk 0は30フレーム(1秒分)のみ
[A2E Sync] offsetMs=5200, frameIdx=156/120, hit=false ← chunk 1到着後も超過
...以降16秒間ずっと hit=false, jawOpen=0.018 で固定
```

原因1: A2E HTTP POSTに約3秒かかるため、音声再生開始時点でexpressionが未到着。
原因2: 旧コード（Array）の `Math.min(frameIndex, length-1)` によるclampingが、Map化で失われた。frameIndex > maxIndex でも `lastValidFrame` が更新されず、初期値で固定。

#### Gemini・ChatGPT の回答の要点

**問題1について（両者一致）**:
- `estimated_frames` を積算して次の `start_frame` を決める方式はNG
- `start_frame` は**入力音声の時間軸（サンプル数）**から算出すべき
- A2Eが何フレーム返すかに依存させない
- await前に確定できるため並列安全

**問題2について（両者一致 + ChatGPT追加提案）**:
- `frameIndex > maxIndex` 時にmaxIndexのフレームを返すclamping追加（両者一致）
- expression参照を音声より200〜400ms遅らせる `expressionDelayMs` の導入（ChatGPT提案、採用）

### 14.6 修正1: バックエンド — `start_frame` メタデータ付与（v2改訂）

**対象ファイル**: `live_api_handler.py`

#### (1) 新規インスタンス変数

`__init__` の A2Eバッファリング機構セクション（L332付近）に追加:

```python
self._a2e_total_samples_24k = 0  # Expression同期用: 累積PCMサンプル数（24kHz基準）
```

> **v2変更点**: 旧 `_a2e_total_frames_sent`（推定フレーム数の積算）を廃止。入力音声のサンプル数を正確に積算する `_a2e_total_samples_24k` に置換。

#### (2) `_flush_a2e_buffer()` の変更

`start_frame` を入力音声のサンプル数から算出する。A2Eの実レスポンスフレーム数には依存しない。

```python
async def _flush_a2e_buffer(self, force: bool = False, is_final: bool = False):
    if len(self._a2e_audio_buffer) == 0:
        return
    if not force and len(self._a2e_audio_buffer) < A2E_MIN_BUFFER_BYTES:
        return

    # A-1: 最終チャンク最小長制限（既存）
    if is_final and len(self._a2e_audio_buffer) < A2E_FINAL_MIN_BYTES:
        pad_needed = A2E_FINAL_MIN_BYTES - len(self._a2e_audio_buffer)
        self._a2e_audio_buffer.extend(b'\x00' * pad_needed)

    pcm_data = bytes(self._a2e_audio_buffer)
    self._a2e_audio_buffer = bytearray()
    chunk_index = self._a2e_chunk_index
    self._a2e_chunk_index += 1

    # ★ start_frame を入力音声サンプル数から算出（v2: estimated_frames廃止）
    # サンプル数は正確に積算されるため、整数丸めの累積誤差が発生しない
    start_frame = int(self._a2e_total_samples_24k / 24000 * A2E_EXPRESSION_FPS)
    self._a2e_total_samples_24k += len(pcm_data) // 2  # 16bit PCM → サンプル数

    try:
        await self._send_to_a2e(pcm_data, chunk_index,
                                start_frame=start_frame, is_final=is_final)
    except Exception as e:
        logger.error(f"[A2E] フラッシュエラー: {e}")
```

**v2のポイント**:
- `start_frame` は「この音声チャンクが会話全体の何秒目から始まるか」を表す**入力音声の時間軸上の位置**
- A2Eがリサンプリング・パディング等で何フレーム返してきても、次のチャンクの `start_frame` は入力音声のサンプル数から一意に決まる
- `await` 前に `_a2e_total_samples_24k` を更新するため、並列コルーチン間でも直列に処理される（v1と同じ並列安全性を維持）

> **注意**: `asyncio.ensure_future()` によりコルーチンはイベントループに登録されるが、`_flush_a2e_buffer` の `start_frame` 算出〜`_a2e_total_samples_24k` 更新は `await` 前に実行されるため、同一イベントループティック内で直列に処理される。

> **v1との違い**: v1は `estimated_frames = int((len(pcm_data) / 2) / 24000 * FPS)` で推定フレーム数を積算していたが、A2E実レスポンスとの差異（例: 推定32フレーム vs 実30フレーム）によりMapに穴が生まれた。v2はサンプル数を正確に積算し、`start_frame` への変換は最終段の1回のみ行うことで、この問題を解消する。

#### (3) `_send_to_a2e()` シグネチャ変更

```python
async def _send_to_a2e(self, pcm_data: bytes, chunk_index: int,
                        start_frame: int = 0, is_final: bool = False):
```

emitペイロードに `start_frame` を追加:

```python
self.socketio.emit('live_expression', {
    'expressions': expressions,
    'expression_names': names,
    'frame_rate': frame_rate,
    'chunk_index': chunk_index,
    'start_frame': start_frame,   # ← 追加
}, room=self.client_sid)
```

#### (4) リセット箇所

`_a2e_total_samples_24k = 0` を以下のリセット箇所に追加:

| タイミング | コード位置 |
|-----------|-----------|
| `turn_complete` | `self._a2e_chunk_index = 0` の直後 |
| `interrupted` | `self._a2e_chunk_index = 0` の直後 |
| `_describe_shops_via_live` リセット | `self._a2e_chunk_index = 0` の直後 |
| `_send_a2e_ahead` | `self._a2e_chunk_index = 0` の直後 |

#### (5) A2E先行方式（`_emit_collected_shop`, `_emit_cached_audio`）

`_emit_collected_shop` の事前計算済みemit に `'start_frame': 0` を追加。
`_send_a2e_ahead` 経由のemitは `_send_to_a2e` を通るため自動的に `start_frame` が付与される。

### 14.7 修正2: フロントエンド — 絶対フレーム位置による格納・参照（v2改訂）

**対象ファイル**: `live-audio-manager.ts`

#### (1) データ構造の変更

```typescript
// 変更前
private expressionFrameBuffer: ExpressionFrame[] = [];

// 変更後
private expressionFrameMap: Map<number, ExpressionFrame> = new Map();
private expressionFrameMaxIndex: number = -1;     // Map内の最大フレームインデックス
private lastValidFrame: ExpressionFrame | null = null;  // 未到着・範囲外フレーム用
private expressionDelayMs: number = 300;           // ★ v2追加: expression参照遅延（ms）
```

#### (2) `onExpressionReceived()` の変更

```typescript
onExpressionReceived(data: {
    expressions: number[][];
    expression_names: string[];
    frame_rate: number;
    chunk_index: number;
    start_frame?: number;  // ← 追加（後方互換のためoptional）
}): void {
    if (data.frame_rate) this.expressionFrameRate = data.frame_rate;
    if (data.expression_names && data.expression_names.length > 0) {
        this.expressionNames = data.expression_names;
    }

    // ★ start_frame ベースの絶対位置格納
    const startFrame = data.start_frame ?? this.expressionFrameMaxIndex + 1;
    for (let i = 0; i < data.expressions.length; i++) {
        const frameIndex = startFrame + i;
        this.expressionFrameMap.set(frameIndex, { values: data.expressions[i] });
        if (frameIndex > this.expressionFrameMaxIndex) {
            this.expressionFrameMaxIndex = frameIndex;
        }
    }

    // デバッグログ
    if (data.expressions.length > 0) {
        const jawOpenIdx = this.expressionNames.indexOf('jawOpen');
        const firstFrame = data.expressions[0];
        const lastFrame = data.expressions[data.expressions.length - 1];
        console.log(
            `[A2E Buffer] chunk=${data.chunk_index}, start_frame=${startFrame}, ` +
            `+${data.expressions.length}frames, total=${this.expressionFrameMap.size}, ` +
            `jawOpenIdx=${jawOpenIdx}, jawOpen=[${jawOpenIdx >= 0 ? firstFrame[jawOpenIdx]?.toFixed(3) : 'N/A'}..${jawOpenIdx >= 0 ? lastFrame[jawOpenIdx]?.toFixed(3) : 'N/A'}], ` +
            `firstChunkStartTime=${this.firstChunkStartTime.toFixed(3)}`
        );
    }
}
```

#### (3) `getCurrentExpressionFrame()` の変更（v2: clamping + expressionDelayMs 追加）

```typescript
getCurrentExpressionFrame(): ExpressionFrame | null {
    if (this.expressionFrameMap.size === 0) return null;

    // ★ v2: expression参照を音声再生より expressionDelayMs 遅らせる
    // A2E HTTP推論の遅延を吸収し、再生ヘッドの先走りを抑制する
    const offsetMs = this.getCurrentPlaybackOffset() - this.expressionDelayMs;
    if (offsetMs < 0) return this.lastValidFrame;

    const frameIndex = Math.floor((offsetMs / 1000) * this.expressionFrameRate);

    // ★ 三段構えのフレーム取得（v2: Gemini・ChatGPT共通提案）
    let frame: ExpressionFrame | undefined;

    // 1. Mapに直接存在する場合（理想的なケース）
    frame = this.expressionFrameMap.get(frameIndex);
    if (frame) {
        this.lastValidFrame = frame;
    }
    // 2. 再生位置がMap最大インデックスを超えている場合（clamping）
    else if (frameIndex > this.expressionFrameMaxIndex && this.expressionFrameMaxIndex >= 0) {
        frame = this.expressionFrameMap.get(this.expressionFrameMaxIndex);
        if (frame) {
            this.lastValidFrame = frame;
        }
    }
    // 3. Map範囲内だが穴がある場合 → lastValidFrame を返す

    // デバッグ: 60フレームごと（約1秒）にログ出力
    this._a2eDebugCounter++;
    if (this._a2eDebugCounter % 60 === 0) {
        const currentFrame = frame ?? this.lastValidFrame;
        const jawOpenIdx = this.expressionNames.indexOf('jawOpen');
        const jawVal = currentFrame && jawOpenIdx >= 0 && currentFrame.values[jawOpenIdx] !== undefined
            ? currentFrame.values[jawOpenIdx].toFixed(3) : 'N/A';
        console.log(
            `[A2E Sync] offsetMs=${(offsetMs + this.expressionDelayMs).toFixed(0)}, ` +
            `exprOffsetMs=${offsetMs.toFixed(0)}, ` +
            `frameIdx=${frameIndex}/${this.expressionFrameMaxIndex}, ` +
            `hit=${!!this.expressionFrameMap.get(frameIndex)}, clamped=${frameIndex > this.expressionFrameMaxIndex}, ` +
            `jawOpen=${jawVal}`
        );
    }

    return frame ?? this.lastValidFrame ?? null;
}
```

**v2のポイント**:
- **`expressionDelayMs`（300ms）**: expression参照を音声再生より300ms遅らせることで、A2E HTTP推論遅延による「先走り」を抑制。リアルタイムリップシンクでは口パクを少し遅らせる方が停止するよりずっと自然（ChatGPT提案）
- **三段構えのフレーム取得**: (1) Map直接hit → (2) maxIndexへのclamping → (3) lastValidFrame。v1では(1)と(3)のみで、(2)のclampingが欠落していたため、frameIndex > maxIndex で常にlastValidFrameが初期値のまま固定された（Gemini・ChatGPT共通提案）
- **clampingにより `lastValidFrame` が常に最新末尾で更新される**: chunk 1到着後は chunk 1末尾のフレームが使われるため、表情が更新され続ける

> **`expressionDelayMs` の値について**: 初期値300ms。A2E HTTPレイテンシ（ログ上約3秒）はバッファリング（初回0.1秒、後続5秒）で大部分が吸収されるため、expressionDelayMsはバッファリングで吸収しきれない残余遅延の補正。実証テストで調整する。

#### (4) クリア処理の変更

`clearPlaybackQueue()` と `resetForNewSegment()` と `onAiResponseStarted()` 内の `expressionFrameBuffer = []` を以下に置換:

```typescript
this.expressionFrameMap = new Map();
this.expressionFrameMaxIndex = -1;
this.lastValidFrame = null;
```

### 14.8 未到着・遅延フレームのポリシー（v2改訂）

| 状況 | 対応 | 根拠 |
|------|------|------|
| 該当フレームがMapに存在 | そのフレームを返す | 理想ケース |
| `frameIndex > maxIndex` | maxIndexのフレームを返す（clamping） | Gemini・ChatGPT共通提案。旧Array版の `Math.min` 相当 |
| Map範囲内だが穴（推定誤差由来） | `lastValidFrame` を返す（前フレーム保持） | Gemini・ChatGPT共通提案 |
| 再生済み時刻のchunkが後から到着 | Mapに格納する（参照されるかは再生位置次第） | データ一貫性の維持 |
| バッファクリア時 | `Map.clear()` + `expressionFrameMaxIndex = -1` + `lastValidFrame = null` | 新セグメントは白紙から |

### 14.9 不採用とした提案

| 提案 | 提案元 | 不採用理由 |
|------|--------|-----------|
| A2E HTTP並列数制限（セマフォ） | ChatGPT | バッファ設計（初回0.1秒、後続5秒）で実質2〜3並列に収まる。修正1+2で順序問題は解決されるため過剰 |
| job_id紐付けによるデバッグ改善 | ChatGPT | `chunk_index` + `start_frame` で追跡可能。優先度低 |
| Jitter Buffer（音声側に遅延挿入） | Gemini | 音声レイテンシ増加。表情側で吸収する方が適切 |
| neutral decay（末尾保持→lerp→0） | Gemini v1 / ChatGPT v2 | 現行コードにneutral expressionの定義なし。clamping + expressionDelayMs で十分。必要に応じてセクション10.7 B-2として別途検討 |
| `start_sample_24k` をフロントに送信しフロント側で `start_frame` 変換 | ChatGPT | backendで変換する方がフロントの変更が少ない。24kHzサンプルレートはbackendの関心事 |

### 14.10 修正対象まとめ（v2改訂）

| # | ファイル | 変更内容 | 規模 |
|---|---------|---------|------|
| 1 | `live_api_handler.py` | `_a2e_total_frames_sent` → `_a2e_total_samples_24k` に置換、`_flush_a2e_buffer` で `start_frame` をサンプル数から算出、`_send_to_a2e` シグネチャ変更・emitペイロード追加、リセット箇所4か所に `_a2e_total_samples_24k = 0` 追加 | 小 |
| 2 | `live-audio-manager.ts` | `expressionFrameBuffer: ExpressionFrame[]` → `expressionFrameMap: Map` + `expressionFrameMaxIndex` + `lastValidFrame` + `expressionDelayMs` 追加、`getCurrentExpressionFrame` に三段構えロジック + expressionDelayMs適用、`onExpressionReceived` / クリア処理3か所の変更 | 中 |

### 14.11 セクション10・11との関係

- **セクション10（A-1 + A-2）**: 最終チャンク品質改善 → **独立・併用可能**
- **セクション11（context持ち回し）**: A2Eサービス側のチャンク間連続性 → **独立・併用可能**
- **本セクション14**: フロントエンドでの表情フレーム順序保証 → **独立・併用可能**

3つの改善は異なるレイヤーの問題を解決するため、**全て併用**することで最大の効果が得られる。

```
セクション10: A2Eサービスへの入力品質（最終チャンク）
セクション11: A2Eサービス内部のcontext連続性（チャンク間）
セクション14: フロントエンドでの出力フレーム順序（チャンク順序ずれ + 再生ヘッド先走り抑制）
```

---

## 参照ドキュメント

| 文書 | 内容 |
|------|------|
| `docs/09_liveapi_migration_design_v6.md` §4 | V6統合仕様書（A2Eセクション） |
| `docs/10_lam_audio2expression_spec.md` | A2E技術仕様書 |
| `docs/11_a2e_lipsync_implementation_guide.md` | リップシンク実装ルール（本ドキュメントに統合） |
| `docs/12_shop_audio_a2e_sync_fix_spec.md` | 修正案C仕様（本ドキュメントに統合） |
| A2E公式リポジトリ | https://github.com/aigc3d/LAM_Audio2Expression |
| 論文 | He, Y. et al. (2025). "LAM: Large Avatar Model" arXiv:2502.17796v2 |
