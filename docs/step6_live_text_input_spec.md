# Step 6: テキスト入力のLiveAPI対応 — 修正仕様書

## 1. 目的

現状、Chatty AIモード（lessonモード）の `sendMessage()` はREST API `/api/chat` にfetchしている。
テキスト入力もLiveAPIセッション経由に変更し、音声入力と同一のパスで処理する。

これにより:
- 音声入力・テキスト入力で応答品質に差がなくなる
- LiveAPIのFunction Calling（Google検索等）がテキスト入力でも利用可能になる
- A2Eリップシンクがテキスト入力の応答でも動作する
- 会話履歴がLiveAPIセッション内で一元管理される

## 2. 現状のフロー

### 音声入力（正常動作中）
```
ブラウザ マイク → AudioWorklet → PCM → socket.emit('live_audio_in')
  → LiveAPISession.enqueue_audio() → Gemini LiveAPI
  → 応答: live_audio / ai_transcript / live_expression / turn_complete
  → ブラウザ: 音声再生 + リップシンク + チャット表示
```

### テキスト入力（現状: REST API）
```
ブラウザ テキスト → fetch('/api/chat', {message})
  → SupportAssistant → Gemini REST API
  → JSONレスポンス → ブラウザ: TTS + チャット表示（リップシンクなし）
```

## 3. 変更後のフロー

### テキスト入力（変更後: LiveAPI経由）
```
ブラウザ テキスト → socket.emit('live_text_input', {session_id, text})
  → LiveAPISession.send_text(text)
    → session.send_client_content(text, turn_complete=True)
  → Gemini LiveAPI
  → 応答: live_audio / ai_transcript / live_expression / turn_complete
  → ブラウザ: 音声再生 + リップシンク + チャット表示
```

## 4. バックエンド変更

### 4.1 app_customer_support.py — 新規Socket.IOイベント

```python
@socketio.on('live_text_input')
def handle_live_text_input(data):
    """テキスト入力をLiveAPIセッションに送信"""
    client_sid = request.sid
    session_id = data.get('session_id')
    text = data.get('text', '').strip()

    if not text:
        return

    live_session = active_live_sessions.get(client_sid)
    if not live_session or not live_session.is_running:
        emit('live_text_error', {'error': 'LiveAPIセッションが未接続です'})
        return

    live_session.enqueue_text(text)
```

### 4.2 live_api_handler.py — LiveAPISessionクラスに追加

```python
def __init__(self, ...):
    ...
    self.text_queue = asyncio.Queue()  # テキスト入力用キュー

def enqueue_text(self, text: str):
    """テキスト入力をキューに追加"""
    if self.text_queue and self.is_running:
        try:
            self.text_queue.put_nowait(text)
        except asyncio.QueueFull:
            pass
```

### 4.3 live_api_handler.py — _session_loop() にテキスト送信タスクを追加

`_session_loop()` の `TaskGroup` に3つ目のタスクを追加:

```python
async def send_text():
    """テキスト入力をLiveAPIに送信"""
    while not self.needs_reconnect and self.is_running:
        try:
            text = await asyncio.wait_for(
                self.text_queue.get(),
                timeout=0.1
            )
            # テキストをsend_client_contentで送信
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=text)]
                ),
                turn_complete=True
            )
            # 会話履歴に追加
            self._add_to_history("user", text)
            logger.info(f"[LiveAPI] テキスト入力送信: '{text[:50]}'")
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            if self.needs_reconnect or not self.is_running:
                return
            logger.error(f"[LiveAPI] テキスト送信エラー: {e}")
            self.needs_reconnect = True
            return

async with asyncio.TaskGroup() as tg:
    tg.create_task(send_audio())
    tg.create_task(send_text())   # ← 追加
    tg.create_task(receive())
```

### 4.4 テキストキューの初期化とクリア

`run()` メソッドのループ先頭で:
```python
self.text_queue = asyncio.Queue(maxsize=10)
```

`_session_loop()` のキュークリア部分に追加:
```python
while not self.text_queue.empty():
    try:
        self.text_queue.get_nowait()
    except asyncio.QueueEmpty:
        break
```

## 5. フロントエンド変更

### 5.1 lesson-controller.ts — sendMessage() の書き換え

REST API fetchを削除し、Socket.IO emit に変更:

```typescript
protected async sendMessage() {
    this.unlockAudioParams();
    const message = this.els.userInput.value.trim();
    if (!message || this.isProcessing) return;

    this.isProcessing = true;
    this.els.sendBtn.disabled = true;
    this.els.micBtn.disabled = true;
    this.els.userInput.disabled = true;

    // テキスト入力時の処理
    if (!this.isFromVoiceInput) {
        this.addMessage('user', message);
        const textLength = message.trim().replace(/\s+/g, '').length;
        if (textLength < 2) {
            const msg = this.t('shortMsgWarning');
            this.addMessage('assistant', msg);
            if (this.isTTSEnabled && this.isUserInteracted) await this.speakTextGCP(msg, true);
            this.resetInputState();
            return;
        }
        this.els.userInput.value = '';
    }

    this.isFromVoiceInput = false;

    // LiveAPIセッション経由でテキスト送信
    if (this.isLiveMode && this.socket?.connected) {
        this.socket.emit('live_text_input', {
            session_id: this.sessionId,
            text: message
        });
    }

    // 応答はLiveAPIリスナー（ai_transcript, live_audio, turn_complete）で処理
    // turn_completeでresetInputState()が呼ばれる

    this.resetInputState();
}
```

### 5.2 turn_complete ハンドラの調整

`core-controller.ts` の既存 `turn_complete` ハンドラ（L357-375）が応答完了時の処理を担当。
テキスト入力の場合も同じパスで処理されるため、追加変更は不要。

ただし `userTranscriptBuffer` にテキスト入力の内容が入らない点に注意:
- 音声入力: `user_transcript` イベントで `userTranscriptBuffer` に蓄積 → `turn_complete` でチャット表示
- テキスト入力: `sendMessage()` 内で先に `addMessage('user', message)` 済み → `turn_complete` では表示不要

`turn_complete` ハンドラの `userTranscriptBuffer` 表示部分（L362-365）は `currentMode !== 'lesson'` でガードされているため、lessonモードでは影響なし。

## 6. 変更対象ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| `chatty-base/app_customer_support.py` | `live_text_input` Socket.IOイベントハンドラ追加 |
| `chatty-base/live_api_handler.py` | `text_queue`, `enqueue_text()`, `send_text()` タスク追加 |
| `src/scripts/chat/lesson-controller.ts` | `sendMessage()` をREST API → Socket.IO emitに変更 |

## 7. 変更しないもの

- `core-controller.ts` — LiveAPIリスナー（ai_transcript, live_audio, turn_complete, live_expression）はそのまま利用
- REST API `/api/chat` — chatモード・conciergeモードで引き続き使用
- A2E関連 — LiveAPI応答として自動的にリップシンクが動作

## 8. テスト確認項目

1. テキスト入力 → LLMが音声で応答する（live_audioで再生）
2. テキスト入力 → AI応答がチャット欄にストリーミング表示される（ai_transcript）
3. テキスト入力 → リップシンクが動作する（live_expression）
4. テキスト入力 → Google検索が動作する（天気・ニュース等）
5. 音声入力は従来通り正常動作する
6. テキスト入力と音声入力を交互に使っても正常動作する
7. セッション再接続後もテキスト入力が正常動作する
