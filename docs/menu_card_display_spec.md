# メニューカード表示 仕様書

## 1. 概要

注文サポートモードで、LLMがメニューを提案する際にメニューカードを表示する。
**既存のShopCardList（サイドパネル）の仕組みを流用**し、メニュー専用のカードを表示する。

## 2. 既存のショップカード表示の仕組み（参考）

### アーキテクチャ
```
concierge.astro
├── chat-section（左）
│   └── Concierge.astro → chatArea（チャット吹き出し）
└── shop-list-section（右 / モバイルは下）  ← ★ここにカードが表示される
    └── ShopCardList.astro → shopCardList（カード一覧）
```

### 表示フロー
1. バックエンドが `shop_search_result` Socket.IOイベントでショップデータを送信
2. `core-controller.ts` が `displayShops` カスタムイベントをdispatch
3. `ShopCardList.astro` 内のスクリプトがイベントを受信
4. `ShopCardListManager.displayShops()` がカードHTMLを生成して `#shopCardList` に挿入

### ポイント
- カードは **chatArea（チャット吹き出し）の外** に表示される
- カードは **専用のコンテナ（#shopCardList）** に挿入される
- カードのCSS は ShopCardList.astro のscoped CSSで管理
- chatAreaの `white-space: pre-wrap` 等のCSSの影響を受けない

## 3. メニューカード表示の設計

### 方針
**既存のShopCardListと同じパターンを使う。** chatAreaへの直接挿入は行わない。

### アーキテクチャ
```
concierge.astro
├── chat-section（左）
│   └── Concierge.astro → chatArea（チャット吹き出し）
└── shop-list-section（右 / モバイルは下）  ← ★メニューカードもここに表示
    └── ShopCardList.astro → shopCardList（メニューカード一覧に転用）
```

### 表示フロー
1. バックエンドが `menu_recommend` Socket.IOイベントでメニューデータを送信
2. `core-controller.ts` が `displayMenuItems` カスタムイベントをdispatch
3. `ShopCardList.astro` 内のスクリプトがイベントを受信（既存の `displayShops` と別ハンドラ）
4. メニューカードHTMLを生成して `#shopCardList` に挿入

### メニューカードのHTML構造（ShopCardList.astro内で生成）
```html
<div class="shop-card menu-item-card">
  <div class="hero-image">
    <img src="https://xxx.supabase.co/storage/v1/object/public/menu/dennys/pageN_imgM.jpg" />
  </div>
  <div class="shop-card-body">
    <div class="shop-card-title">和風ハンバーグ</div>
    <div class="shop-card-price">¥935</div>
    <div class="shop-card-description">40余年こだわりを重ねた醤油風味のソース</div>
  </div>
</div>
```

### CSSの管理
- 既存の `.shop-card` CSSをベースに使用（角丸、影、ホバー効果等）
- メニュー固有のスタイルは `.menu-item-card` で追加
- **chatAreaのCSS（white-space: pre-wrap等）の影響を受けない**（別コンテナのため）

## 4. データフロー

### バックエンド → フロントエンド

`menu_recommend` Socket.IOイベント:
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

### フロントエンド内のイベント連鎖

```
socket.on('menu_recommend') → core-controller.ts
  ↓ document.dispatchEvent(new CustomEvent('displayMenuItems', { detail: { items } }))
ShopCardList.astro のスクリプト
  ↓ document.addEventListener('displayMenuItems', ...)
  ↓ ShopCardListManager.displayMenuItems(items)
  ↓ #shopCardList に メニューカードHTMLを挿入
```

## 5. 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `src/scripts/chat/core-controller.ts` | `menu_recommend` リスナーで `displayMenuItems` カスタムイベントをdispatch |
| `src/components/ShopCardList.astro` | `displayMenuItems` ハンドラとメニューカード生成メソッドを追加 |
| `src/pages/concierge.astro` | ショップリストのヘッダーテキストを「おすすめメニュー」に変更 |

## 6. 変更しないもの

- `chatArea` へのHTML直接挿入は **行わない**
- 既存の `displayShops` / ショップカード機能は維持
- `live_api_handler.py` のFunction Calling部分は変更なし（既に動作確認済み）
