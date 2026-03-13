# 修正仕様書: ハイブリッド構成（Claude REST + Gemini LiveAPI）

## 1. 概要

### 1.1 背景
Claudeで実現できた成功事例を基に、以下の2つの機能を両立させる:
- **正確で細かなショップカード表示** → Claude REST API
- **お店の説明をLiveAPIで喋らせる** → 現行LiveAPI実装（変更なし）

### 1.2 方針
「正しいアーキテクチャ」ではないが、**実証済みの成功パターン**を採用する。

| 機能 | 担当 | 変更 |
|------|------|------|
| 音声入力（STT） | Gemini LiveAPI | 変更なし |
| 音声出力（TTS・読み上げ） | Gemini LiveAPI | 変更なし |
| 検索トリガー（function calling） | Gemini LiveAPI | 変更なし |
| ショップカード生成（JSON） | **Claude REST API** | **新規** |
| チャットテキスト表示 | **Claude REST API** | **変更** |
| ai_transcript（LiveAPI出力テキスト） | 非表示（内部利用のみ） | **変更** |

---

## 2. アーキテクチャ変更

### 2.1 現行フロー
```
ユーザー音声
  → LiveAPI (STT + 意図理解)
  → search_shops function calling 発火
  → shop_search_callback()
    → SupportAssistant.process_user_message()  ← Gemini REST
    → Gemini 2.5-flash がショップJSON生成
    → enrich_shops_with_photos() で外部API補強
  → shop_search_result イベント (ショップカード表示)
  → _describe_shops_via_live() (LiveAPIで1軒ずつ読み上げ)
  → ai_transcript イベント (テキスト表示)
```

### 2.2 変更後フロー
```
ユーザー音声
  → LiveAPI (STT + 意図理解)              ← 変更なし
  → search_shops function calling 発火      ← 変更なし
  → shop_search_callback()
    → ★ Claude REST API がショップJSON生成   ← 変更箇所
    → enrich_shops_with_photos()             ← 変更なし
  → shop_search_result イベント              ← 変更なし
  → _describe_shops_via_live()              ← 変更なし（LiveAPIで読み上げ）
  → ★ Claude REST の応答テキストを表示       ← 変更箇所
  → ★ ai_transcript は非表示               ← 変更箇所
```

---

## 3. 変更対象ファイルと変更内容

### 3.1 `support_core.py` — SupportAssistant クラス

#### 変更箇所: `process_user_message()` メソッド（L534-666）

**現行:**
```python
# Gemini 2.5-flash で生成
response = gemini_client.models.generate_content(
    model="gemini-2.5-flash",
    contents=history,
    config=config
)
```

**変更後:**
```python
# Claude REST API で生成
# Anthropic SDK (anthropic パッケージ) を使用
# モデル: claude-sonnet-4-6（コスト/速度バランス）
```

**変更詳細:**
1. `anthropic` パッケージをインポート
2. `ANTHROPIC_API_KEY` 環境変数を追加
3. `process_user_message()` 内のLLM呼び出しをClaude APIに差し替え
4. 会話履歴の形式を Gemini `types.Content` → Claude `messages` 形式に変換
5. システムプロンプトは既存のものをそのまま使用（`system` パラメータで渡す）
6. JSON出力のパース処理（`_parse_json_response`）は変更なし

#### 注意: 変更しないもの
- `SupportSession` クラス: 変更なし
- `get_initial_message()`: 変更なし（LLM呼び出しがないため）
- `_generate_summary()`: Gemini のまま or Claude に統一（要検討）
- `generate_final_summary()`: 同上

### 3.2 `live_api_handler.py` — LiveAPISession クラス

#### 変更なし
以下はすべて現行コードのまま:
- `SEARCH_SHOPS_DECLARATION`: function calling 定義
- `_handle_tool_call()`: search_shops 処理
- `_handle_shop_search()`: shop_search_callback 呼び出し
- `_describe_shops_via_live()`: ショップ読み上げ
- `_receive_shop_description()`: 読み上げ音声受信
- 再接続メカニズム全般

### 3.3 `app_customer_support.py` — Webアプリケーション層

#### 変更箇所1: `shop_search_callback`（L783-801）
- 内部で `SupportAssistant.process_user_message()` を呼ぶ → これが Claude REST に変わるため、コールバック自体の変更は不要（SupportAssistant内部の変更で対応）

#### 変更箇所2: `chat()` REST エンドポイント（L230-401）
- `SupportAssistant.process_user_message()` の中身が Claude に変わるため、エンドポイント自体の変更は最小限
- `enrich_shops_with_photos()` の呼び出しは変更なし

#### 変更箇所3: フロントエンドへのイベント送信
- **`ai_transcript` イベント**: LiveAPIから送信されるが、フロントエンド側で**非表示**にする
- **`shop_search_result` イベント**: Claude が生成した `message` フィールドをチャットテキストとして表示

### 3.4 フロントエンド側変更

#### `ai_transcript` の扱い
**現行:** チャットエリアにリアルタイム表示
**変更後:** 表示しない（音声のみ再生）

#### `shop_search_result` の `response` フィールド
**現行:** Gemini が生成した応答テキスト
**変更後:** Claude が生成した応答テキストをチャットエリアに表示

#### 通常会話テキスト（ショップ検索以外）
**現行:** LiveAPI の `ai_transcript` をリアルタイム表示
**変更後:**
- 選択肢A: LiveAPI の transcript を非表示にし、Claude REST でテキスト生成して表示
- 選択肢B: 通常会話時のみ `ai_transcript` を表示し、ショップ検索時のみ Claude テキストに切り替え
- **推奨: 選択肢B**（通常会話のレイテンシを維持するため）

---

## 4. 環境変数追加

| 変数名 | 値 | 設定箇所 |
|--------|-----|---------|
| `ANTHROPIC_API_KEY` | Claude APIキー | Cloud Run 環境変数 / `.env` |

### 4.1 Cloud Run デプロイ設定
`.github/workflows/deploy-cloud-run.yml` に追加:
```yaml
--set-env-vars="ANTHROPIC_API_KEY=${{ secrets.ANTHROPIC_API_KEY }}"
```

### 4.2 Dockerfile
`requirements.txt` に追加:
```
anthropic
```

---

## 5. Claude REST API 呼び出し仕様

### 5.1 リクエスト形式
```python
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system=system_prompt,       # 既存のシステムプロンプトをそのまま使用
    messages=claude_messages,   # 変換済みの会話履歴
)
```

### 5.2 会話履歴の変換
```python
# Gemini形式 → Claude形式
def convert_history_for_claude(gemini_history):
    """types.Content リストを Claude messages 形式に変換"""
    claude_messages = []
    for content in gemini_history:
        role = "user" if content.role == "user" else "assistant"
        text = content.parts[0].text
        claude_messages.append({"role": role, "content": text})
    return claude_messages
```

### 5.3 レスポンス処理
```python
# Claude のレスポンスからテキストを取得
assistant_text = response.content[0].text

# 以降は既存の _parse_json_response() でパース（変更なし）
parsed_message, parsed_shops, parsed_action = self._parse_json_response(assistant_text)
```

---

## 6. データフローまとめ

### 6.1 ショップ検索時
```
[LiveAPI]  ユーザー音声 → STT → 意図理解 → search_shops 発火
                                              ↓
[Backend]  shop_search_callback()
           → SupportAssistant.process_user_message()
             → ★ Claude REST API 呼び出し
             → ショップJSON取得
             → enrich_shops_with_photos()
                                              ↓
[Frontend] shop_search_result イベント受信
           → ショップカード表示（Claude生成のJSON）
           → Claude の message をチャットテキスト表示
                                              ↓
[LiveAPI]  _describe_shops_via_live()
           → 1軒ずつ LiveAPI で読み上げ（現行通り）
           → live_audio イベント（音声再生のみ）
           → ai_transcript イベント（★非表示）
```

### 6.2 通常会話時
```
[LiveAPI]  ユーザー音声 → STT → AI応答生成 → 音声出力
           → live_audio イベント（音声再生）
           → ai_transcript イベント（★表示する ← 通常会話時は表示）
```

---

## 7. リスク・注意事項

### 7.1 レイテンシ
- ショップ検索時: LiveAPI function calling → Claude REST → enrich → 表示
- Claude REST の応答時間（通常1-3秒）が追加される
- ただし、現行でも Gemini REST の応答待ちがあるため、体感差は小さい

### 7.2 コスト
- Claude API 利用料が追加（Gemini REST の代替なので純増ではなく置換）
- モデル選択: `claude-sonnet-4-6`（コスト効率重視）

### 7.3 プロンプト互換性
- 既存のシステムプロンプト（`support_system_ja.txt` / `concierge_ja.txt`）はClaude向けに微調整が必要な可能性あり
- JSON出力形式の強制ルール（`json_enforcement`）はClaude でも動作するが、検証が必要

### 7.4 Google Search グラウンディング
- 現行: `tools = [types.Tool(google_search=types.GoogleSearch())]` で Gemini のグラウンディング利用
- Claude にはこの機能がないため、ショップ情報の正確性は LLM の知識 + enrich_shops_with_photos() に依存
- **影響**: ショップ名の正確性が下がる可能性があるが、enrich_shops_with_photos() で Google Places API による検証・補正が行われるため、最終的なカード品質への影響は限定的

### 7.5 二重LLM構成の複雑さ
- LiveAPI（Gemini）と Claude REST の2つのLLMが同時稼働
- 会話コンテキストの同期は不完全（LiveAPIの会話履歴とClaude RESTの会話履歴は別管理）
- → **許容する**（仕様として正しくないが、実証済みパターン）

---

## 8. LiveAPIモードのウェイティングアニメーション追加

### 8.1 問題
現行のウェイティングアニメーション（`wait-overlay` + `wait.mp4`）は、テキスト入力時の `/api/chat` REST呼び出し前（4秒タイマー）でのみ発火する。
LiveAPIモードでは `shop_search_result` ハンドラに `showWaitOverlay` / `hideWaitOverlay` が**呼ばれておらず**、検索中にウェイティングが表示されない。

Claude REST に切り替えるとレイテンシが追加されるため、LiveAPIモードでもウェイティング表示が必要。

### 8.2 バックエンド変更: `live_api_handler.py`

`_handle_tool_call()` で `search_shops` 発火時に即座にイベントを送信する。

```python
async def _handle_tool_call(self, tool_call, session):
    for fc in tool_call.function_calls:
        if fc.name == "search_shops":
            user_request = fc.args.get("user_request", "")
            logger.info(f"[LiveAPI] search_shops呼び出し: '{user_request}'")

            # ★ 追加: 検索開始通知（ウェイティングアニメーション発火用）
            self.socketio.emit('shop_search_started', {},
                               room=self.client_sid)

            # ショップ検索を実行
            await self._handle_shop_search(user_request)

            # function responseを返す
            # ... (以下変更なし)
```

### 8.3 フロントエンド変更: `core-controller.ts`

`setupSocketListeners()` 内に `shop_search_started` リスナーを追加し、
既存の `shop_search_result` ハンドラに `hideWaitOverlay()` を追加する。

```typescript
// ★ 追加: ショップ検索開始 → ウェイティングアニメーション表示
this.socket.on('shop_search_started', () => {
  console.log('[LiveAPI] shop_search_started: ウェイティング表示');
  this.showWaitOverlay();
});

// ★ 既存の shop_search_result ハンドラに hideWaitOverlay() を追加
this.socket.on('shop_search_result', (data: any) => {
  console.log('[LiveAPI] shop_search_result:', data?.shops?.length || 0, '件');
  this.hideWaitOverlay();  // ★ 追加
  // ... (以下既存コードそのまま)
});
```

### 8.4 フロントエンド変更: `concierge-controller.ts`

`concierge-controller.ts` にも同様の変更を適用する。
（`ConciergeController` は `CoreController` を継承しているため、
  `setupSocketListeners()` をオーバーライドしている場合のみ追加が必要）

### 8.5 タイムライン

```
[LiveAPI] search_shops function calling 発火
  ↓
[Backend] shop_search_started イベント送信  ← 即座
  ↓
[Frontend] showWaitOverlay()               ← ウェイティング表示
  ↓
[Backend] Claude REST API 呼び出し（1-3秒）
  ↓
[Backend] enrich_shops_with_photos()（1-2秒）
  ↓
[Backend] shop_search_result イベント送信
  ↓
[Frontend] hideWaitOverlay()               ← ウェイティング非表示
           displayShops()                  ← カード表示
  ↓
[LiveAPI] _describe_shops_via_live()       ← 読み上げ開始
```

### 8.6 エラー時のフォールバック

検索がエラーで失敗した場合にウェイティングが表示され続けることを防ぐため、
`_handle_shop_search()` のexceptブロックでもイベントを送信する。

```python
async def _handle_shop_search(self, user_request: str):
    if not self._shop_search_callback:
        logger.error("[ShopSearch] shop_search_callback が未設定")
        self.socketio.emit('shop_search_failed', {},
                           room=self.client_sid)  # ★ 追加
        return

    try:
        # ... 既存処理 ...
    except Exception as e:
        logger.error(f"[ShopSearch] エラー: {e}", exc_info=True)
        self.socketio.emit('shop_search_failed', {},
                           room=self.client_sid)  # ★ 追加
```

フロントエンド側:
```typescript
this.socket.on('shop_search_failed', () => {
  console.log('[LiveAPI] shop_search_failed: ウェイティング非表示');
  this.hideWaitOverlay();
});
```

---

## 10. 変更しないもの一覧

| コンポーネント | 理由 |
|-------------|------|
| `live_api_handler.py` 全体 | TTSの実装コードそのまま |
| `SEARCH_SHOPS_DECLARATION` | function calling 定義は変更不要 |
| `_describe_shops_via_live()` | ショップ読み上げは LiveAPI のまま |
| `_receive_shop_description()` | 読み上げ音声受信は変更不要 |
| `enrich_shops_with_photos()` | 外部API連携は変更不要 |
| `api_integrations.py` | 外部API統合は変更不要 |
| `long_term_memory.py` | 長期記憶は変更不要 |
| LiveAPI の再接続メカニズム | 変更不要 |
| LiveAPI のプロンプト（`LIVEAPI_*`） | 音声会話用は Gemini のまま |

---

## 11. 実装優先順

1. **`support_core.py`**: `process_user_message()` の LLM 呼び出しを Claude REST に差し替え
2. **環境変数**: `ANTHROPIC_API_KEY` の追加（Cloud Run + GitHub Secrets）
3. **`requirements.txt`**: `anthropic` パッケージ追加
4. **フロントエンド**: `ai_transcript` の表示制御（ショップ検索時は非表示）
5. **ウェイティングアニメーション**: LiveAPIモード用の `shop_search_started` / `shop_search_failed` 対応（セクション8）
6. **検証**: ショップカードのJSON出力品質テスト
7. **デプロイ**: Cloud Run へ反映
