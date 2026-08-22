# Chatty-sp 用 Google検索 Function Calling 導入指示書

> 元実装: AI-mtg-assistant コミット `e19d232` (`support-base/live_api_handler.py`)
> 適用先: `mirai-gpro/Chatty-sp` ブランチ `main`、ファイル `chatty-base/live_api_handler.py`

---

## 1. 背景

Live API 3.1 (`gemini-3.1-flash-live-preview`) では `google_search` ツールが正常動作しない不具合あり (Google も把握済み)。
回避策として、LLM が必要と判断したときに **Function Calling 経由で REST API (`gemini-2.5-flash`) を呼び出して検索を代替する** 仕組みを導入する。

---

## 2. 修正対象

`chatty-base/live_api_handler.py` の **1ファイルのみ** 修正。

修正箇所は3つ:
1. `GOOGLE_SEARCH_DECLARATION` Function宣言を新規追加
2. `_build_config()` の `config["tools"]` 配列に追加
3. `_handle_tool_call()` に `google_search` 分岐と `_handle_google_search()` メソッドを追加

フロントエンド・他のバックエンドファイル・Dockerfile・依存ライブラリ・環境変数は **一切変更不要**。

---

## 3. パッチ詳細

### パッチ ①: `GOOGLE_SEARCH_DECLARATION` 追加

**位置**: `UPDATE_USER_PROFILE_DECLARATION` (line 377-391 付近) の **直後** に挿入。

```python
# ※ Live API 3.1 では google_search ツールが正常動作しないため、
#    REST API (gemini-2.5-flash) を Function Calling 経由で呼び出して代替する
GOOGLE_SEARCH_DECLARATION = types.FunctionDeclaration(
    name="google_search",
    description=(
        "Web検索で最新情報・事実情報を取得する。会議で議論されているトピック、"
        "最近のニュース、固有名詞や専門用語の確認、リアルタイム情報や"
        "学習データ外の情報が必要なときに呼び出す。"
        "結果テキストが返るので、要点を簡潔にまとめて読み上げること。"
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "query": types.Schema(
                type="STRING",
                description="検索クエリ。会話の文脈に沿った具体的な検索語句。例: 'Anthropic Claude 4.7 リリース日'"
            )
        },
        required=["query"]
    )
)
```

> **Chatty-sp 向けカスタマイズ**: description の「会議で」を「会話で」に置換済 (Chatty-sp は飲食シーンなので「会議」は不自然)。

---

### パッチ ②: `_build_config()` の tools 配列に追加

**位置**: 現在の `_build_config()` 内 (line 527-537 付近)、tools 配列を書き換え。

#### 修正前
```python
# モードに応じたfunction calling定義
if self.mode == 'lesson':
    config["tools"] = [types.Tool(function_declarations=[UPDATE_USER_PROFILE_DECLARATION])]
else:
    config["tools"] = [types.Tool(function_declarations=[
        RECOMMEND_MENU_DECLARATION,
        ADD_TO_ORDER_DECLARATION,
        SHOW_ORDER_SUMMARY_DECLARATION,
        UPDATE_USER_PROFILE_DECLARATION
    ])]
```

#### 修正後
```python
# モードに応じたfunction calling定義
if self.mode == 'lesson':
    config["tools"] = [types.Tool(function_declarations=[
        UPDATE_USER_PROFILE_DECLARATION,
        GOOGLE_SEARCH_DECLARATION,
    ])]
else:
    config["tools"] = [types.Tool(function_declarations=[
        RECOMMEND_MENU_DECLARATION,
        ADD_TO_ORDER_DECLARATION,
        SHOW_ORDER_SUMMARY_DECLARATION,
        UPDATE_USER_PROFILE_DECLARATION,
        GOOGLE_SEARCH_DECLARATION,
    ])]
```

> **両モードに追加**: lesson / concierge どちらでも検索機能を使えるようにする。片方だけで良ければ、不要なほうから外す。

---

### パッチ ③: `_handle_tool_call()` に分岐追加 + `_handle_google_search()` メソッド追加

**位置**: `_handle_tool_call()` の最後の `update_user_profile` 分岐 (line 1010-1035 付近) の **直後**、`else: logger.warning(...)` の **直前** に挿入。

#### 既存コード (前後関係確認用)
```python
        elif fc.name == "update_user_profile":
            # ... 既存処理 ...
            await session.send_tool_response(
                function_responses=[types.FunctionResponse(
                    name=fc.name,
                    id=fc.id,
                    response={"result": "プロファイルを更新しました"}
                )]
            )
        # ★ ここに新分岐を挿入 ★
        else:
            logger.warning(f"[LiveAPI] 未知のfunction call: {fc.name}")
```

#### 挿入する分岐
```python
        elif fc.name == "google_search":
            # Live API 3.1 の google_search 不具合回避: REST API (gemini-2.5-flash) で代替
            query = fc.args.get("query", "")
            logger.info(f"[LiveAPI] google_search呼び出し: '{query}'")
            result_text = await self._handle_google_search(query)
            await session.send_tool_response(
                function_responses=[types.FunctionResponse(
                    name=fc.name,
                    id=fc.id,
                    response={"result": result_text}
                )]
            )
```

#### 追加する新メソッド

`_handle_tool_call()` メソッドの **直後** (= `else: logger.warning(...)` の閉じ括弧の後、次のメソッド `_process_turn_complete()` 等が始まる前) に追加。

```python
    async def _handle_google_search(self, query: str) -> str:
        """
        gemini-2.5-flash + google_search tool を REST API 経由で呼び出し、検索結果テキストを返す。
        Live API 3.1 では google_search ツールが正常動作しない問題への代替実装。
        """
        if not query:
            return "検索クエリが空でした。"
        try:
            loop = asyncio.get_event_loop()

            def _call_search():
                config = types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )
                response = self.client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=query,
                    config=config,
                )
                return response.text or ""

            result_text = await loop.run_in_executor(None, _call_search)
            logger.info(f"[GoogleSearch] '{query}' → 結果 {len(result_text)}文字取得")
            return result_text
        except Exception as e:
            logger.error(f"[GoogleSearch] エラー: {e}", exc_info=True)
            return f"検索中にエラーが発生しました: {str(e)}"
```

---

## 4. 動作確認

### Pythonの構文チェック
```bash
python3 -c "import ast; ast.parse(open('chatty-base/live_api_handler.py').read()); print('Syntax OK')"
```

### デプロイ後の挙動テスト
ブラウザで Chatty-sp を開き、以下のような発話をする:
- 「**最近のニュースを教えて**」
- 「**Claude Sonnet 4.6 のリリース日について調べて**」
- 「**Anthropic の本社はどこ？**」

### 期待ログ (Cloud Run ログ)
```
[LiveAPI] google_search呼び出し: '...クエリ...'
[GoogleSearch] '...クエリ...' → 結果 NNN文字取得
```

### 期待挙動
1. LLM が「検索が必要」と自律判断 → `google_search` Function call
2. バックエンドで `gemini-2.5-flash` が REST 検索実行
3. 結果テキストが Function Response として Live API LLM に戻る
4. Live API LLM が結果を音声で要約・読み上げ → リップシンク連動
5. AI 発話は既存の `output_transcription` 経路で会話ログに自動記録

---

## 5. 既存機能との関係

| 既存機能 | 影響 |
|---|---|
| `search_shops` (レストラン検索) | 影響なし。引き続きレストラン検索の用途で動作 |
| `recommend_menu` / `add_to_order` / `show_order_summary` | 影響なし |
| `update_user_profile` (名前認識) | 影響なし |
| リップシンク (LAM/A2E) | 影響なし |
| 初期あいさつ (挨拶/`greeting_done`) | 影響なし (Chatty-sp 側の仕様に依存) |

`google_search` は LLM が自律判断で呼び出すため、既存 Function 同士で競合することはない (LLM が文脈から最適な Function を1つ選ぶ)。

---

## 6. 環境変数・依存関係

**変更不要**:
- `GEMINI_API_KEY`: 既存の Live API 用キーをそのまま流用 (`self.client` 経由)
- `requirements.txt`: 追加パッケージなし (`google-genai` は既に Live API で使用中)
- `Dockerfile`: 変更なし

---

## 7. 既知の制約

- **検索結果の長さ**: `gemini-2.5-flash` の出力テキストがそのまま LLM に渡るため、長文の場合は読み上げ時間が伸びる。必要なら `_handle_google_search()` 内で `result_text[:1000]` 等で切り詰める or 「200字以内で要約して」を contents に追加
- **クォータ**: `gemini-2.5-flash` のレート制限は Live API と別カウント。会議中の頻繁な検索で枯渇する可能性。監視推奨
- **言語**: クエリ・結果は LLM が自動的にユーザーの会話言語に合わせる (description で明示制限なし)

---

## 8. 適用後の挙動チューニング (オプション)

### 8.1 検索結果を要約させる場合
`_handle_google_search()` の `_call_search()` 内で:
```python
contents=f"以下のクエリについて Web 検索し、結果を200字以内で日本語要約してください。\n\nクエリ: {query}",
```
に変更。

### 8.2 LLM がほとんど検索を呼ばない場合
`GOOGLE_SEARCH_DECLARATION` の description を強化:
```python
description=(
    "Web検索を実行する。リアルタイム情報・最新ニュース・固有名詞・"
    "専門用語の確認が必要なときは積極的に呼び出すこと。"
    "推測で答えるより検索したほうが正確な情報を提供できる。"
),
```

### 8.3 検索範囲を絞りたい場合
`_call_search()` の `contents` に「site:example.com の範囲で」等のフィルタを追加可能 (ただし `google_search` tool の挙動は Google 任せ)。

---

## 9. 適用順序の推奨

1. ローカルで `chatty-base/live_api_handler.py` にパッチ ①〜③ 適用
2. `python3 -c "import ast; ast.parse(...)"` で構文チェック
3. 1コミットで commit
4. push → Cloud Run 自動デプロイ
5. デプロイ完了後ブラウザで動作確認
6. 必要なら 8.1〜8.3 のチューニング

---

## 10. 参考: AI-mtg-assistant 側のコミット

- 実装コミット: `e19d232` (feat: Google検索 Function Calling 実装（gemini-2.5-flash REST代替）)
- ブランチ: `claude/inherit-migration-tests-e4lrG`
- ファイル: `support-base/live_api_handler.py`

このコミットの diff をそのまま参考にできる (パスを `support-base/` → `chatty-base/` に置換)。
