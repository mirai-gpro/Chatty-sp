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

### 2.1 タイトル・サブタイトル（実装済み）

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| タイトル | AIコンシェルジュ | 注文サポートAI |
| サブタイトル | おもてなしの心でお店探しをサポート | 食べたいものをメニューから選ぶお手伝い！ |

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

### 2.3 予約ボタン → 注文確認ボタン

既存の「📞 予約依頼」ボタンを「📋 注文を確認」ボタンに変更。
タップで現在の仮注文一覧（メニュー名・個数・金額・合計）を表示。

### 2.4 メニューカード表示（Markdown → カード変換）

LLMが出力するMarkdownをフロントエンドでカードコンポーネントに変換して表示。

#### LLMが出力するMarkdownの例
```markdown
### 🍗 鶏竜田バーガー香味ネギ
**価格:** ¥540
**特徴:** サクッと食感、シャキシャキのネギと香味ソースが絶妙

![鶏竜田バーガー香味ネギ](https://bisguyfngvlpcgagrdmr.supabase.co/storage/v1/object/public/menu/kfc/page3_img0.jpg)

> **おすすめポイント:** ガッツリいきたいなら、この香味ネギのパンチが最高ですよ！
```

#### フロントでの変換
- `react-markdown`等のライブラリでMarkdownをパース
- `###` → カードタイトル、`![image]` → カード画像、`**価格:**` → 価格表示
- Tailwind CSS等でカード風に装飾

### 2.5 注文一覧パネル

仮確定した注文の一覧を表示するパネル（モーダル or サイドパネル）。

#### 表示内容
- メニュー名 × 個数
- 各品の金額（小計）
- 合計金額
- 「注文を確定する」ボタン（将来のAPI連携用、現段階はダミー）
- 個別削除・数量変更

---

## 3. データアーキテクチャ（Markdown統一方式）

### 3.1 設計思想

全てのメニューデータをMarkdown形式で統一管理する。

| 役割 | 形式 | 理由 |
|------|------|------|
| データの保持 | Markdown | LLMとの相性が最も良い。検索・フィルタもMarkdown内で可能 |
| LLMへの注入 | Markdown | LLMが構造を最も正確に把握できる |
| LLMの出力 | Markdown | 「見せ方」を自由にコントロールでき、カード変換が容易 |
| フロント表示 | Markdown → カード | react-markdown等でコンポーネントに自動変換 |

**JSON / Supabase DBは不要。** Markdownファイルが唯一のデータソース。

### 3.2 メニューデータの生成フロー

```
公式PDF（27MB）
  ↓ extract_menu.py（Gemini API + pdfplumber）
  ↓
  ├─ 画像抽出 → Supabase Storage（menuバケット）にアップロード
  │   └─ 公開URL取得: https://xxx.supabase.co/storage/v1/object/public/menu/dennys/page5_img0.jpg
  │
  └─ Gemini APIでカテゴリごとにMarkdown生成（画像URL埋め込み）
      └─ menu_data/dennys/dennys_menu.md
          └─ GitHub push → GCSにもアップロード
```

### 3.3 画像管理: Supabase Storage

- バケット名: `menu`（Public）
- パス: `{shop_id}/page{N}_img{M}.jpg`
- 公開URL: `{SUPABASE_URL}/storage/v1/object/public/menu/{shop_id}/page{N}_img{M}.jpg`

#### Supabase Storageを選ぶ理由
- GCSより設定がシンプル（IAM不要）
- 既存のSupabaseプロジェクトをそのまま使える
- 公開URL生成が簡単（`getPublicUrl()`）
- 無料枠で十分（1GB保存、2GB/月転送）
- 将来的にProプランの画像リサイズ機能も活用可能

### 3.4 Markdownファイルの構成

```
chatty-base/
  menu_data/
    dennys/
      dennys_menu.md    ← メニューデータ（Markdown形式、画像URL埋め込み）
      menu.pdf          ← 原本PDF（GitHubにはpushしない、GCSに配置）
    kfc/
      kfc_menu.md
      menu.pdf
  extract_menu.py       ← PDF → Markdown変換スクリプト
```

### 3.5 dennys_menu.md のフォーマット

```markdown
# デニーズ メニュー

## モーニングメニュー

### セレクトモーニング
![セレクトモーニング](https://xxx.supabase.co/storage/v1/object/public/menu/dennys/page2_img0.jpg)
**価格:** ¥748
**メニュー番号:** 01701
**説明:** メインとセットメニューを選べるモーニングセット
**販売時間:** 開店〜11:00

---

### おろしハンバーグ朝食
![おろしハンバーグ朝食](https://xxx.supabase.co/storage/v1/object/public/menu/dennys/page6_img0.jpg)
**価格:** ¥1,078
**メニュー番号:** 01715
**説明:** ふっくらジューシーなおろしハンバーグを定食スタイルで
**ドリンクバー付き:** ¥1,256
**販売時間:** 開店〜11:00

---

## ハンバーグ

### 和風ハンバーグ
...
```

---

## 4. バックエンド変更

### 4.1 新規プロンプトファイル（実装済み）

`chatty-base/prompts/order_support_ja.txt`

### 4.2 プロンプト読み込みパス変更（実装済み）

`support_core.py` のconciergeモード用を `order_support_{lang}.txt` に変更済み。

### 4.3 メニューMarkdownのコンテキスト注入

`live_api_handler.py` の `build_system_instruction()` で、conciergeモード時にMarkdownメニューデータをプロンプトに注入。

- GCSまたはローカルから `{shop_id}_menu.md` を読み込み
- システムプロンプトの `{menu_data}` プレースホルダに埋め込み

### 4.4 注文管理（Function Calling）

既存の `search_shops` Function Callingを、注文管理用に置き換え or 追加:

- `add_to_order(item_name, quantity)` — 仮注文に追加
- `remove_from_order(item_name)` — 仮注文から削除
- `show_order_summary()` — 現在の注文一覧を返す

---

## 5. フロントエンド → バックエンド 連携

### 5.1 店舗選択の送信

```
socket.emit('live_start', {
  session_id, mode: 'concierge', language,
  shop_id: 'dennys'  ← 新規追加
})
```

### 5.2 注文データの同期

Function Callingの結果としてバックエンドから注文データが返される:

```
socket.emit('order_updated', {
  items: [...],
  total_price: 2580
})
```

フロントはこれを受けて注文一覧パネルとメニューカードを更新。

---

## 6. 変更対象ファイル一覧

| ファイル | 変更内容 | 状態 |
|---------|---------|------|
| `src/pages/concierge.astro` | タイトル・サブタイトル変更 | ✅ 完了 |
| `src/constants/i18n.ts` | pageTitleConcierge等の変更 | ✅ 完了 |
| `src/scripts/chat/concierge-controller.ts` | サブタイトル上書き | ✅ 完了 |
| `chatty-base/prompts/order_support_ja.txt` | 注文サポート用プロンプト | ✅ 完了 |
| `chatty-base/support_core.py` | プロンプト読み込みパス変更 | ✅ 完了 |
| `chatty-base/extract_menu.py` | PDF→Markdown+画像抽出スクリプト | ✅ 完了 |
| `src/components/Concierge.astro` | 店舗プルダウン追加、注文確認ボタン | 未着手 |
| `src/components/ShopCardList.astro` | Markdown→メニューカード変換 | 未着手 |
| `src/components/OrderSummary.astro` | 新規: 注文一覧パネル | 未着手 |
| `chatty-base/live_api_handler.py` | メニューMarkdown注入 | 未着手 |
| `chatty-base/app_customer_support.py` | order_updatedイベント追加 | 未着手 |

---

## 7. 実装順序

### Phase 1: UI変更 + プロンプト ✅ 完了
1. タイトル・サブタイトル変更
2. `order_support_ja.txt` 作成
3. `support_core.py` のプロンプトパス変更

### Phase 2: メニューデータ生成 + 画像管理（進行中）
4. Supabase Storage `menu`バケット作成 ✅ 完了
5. `extract_menu.py` 作成（PDF→画像抽出→Supabase Storage + Gemini→Markdown生成） ✅ 完了
6. デニーズPDFで実行 → `dennys_menu.md` 生成 → GCSにもアップ
7. メニューMarkdownをLiveAPIコンテキストに注入
8. フロントでMarkdown→メニューカード変換
9. デプロイ＆動作確認

### Phase 3: 注文管理
10. Function Calling定義（add_to_order等）
11. 注文一覧パネル（OrderSummary.astro）
12. 注文確認ボタンの接続
13. デプロイ＆動作確認

---

## 8. 変更しないもの

- Chatty AIモード（lesson）— 影響なし
- chatモード — 影響なし
- A2Eリップシンク — 既存のまま動作
- 長期記憶 — 既存のまま動作
- LiveAPI基盤 — 既存のまま利用

---

## 9. 技術選定の根拠

### なぜJSONではなくMarkdownか
- LLMのネイティブ言語であり、生成精度が最も高い
- Astroが標準でMarkdownパースをサポート
- データ保持・LLM注入・LLM出力・フロント表示の全てをMarkdown統一で管理できる
- 表形式、太字、リスト等を正確に出力でき、カードレイアウトが崩れにくい
- 派生店舗追加時もMarkdownファイルを1つ追加するだけ

### なぜSupabase Storageか（画像管理）
- 既存のSupabaseプロジェクトをそのまま利用可能
- GCSより設定がシンプル（IAM設定不要）
- Public Bucketで公開URL生成が簡単
- 無料枠（1GB保存、2GB/月転送）でプロトタイプに十分
- 将来的にProプランの画像リサイズ機能（Smart Crop、WebP変換）も活用可能

### なぜSupabase DBは使わないか
- Markdown1ファイルでデータ保持・LLM注入・表示の全てをカバーできる
- DBに分散させるとデータの整合性管理が発生する
- プロトタイプ段階では管理コストを最小化する
