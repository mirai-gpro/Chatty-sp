# コンシェルジュモード刷新 → 注文サポートモード 修正仕様書

## 1. 概要

既存の「AIコンシェルジュ」モード（グルメ店舗検索）を「注文サポートAI」モードに刷新する。
大手ファミレス・ファーストフード店のメニューからユーザーが注文を決めるまでをサポートするプロトタイプ。

### ゴール
- ユーザーとの対話で食べたいもの・飲みたいものを一緒に決める
- メニュー項目をカード形式で表示して提案する
- 仮確定した注文を一覧表示（合計金額入り）
- 将来的にはAPI経由でショップ側システムに注文を送信（現段階ではスコープ外）

### 初期対応店舗
- **デニーズ**（最初の動作確認用）
- **KFC**（デニーズ確認後に追加）
- 店舗切り替えはプルダウンメニューで行う

---

## 2. UI変更

### 2.1 タイトル・サブタイトル

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| タイトル | AIコンシェルジュ | 注文サポートAI |
| サブタイトル | おもてなしの心でお店探しをサポート | 食べたいものをメニューから選ぶお手伝い！ |

#### 変更ファイル
- `src/pages/concierge.astro` L212-214: タイトル・サブタイトル変更
- `src/constants/i18n.ts`: `pageTitleConcierge` → `注文サポートAI`、`pageSubtitleConcierge`(新規) 追加
- `src/scripts/chat/concierge-controller.ts`: `updateUILanguage()` でサブタイトルも上書き

### 2.2 店舗選択プルダウン

`src/components/Concierge.astro` のヘッダーエリアに店舗選択プルダウンを追加:

```html
<div class="shop-selector">
  <select id="shopSelect" class="shop-dropdown">
    <option value="dennys">デニーズ</option>
    <option value="kfc">KFC</option>
  </select>
</div>
```

#### 変更ファイル
- `src/components/Concierge.astro`: ヘッダーにプルダウン追加 + CSS
- `src/scripts/chat/concierge-controller.ts`: プルダウン変更時にセッションリセット + 選択店舗をバックエンドに送信

### 2.3 予約ボタン → 注文確認ボタン

既存の「📞 予約依頼」ボタンを「📋 注文を確認」ボタンに変更。
タップで現在の仮注文一覧（メニュー名・個数・金額・合計）を表示。

#### 変更ファイル
- `src/components/Concierge.astro` L73-75: ボタンテキスト変更
- `src/scripts/chat/concierge-controller.ts`: タップ時の処理を注文一覧表示に変更

### 2.4 ショップカード → メニューカード

既存のShopCardList（店舗情報カード）をメニューアイテム表示用にカスタマイズ。

#### メニューカードの表示項目
- メニュー画像（PDFから抽出）
- メニュー名
- 価格（税込）
- カテゴリ（グランドメニュー、デザート等）
- 簡単な説明
- 「追加」ボタン（タップで仮注文に追加）

#### 変更ファイル
- `src/components/ShopCardList.astro`: カードテンプレートをメニュー表示用に調整（または新コンポーネント作成）
- `src/pages/concierge.astro`: ショップリストのヘッダーテキスト変更

### 2.5 注文一覧パネル

仮確定した注文の一覧を表示するパネル（モーダル or サイドパネル）。

#### 表示内容
- メニュー名 × 個数
- 各品の金額（小計）
- 合計金額
- 「注文を確定する」ボタン（将来のAPI連携用、現段階はダミー）
- 個別削除・数量変更

#### 変更ファイル
- 新規コンポーネント `src/components/OrderSummary.astro` を作成（既存ReservationModalをベースに）
- `src/scripts/chat/concierge-controller.ts`: 注文データの管理ロジック

---

## 3. バックエンド変更

### 3.1 新規プロンプトファイル

`chatty-base/prompts/order_support_ja.txt` を新規作成。

#### プロンプト内容の方針
- あなたは注文サポートAIです。ユーザーが{shop_name}のメニューから食べたいものを選ぶお手伝いをします
- メニューデータ（JSON）をコンテキストとして持つ
- ユーザーの好みを聞いて、メニューからおすすめを提案する
- 提案時はメニュー名・価格・説明を含める
- ユーザーが「これにする」と言ったら仮注文リストに追加
- 「注文を見せて」と言われたら現在の仮注文一覧を表示
- セットメニューやお得な組み合わせも提案する
- 音声応答ルール（50文字以内等）は既存と同じ

### 3.2 メニューデータ管理

公式PDFからメニューデータを抽出し、JSON形式で管理。

#### ファイル構成
```
chatty-base/
  menu_data/
    dennys/
      menu.json        ← メニューデータ（名前、価格、カテゴリ、説明）
      images/           ← メニュー画像（PDFから抽出）
    kfc/
      menu.json
      images/
```

#### menu.json フォーマット
```json
{
  "shop_name": "デニーズ",
  "last_updated": "2026-03-30",
  "categories": [
    {
      "name": "ハンバーグ",
      "items": [
        {
          "id": "d001",
          "name": "とろ〜り卵とチーズのハンバーグ",
          "price": 990,
          "tax_included": true,
          "description": "とろとろの半熟卵とチーズソースのハンバーグ",
          "image": "dennys/images/d001.jpg",
          "calories": 650,
          "allergens": ["卵", "乳", "小麦"],
          "is_set_available": true,
          "set_price": 1290
        }
      ]
    }
  ]
}
```

### 3.3 プロンプト読み込みパス変更

`support_core.py` のプロンプト読み込みで、conciergeモード用を `order_support_{lang}.txt` に変更。

#### 変更ファイル
- `chatty-base/support_core.py`: GCS/ローカル読み込みパスを変更

### 3.4 メニューデータのコンテキスト注入

`live_api_handler.py` の `build_system_instruction()` で、conciergeモード時にメニューデータJSONをプロンプトに注入。

#### 変更ファイル
- `chatty-base/live_api_handler.py`: conciergeモードの処理を修正

### 3.5 注文管理（Function Calling）

既存の `search_shops` Function Callingを、注文管理用に置き換え or 追加:

- `add_to_order(item_id, quantity)` — 仮注文に追加
- `remove_from_order(item_id)` — 仮注文から削除
- `show_order_summary()` — 現在の注文一覧を返す
- `recommend_menu(preference)` — メニューからおすすめを返す

---

## 4. フロントエンド → バックエンド 連携

### 4.1 店舗選択の送信

```
socket.emit('live_start', {
  session_id, mode: 'concierge', language,
  shop_id: 'dennys'  ← 新規追加
})
```

### 4.2 注文データの同期

Function Callingの結果としてバックエンドから注文データが返される:

```
socket.emit('order_updated', {
  items: [...],
  total_price: 2580
})
```

フロントはこれを受けて注文一覧パネルとメニューカードを更新。

---

## 5. 変更対象ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| `src/pages/concierge.astro` | タイトル・サブタイトル変更 |
| `src/components/Concierge.astro` | 店舗プルダウン追加、予約ボタン→注文確認ボタン |
| `src/constants/i18n.ts` | `pageTitleConcierge`等の変更、`pageSubtitleConcierge`追加 |
| `src/scripts/chat/concierge-controller.ts` | サブタイトル上書き、店舗選択、注文管理ロジック |
| `src/components/ShopCardList.astro` | メニューカード表示用にカスタマイズ |
| `src/components/OrderSummary.astro` | 新規: 注文一覧パネル |
| `chatty-base/prompts/order_support_ja.txt` | 新規: 注文サポート用プロンプト |
| `chatty-base/menu_data/dennys/menu.json` | 新規: デニーズメニューデータ |
| `chatty-base/support_core.py` | プロンプト読み込みパス変更 |
| `chatty-base/live_api_handler.py` | メニューデータ注入、Function Calling変更 |
| `chatty-base/app_customer_support.py` | order_updatedイベント等追加 |

---

## 6. 実装順序

### Phase 1: UI変更 + プロンプト（最小動作確認）
1. タイトル・サブタイトル変更（concierge.astro, i18n.ts, concierge-controller.ts）
2. 店舗選択プルダウン追加（Concierge.astro）
3. `order_support_ja.txt` 作成
4. `support_core.py` のプロンプトパス変更
5. デプロイ＆動作確認（AIがメニュー相談に応じるか）

### Phase 2: メニューデータ + カード表示
6. デニーズPDFからメニューデータ抽出 → menu.json作成
7. メニューデータをプロンプトのコンテキストに注入
8. ShopCardListをメニューカード表示にカスタマイズ
9. デプロイ＆動作確認

### Phase 3: 注文管理
10. Function Calling定義（add_to_order等）
11. 注文一覧パネル（OrderSummary.astro）
12. 注文確認ボタンの接続
13. デプロイ＆動作確認

---

## 7. 変更しないもの

- Chatty AIモード（lesson）— 影響なし
- chatモード — 影響なし
- A2Eリップシンク — 既存のまま動作
- 長期記憶 — 既存のまま動作
- LiveAPI基盤 — 既存のまま利用
