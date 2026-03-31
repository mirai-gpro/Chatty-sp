# メニューカード表示 詳細仕様書

## 1. 概要

注文サポートモードで、LLMがメニューを提案する際にメニューカードを表示する。
既存のコンシェルジュモードのショップカード表示をベースに、メニュー表示用にカスタマイズする。

### 最大の違い: 全てLiveAPIで完結

| 項目 | ショップカード（既存） | メニューカード（今回） |
|------|----------------------|----------------------|
| 検索/提案のトリガー | LiveAPIのFunction Calling `search_shops` | LiveAPIのFunction Calling `recommend_menu` |
| データ取得 | FC → REST APIで外部検索（Google等） | FC → サーバー内のMarkdownメニューデータから検索 |
| 音声読み上げ | **REST API TTS**（LiveAPIから切り替え） | **LiveAPI音声のまま**（切り替えなし） |
| カード表示 | `shop_search_result` → `displayShops` → ShopCardList | `menu_recommend` → `displayMenuItems` → ShopCardList（メニュー版） |
| A2Eリップシンク | REST TTS時は非対応 | **LiveAPI音声なので対応** |

### ショップカードでREST APIに切り替えている理由（参考）
- 店情報が長いためLiveAPIの累積文字数制限に抵触
- LiveAPIでの読み上げ開始のタイムラグが埋まらなかった（プレビュー版の制約）

### メニューカードでLiveAPIのまま行ける理由
- メニュー名+価格は短い（50文字以内のプロンプトルールに収まる）
- LLMが音声で「和風ハンバーグがおすすめです」と話し、同時にカードを表示
- REST API切り替え不要 → リップシンクが途切れない

---

## 2. 既存ショップカードのフロー（比較用）

### バックエンド（live_api_handler.py）
```
LLMが search_shops FC発火
  → _handle_tool_call() → _handle_shop_search()
    → REST APIで外部検索（Google等）
    → shop_search_result Socket.IOイベントでフロントに送信
    → _describe_shops_via_live() でREST TTS音声生成+再生
```

### フロントエンド（core-controller.ts + ShopCardList.astro）
```
socket.on('shop_search_start') → 待機アニメーション表示
socket.on('shop_search_result') → 
  → displayShops カスタムイベント dispatch
  → ShopCardList.astro がイベント受信
  → ShopCardListManager.displayShops() でカードHTML生成
  → #shopCardList コンテナに挿入
  → shopListSection に has-shops クラス追加（表示）
```

### カード表示位置
```
concierge.astro
├── chat-section（左/上）
│   └── Concierge.astro → chatArea（チャット吹き出し）
└── shop-list-section（右/下）  ← ★ここにカードが表示される
    └── ShopCardList → #shopCardList
```

---

## 3. メニューカードのフロー（今回の実装）

### バックエンド（live_api_handler.py）

```
LLMが recommend_menu FC発火（メニュー名の配列を渡す）
  → _handle_tool_call()
    → メニューMarkdownから該当アイテムを検索（_search_menu_items()）
    → menu_recommend Socket.IOイベントでフロントにカードデータ送信
    → function responseをLiveAPIに返す
    → LLMは音声で提案を続ける（REST APIへの切り替えなし）
    → A2Eリップシンクは通常通り動作
```

### フロントエンド（core-controller.ts + ShopCardList.astro）

```
socket.on('menu_recommend') → core-controller.ts
  → displayMenuItems カスタムイベント dispatch
  → ShopCardList.astro がイベント受信
  → ShopCardListManager.displayMenuItems() でメニューカードHTML生成
  → #shopCardList コンテナに挿入
  → shopListSection に has-shops クラス追加（表示）
```

### カード表示位置（ショップカードと同じ）
```
concierge.astro
├── chat-section（左/上）
│   └── Concierge.astro → chatArea（チャット吹き出し）
└── shop-list-section（右/下）  ← ★メニューカードもここに表示
    ├── ヘッダー: 「おすすめメニュー」
    └── ShopCardList → #shopCardList（メニューカードを表示）
```

---

## 4. Function Calling定義

### recommend_menu

```python
RECOMMEND_MENU_DECLARATION = types.FunctionDeclaration(
    name="recommend_menu",
    description="ユーザーにメニューアイテムを提案する時に呼び出す。"
                "提案するメニュー名を配列で渡す。"
                "音声での説明と同時にメニューカード（画像・価格付き）が"
                "ユーザーの画面に表示される。",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "menu_items": types.Schema(
                type="ARRAY",
                items=types.Schema(type="STRING"),
                description="提案するメニュー名の配列。"
                            "例: ['和風ハンバーグ', 'おろしハンバーグ']"
            )
        },
        required=["menu_items"]
    )
)
```

### conciergeモードのtools定義変更

```python
# 変更前（ショップ検索）
config["tools"] = [types.Tool(function_declarations=[
    SEARCH_SHOPS_DECLARATION, UPDATE_USER_PROFILE_DECLARATION
])]

# 変更後（メニュー提案）
config["tools"] = [types.Tool(function_declarations=[
    RECOMMEND_MENU_DECLARATION, UPDATE_USER_PROFILE_DECLARATION
])]
```

---

## 5. バックエンドのメニュー検索（_search_menu_items）

### 検索ロジック
- メニューMarkdown（GCSから読み込み済み）を`---`で分割
- 各アイテムの`###`タイトルを取得
- LLMが渡したメニュー名と**タイトルの部分一致**で検索
- マッチ方向: `name in title`のみ（`title in name`は広すぎるので除外）

### 返却データ構造
```json
{
  "items": [
    {
      "name": "和風ハンバーグ",
      "image_url": "https://xxx.supabase.co/storage/v1/object/public/menu/dennys/page20_img11.jpg",
      "price": "¥935",
      "description": "40余年こだわりを重ねた醤油風味のソース",
      "menu_number": "20721",
      "drink_bar_price": "¥1,135",
      "time_restriction": "10:30 - 閉店"
    }
  ]
}
```

---

## 6. フロントエンドのメニューカード表示

### 6.1 core-controller.ts の変更

`menu_recommend` Socket.IOリスナーを追加:

```typescript
this.socket.on('menu_recommend', (data: any) => {
  if (!data.items || data.items.length === 0) return;
  
  // displayMenuItems カスタムイベントをdispatch
  document.dispatchEvent(new CustomEvent('displayMenuItems', {
    detail: { items: data.items, language: this.currentLanguage }
  }));
  
  // shopListSectionを表示
  const section = document.getElementById('shopListSection');
  if (section) section.classList.add('has-shops');
  
  // モバイル: カードセクションにスクロール
  if (window.innerWidth < 1024) {
    setTimeout(() => {
      section?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 300);
  }
});
```

### 6.2 ShopCardList.astro の変更

`displayMenuItems`イベントハンドラと`createMenuCard()`メソッドを追加:

```typescript
// イベントリスナー追加
document.addEventListener('displayMenuItems', ((event: CustomEvent) => {
  if (event.detail && event.detail.items) {
    manager.displayMenuItems(event.detail.items);
  }
}) as EventListener);
```

```typescript
// メニューカード表示
displayMenuItems(items: MenuItemData[]) {
  this.container.innerHTML = '';
  items.forEach(item => {
    const card = this.createMenuCard(item);
    this.container.appendChild(card);
  });
}

// メニューカード生成
private createMenuCard(item: MenuItemData): HTMLElement {
  const card = document.createElement('div');
  card.className = 'shop-card menu-item-card';
  
  const imageUrl = item.image_url || '';
  
  card.innerHTML = `
    <div class="hero-image">
      <img src="${imageUrl}" alt="${item.name}" loading="lazy" />
    </div>
    <div class="card-body">
      <h3 class="shop-name">${item.name}</h3>
      <div class="menu-price">${item.price || ''}</div>
      ${item.description ? `<p class="description">${item.description}</p>` : ''}
      <div class="menu-details">
        ${item.menu_number ? `<span class="detail-tag">No. ${item.menu_number}</span>` : ''}
        ${item.drink_bar_price ? `<span class="detail-tag">ドリンクバー付 ${item.drink_bar_price}</span>` : ''}
        ${item.time_restriction ? `<span class="detail-tag">⏰ ${item.time_restriction}</span>` : ''}
      </div>
    </div>
  `;
  
  return card;
}
```

### 6.3 CSS追加（ShopCardList.astro）

既存の`.shop-card` CSSをベースに、メニュー固有のスタイルを追加:

```css
/* メニューカード固有スタイル */
.shop-card-list :global(.menu-item-card .menu-price) {
  font-size: 20px;
  font-weight: 700;
  color: #dc2626;
  margin: 4px 0 8px;
}

.shop-card-list :global(.menu-item-card .menu-details) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.shop-card-list :global(.menu-item-card .detail-tag) {
  font-size: 11px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 2px 8px;
  border-radius: 10px;
}
```

### 6.4 concierge.astro の変更

ショップリストのヘッダーテキストを変更:

```html
<!-- 変更前 -->
<h2 id="shopListTitle">🍽 おすすめのお店</h2>
<p id="shopListEmpty">チャットで検索すると、ここにお店が表示されます</p>

<!-- 変更後 -->
<h2 id="shopListTitle">🍽 おすすめメニュー</h2>
<p id="shopListEmpty">メニューの提案がここに表示されます</p>
```

---

## 7. ショップカードとの処理フロー比較

### ショップカード（既存・REST API切り替え方式）
```
1. ユーザー「渋谷でイタリアン探して」
2. LLM → search_shops FC発火
3. バックエンド: REST APIで外部検索
4. shop_search_result イベントでカードデータ送信
5. ★ ここでLiveAPI音声を停止 → REST TTS音声に切り替え
6. _describe_shops_via_live() でREST TTSの音声をLiveAPIセッション経由で再生
7. フロント: displayShops → ShopCardList にカード表示
8. 音声: REST TTSで店情報を1軒ずつ読み上げ
9. リップシンク: REST TTS区間は非対応
```

### メニューカード（今回・全てLiveAPI方式）
```
1. ユーザー「ハンバーグが食べたい」
2. LLM → recommend_menu FC発火 + 音声で「おすすめは...」と話し始める
3. バックエンド: Markdownから検索 → menu_recommend イベントでカードデータ送信
4. function responseをLiveAPIに返す → LLMは音声を継続
5. ★ LiveAPI音声は途切れない（REST APIへの切り替えなし）
6. フロント: displayMenuItems → ShopCardList にメニューカード表示
7. 音声: LLMがLiveAPIで直接読み上げ（短い内容なので累積制限の心配なし）
8. リップシンク: LiveAPI音声なので通常通り動作
```

---

## 8. 変更対象ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| `chatty-base/live_api_handler.py` | `RECOMMEND_MENU_DECLARATION`追加、`_handle_tool_call`にrecommend_menu処理追加、`_search_menu_items()`追加、`_load_menu_markdown()`追加、conciergeのtools定義変更、`__init__`にshop_id追加、`build_system_instruction`にshop_id引数+メニューMarkdown注入 |
| `chatty-base/app_customer_support.py` | `handle_live_start`でshop_idを取得してLiveAPISessionに渡す、`build_system_instruction`呼び出しにshop_id追加 |
| `chatty-base/prompts/order_support_ja.txt` | `{menu_data}`プレースホルダ追加 |
| `src/scripts/chat/core-controller.ts` | `menu_recommend`リスナー追加（displayMenuItemsイベントdispatch）、`live_start` emitにshop_id追加 |
| `src/components/ShopCardList.astro` | `displayMenuItems`イベントハンドラ追加、`createMenuCard()`メソッド追加、メニュー用CSS追加 |
| `src/pages/concierge.astro` | ショップリストヘッダーテキスト変更 |

---

## 9. 変更しないもの

- `chatArea` へのHTML直接挿入は行わない（前回の失敗を繰り返さない）
- ショップカードの既存機能（chatモード・旧conciergeモード用）は維持
- `live-audio-manager.ts` — A2E関連は変更なし
- `lesson-controller.ts` — Chattyモードは影響なし
- LiveAPIの接続・音声・A2Eの基盤処理 — 変更なし

---

## 10. 実装順序

1. バックエンド: `live_api_handler.py`にrecommend_menu FC+メニュー検索+Markdown注入を追加
2. バックエンド: `app_customer_support.py`でshop_idを渡す
3. バックエンド: `order_support_ja.txt`に`{menu_data}`追加
4. フロント: `core-controller.ts`にmenu_recommendリスナー追加+live_startにshop_id追加
5. フロント: `ShopCardList.astro`にdisplayMenuItemsハンドラ+createMenuCard追加
6. フロント: `concierge.astro`のヘッダーテキスト変更
7. デプロイ＆動作確認

**各ステップ1コミットずつ。** リップシンクへの影響がないことを確認しながら進める。
