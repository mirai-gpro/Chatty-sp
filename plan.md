# 定型音声アナウンス + 1軒目preconnect 実装計画

## 概要
2つのUX改善をバックエンド（live_api_handler.py）に実装する。
両モード（グルメ/コンシェルジュ）共通で動作する。

---

## 事前準備: PCM音声ファイル生成

### 生成スクリプト作成
- `support-base/generate_announce_pcm.py` を作成
- GCP TTS API で LINEAR16 (24kHz, mono) の PCM ファイルを生成
- 生成先: `support-base/audio/` ディレクトリ

### 定型音声パターン（各3パターン）

**検索中フォロー（search_wait）:**
1. `search_wait_1.pcm` - 「只今、お店の情報を確認中です。もう少々お待ちください。」
2. `search_wait_2.pcm` - 「お店を探しております。少々お待ちくださいませ。」
3. `search_wait_3.pcm` - 「ご希望に合うお店を探しています。もう少しお待ちください。」

**ショップ紹介つなぎ（shop_intro）:**
1. `shop_intro_1.pcm` - 「お待たせしました。お店をご紹介しますね。」
2. `shop_intro_2.pcm` - 「お待たせいたしました。おすすめのお店をご紹介します。」
3. `shop_intro_3.pcm` - 「お店が見つかりました。早速ご紹介させていただきます。」

### フォーマット
- 24kHz, 16bit, mono, raw PCM（LiveAPI出力と同一フォーマット）
- A2Eパイプライン（`_buffer_for_a2e`）にそのまま渡せる

---

## 改善1: 検索中フォローアナウンス

### 変更ファイル: `support-base/live_api_handler.py`

### 変更箇所: `_handle_shop_search()` (line 733)

### ロジック
1. `run_in_executor` を `asyncio.create_task` でラップ
2. 5秒タイマーを並行で走らせる
3. 5秒経過時に検索未完了なら、`search_wait` 音声をランダム選択して再生
4. 再生は `live_audio` emit + `_buffer_for_a2e` でA2Eパイプラインを通す

```python
async def _handle_shop_search(self, user_request: str):
    search_task = asyncio.create_task(
        loop.run_in_executor(None, self._shop_search_callback, ...)
    )

    # 5秒後にフォローアナウンス
    announce_task = asyncio.create_task(
        self._play_search_wait_announce(search_task)
    )

    shop_data = await search_task
    announce_task.cancel()  # 検索完了後はキャンセル
    # ... 以降既存処理
```

### 新メソッド: `_play_search_wait_announce(search_task)`
```python
async def _play_search_wait_announce(self, search_task):
    await asyncio.sleep(5)
    if not search_task.done():
        pcm = random.choice(self._search_wait_audio)
        await self._play_prerecorded_audio(pcm)
```

### 新メソッド: `_play_prerecorded_audio(pcm_data)`
- `live_audio` イベントで PCM をチャンク分割して送信
- `_buffer_for_a2e` でA2Eパイプラインにも流す
- `_flush_a2e_buffer(force=True, is_final=True)` で最終フラッシュ
- `_a2e_chunk_index` リセット

---

## 改善2: ショップ紹介つなぎ音声 + 1軒目 preconnect (B-1)

### 変更ファイル: `support-base/live_api_handler.py`

### 変更箇所: `_handle_shop_search()` (line 769以降) + `_describe_shops_via_live()` (line 825)

### ロジック
1. `shop_search_result` emit 直後に、つなぎ音声再生 + 1軒目LiveAPI preconnect を並行開始
2. つなぎ音声の再生完了を待ってから、1軒目のストリーミングを開始
3. preconnect したセッションを `_stream_single_shop` に渡す

### `_handle_shop_search` の変更
```python
# shop_search_result emit 後
# つなぎ音声再生 + preconnect を並行
intro_task = asyncio.create_task(
    self._play_prerecorded_audio(random.choice(self._shop_intro_audio))
)
await self._describe_shops_via_live(shops, intro_task)
```

### `_describe_shops_via_live` の変更
```python
async def _describe_shops_via_live(self, shops, intro_task=None):
    total = len(shops)
    if total == 0:
        return

    # 2軒目以降の並行生成を即座に開始
    remaining_tasks = [...]

    # 1軒目用 preconnect（B-1: 手動 __aenter__)
    config = ...  # 1軒目用config構築
    connector = self.client.aio.live.connect(model=..., config=config)
    session = await connector.__aenter__()

    try:
        # つなぎ音声の完了を待つ
        if intro_task:
            await intro_task

        # 1軒目: preconnect済みセッションでストリーミング
        await self._stream_single_shop_with_session(session, shops[0], 1, total)
    finally:
        await connector.__aexit__(None, None, None)

    # 2軒目以降: 既存処理
    for i, task in enumerate(remaining_tasks):
        ...
```

---

## 起動時の音声ファイルロード

### `__init__` に追加
```python
# 定型音声ロード
self._search_wait_audio = self._load_audio_files('audio/search_wait_*.pcm')
self._shop_intro_audio = self._load_audio_files('audio/shop_intro_*.pcm')
```

### 新メソッド: `_load_audio_files(pattern)`
- glob でファイルを読み込み、bytes のリストとして返す
- ファイルが無い場合はログ警告のみ（機能は無効化）

---

## 変更ファイル一覧
1. `support-base/generate_announce_pcm.py` (新規) - PCM生成スクリプト
2. `support-base/audio/*.pcm` (新規) - 定型音声ファイル6個
3. `support-base/live_api_handler.py` (変更) - メインロジック
