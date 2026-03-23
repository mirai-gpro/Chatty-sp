# 会話レッスン・モード 要件定義・変更仕様書

## 文書情報
- 作成日: 2026-03-23
- ステータス: ドラフト（ユーザー承認待ち）
- 対象リポジトリ: Travel-sp

---

## 1. 概要

グルメサポートAIアプリを**トラベルサポートAI**へ進化させる。
グルメモード（chatモード）を廃止し、新たに**会話レッスン・モード**を新設する。

### 1.1 モード構成の変更

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| モード1 | `chat`（グルメモード） | `lesson`（会話レッスン・モード） |
| モード2 | `concierge`（コンシェルジュモード） | `concierge`（コンシェルジュモード）※そのまま |
| デフォルト | グルメモード（`/`） | 会話レッスン・モード（`/`） |
| アプリ名 | グルメサポートAI | Travel AI |

### 1.2 会話レッスン・モードの基本情報

| 項目 | 値 |
|------|-----|
| タイトル（日本語） | 会話レッスンAI |
| タイトル（英語） | Conversation Practice AI |
| モード識別子 | `lesson` |
| デフォルトルート | `/`（アプリ起動時のデフォルト） |
| 対象言語（初期テスト） | 英語のみ |
| 将来対応予定 | プルダウンから相手先言語を選択（多言語） |

---

## 2. 要件定義

### 2.1 機能要件

#### A) フレーズレッスン機能（メイン）

**ユースケース：**
ユーザーが「ホテルのチェックインで何と言えばいいですか？」のように日本語で質問。

**フロー：**
1. ユーザーが日本語で場面・状況を説明
2. AIが英語のフレーズをテキスト表示 + 音声で発話
3. ユーザーが復唱（マイクボタン）
4. AIが発音・内容を評価
   - 通用するレベル → 褒める
   - 間違い → ゆっくり再度発話して再挑戦を促す
5. AIが「よければ、私相手に会話を試してみませんか？」と誘い、数ターンのロールプレイ会話を実施

#### B) 実戦サポート機能

**ユースケース：**
旅行先で実際に英語で話しかけられた場面。

**フロー：**
1. ユーザーがマイクボタンを押す
2. 相手の英語をAIが聞き取り
3. 内容を日本語でユーザーに伝える
4. ユーザーが返答内容を日本語で指示
5. AIが英語で相手に返答を発話

#### C) フリー会話機能

**ユースケース：**
英語で自由に会話のキャッチボールをして練習。

**フロー：**
1. ユーザーが英語で自由に話す
2. AIが英語で返答
3. 分からない部分があればユーザーが日本語で質問可能
4. AIが解説・翻訳してくれる

### 2.2 非機能要件

- 既存のLiveAPI音声対話基盤をそのまま活用
- コンシェルジュモードのアバター・A2Eリップシンクは変更なし
- 多言語UIの仕組み（i18n）はそのまま引き継ぎ
- ショップ検索（search_shops）機能は会話レッスン・モードでは不要

---

## 3. 変更仕様

### 3.1 フロントエンド変更

#### 3.1.1 ページ構成

| ファイル | 変更内容 |
|----------|----------|
| `src/pages/index.astro` | グルメモード → 会話レッスン・モードに変更 |
| `src/pages/concierge.astro` | 変更なし |
| `src/pages/chat.astro` | 廃止 or リダイレクト |

#### 3.1.2 コンポーネント

| ファイル | 変更内容 |
|----------|----------|
| `src/components/GourmetChat.astro` | `LessonChat.astro` にリネーム。UI をレッスン用に変更 |
| `src/components/ShopCardList.astro` | 会話レッスン・モードでは非表示（コンシェルジュモードでは継続使用） |
| `src/components/ReservationModal.astro` | 会話レッスン・モードでは非表示 |

#### 3.1.3 コントローラ

| ファイル | 変更内容 |
|----------|----------|
| `src/scripts/chat/chat-controller.ts` | `lesson-controller.ts` にリネーム。`currentMode = 'lesson'` |
| `src/scripts/chat/core-controller.ts` | モード型定義に `'lesson'` 追加。shop系UIの条件分岐追加 |
| `src/scripts/chat/concierge-controller.ts` | 変更なし |

#### 3.1.4 i18n（`src/constants/i18n.ts`）

**各言語に追加するキー：**
```typescript
pageTitle: '会話レッスンAI',          // ja
pageTitleLesson: '会話レッスンAI',    // ja
// en: 'Conversation Practice AI'
// zh: '会话练习AI'
// ko: '회화 연습 AI'

initialGreetingLesson: 'こんにちは！会話レッスンAIです。...'

// 相手先言語選択ラベル
targetLanguageLabel: '相手先言語',
```

#### 3.1.5 言語選択UI

- 既存の言語選択（UI表示言語）はそのまま
- **追加**: 相手先言語プルダウン（会話レッスン・モード専用）
  - 初期テストフェーズ: 英語のみ（プルダウンは表示するが選択肢は英語固定）
  - 将来: 多言語選択可能

#### 3.1.6 UI変更（会話レッスン・モード）

- ヘッダー: 「会話レッスンAI」タイトル表示
- カラーテーマ: 新規（グルメの紫系とは別の色。例: グリーン系 `#10b981` ～ `#059669`）
- ShopCardList: 非表示
- 予約ボタン: 非表示
- モード切替トグル: 「Concierge」ラベルはそのまま

### 3.2 バックエンド変更

#### 3.2.1 セッション管理（`support_core.py`）

- `mode` の許容値に `'lesson'` を追加
- `lesson` モード時のプロンプト読み込みロジック追加
- `lesson` モード時は `search_shops` ツールを無効化
- 初期メッセージを会話レッスン用に変更

#### 3.2.2 LiveAPI（`live_api_handler.py`）

- `lesson` モード用のシステムプロンプト構築ロジック追加
- `search_shops` function declaration を `lesson` モードでは除外
- 音声言語設定:
  - ユーザー側: `ja-JP`（日本語で指示）
  - AI発話: 状況に応じて `en-US`（英語フレーズ発話時）と `ja-JP`（解説時）を使い分け
  - ※ LiveAPIの言語切替仕様を要確認（制約あり得る）

#### 3.2.3 プロンプトファイル

**既存プロンプト: そのまま残す（変更・削除しない）**
- `prompts/concierge_ja.txt` — コンシェルジュモード用（継続使用）
- `prompts/support_system_ja.txt` — 旧グルメモード用（残置）
- `prompts/support_system_en.txt` — 同上
- `prompts/support_system_zh.txt` — 同上
- `prompts/support_system_ko.txt` — 同上

**新規追加: `prompts/lesson_ja.txt`**（GCS管理対象）

プロンプト骨子：
```
あなたは、ユーザーの英会話の先生です。

【基本動作】
- ユーザーからは日本語で「〇〇の場合は何と言えばいいですか？」と聞かれます
- そのフレーズを英語のテキストで画面に表示し、音声で発話してください
- ユーザーに復唱させてください
- 英語として通用するレベルであれば、褒めてください
- 間違っていれば、もう一度ゆっくり話してください

【フレーズレッスン】
- 様々な旅行場面（ホテル、レストラン、空港、ショッピング等）に対応
- フレーズ提示後「よければ、私相手に会話を試してみませんか？」と誘う
- 数ターンのロールプレイ会話を実施

【実戦サポート】
- ユーザーが「実戦モード」と言ったら、相手の英語を聞き取って日本語で伝える
- ユーザーの日本語の返答を英語に変換して発話する

【フリー会話】
- ユーザーが「フリー会話」と言ったら、英語で自由に会話する
- ユーザーが分からない部分を日本語で聞いたら、解説する

【制約】
- 50文字以内で簡潔に話す（音声出力のため）
- Markdownは使わない
```

#### 3.2.4 メインアプリ（`app_customer_support.py`）

- CORS設定: 変更なし（`travel-sp.vercel.app` は追加済み）
- セッション開始時に `mode='lesson'` を受け付け

### 3.3 PWA / 設定ファイル変更

| ファイル | 変更内容 |
|----------|----------|
| `public/manifest.webmanifest` | 確認（既に `Travel AI` に変更済み） |
| `astro.config.mjs` | PWA名を `Travel AI` に変更 |
| `package.json` | `name` を `travel-support` に変更 |
| `src/layouts/Layout.astro` | `<title>` を動的に設定（各ページで上書き） |

---

## 4. 改修プラン（フェーズ分割）

### Phase 1: 基盤変更（名称・モード定義）
**優先度: 高 ｜ 想定作業: 小**

1. `package.json` の `name` を変更
2. `astro.config.mjs` のPWA名を変更
3. `core-controller.ts` のモード型定義に `'lesson'` 追加
4. i18n に会話レッスン・モード用のキーを追加

### Phase 2: フロントエンド - 会話レッスン・モードUI
**優先度: 高 ｜ 想定作業: 中**

1. `GourmetChat.astro` → `LessonChat.astro` にリネーム・改修
   - ShopCardList、ReservationModal を非表示
   - カラーテーマ変更
   - 相手先言語プルダウン追加（英語固定）
2. `chat-controller.ts` → `lesson-controller.ts` にリネーム
   - `currentMode = 'lesson'` に変更
3. `index.astro` を会話レッスン・モードに切り替え
4. `chat.astro` を廃止 or リダイレクト

### Phase 3: バックエンド - プロンプト・ロジック
**優先度: 高 ｜ 想定作業: 中**

1. `prompts/lesson_ja.txt` を新規作成
2. `support_core.py` に `lesson` モード対応を追加
3. `live_api_handler.py` に `lesson` モード対応を追加
   - システムプロンプト構築
   - function calling 除外
4. `app_customer_support.py` でのモード受付確認

### Phase 4: 統合テスト
**優先度: 高 ｜ 想定作業: 小**

1. 会話レッスン・モードの基本フロー動作確認
2. コンシェルジュモードが影響を受けていないことの確認
3. モード切替の動作確認
4. LiveAPI音声対話の動作確認

---

## 5. 未決事項・要確認

### 5.1 LiveAPIの言語切替

- 会話レッスン・モードでは、AIが日本語（解説）と英語（フレーズ発話）を切り替える必要がある
- LiveAPIの `speech_config.language_codes` で複数言語を指定可能か要確認
- 制約がある場合の代替案を検討する必要あり

### 5.2 ユーザー発話の評価

- ユーザーの英語復唱をLiveAPIのSTTで文字起こしし、AIが評価する設計
- STTの認識精度が発音評価にどの程度使えるか、実証テストで確認

### 5.3 実戦サポートモードのトリガー

- 「実戦モード」等のキーワードでサブモード切替するか
- UIにサブモード切替ボタンを設けるか
- → 初期テストではプロンプトベース（ユーザーの発言で切替）が妥当

### 5.4 コンシェルジュモードの将来

- コンシェルジュモードは「グルメ」のまま残すか、将来的に「旅行」向けに変更するか
- → 初期テストフェーズでは現状維持

### 5.5 A2Eアバターの適用

- 会話レッスン・モードでもアバターを使うか
- → 初期テストフェーズではアバターなし（コンシェルジュモードのみ）

---

## 6. 影響範囲

### 変更するファイル

| ファイル | 変更種別 |
|----------|----------|
| `package.json` | 名称変更 |
| `astro.config.mjs` | PWA名変更 |
| `src/pages/index.astro` | コンポーネント差し替え |
| `src/pages/chat.astro` | 廃止 or リダイレクト |
| `src/components/GourmetChat.astro` | リネーム → `LessonChat.astro` + UI変更 |
| `src/scripts/chat/chat-controller.ts` | リネーム → `lesson-controller.ts` + ロジック変更 |
| `src/scripts/chat/core-controller.ts` | モード型定義追加 |
| `src/constants/i18n.ts` | レッスン・モード用キー追加 |
| `support-base/support_core.py` | lessonモード対応追加 |
| `support-base/live_api_handler.py` | lessonモード対応追加 |
| `support-base/prompts/lesson_ja.txt` | 新規作成 |

### 変更しないファイル

| ファイル | 理由 |
|----------|------|
| `src/pages/concierge.astro` | コンシェルジュモードは変更なし |
| `src/components/Concierge.astro` | 同上 |
| `src/scripts/chat/concierge-controller.ts` | 同上 |
| `src/scripts/chat/live-audio-manager.ts` | 音声基盤は共通利用 |
| `src/scripts/chat/audio-manager.ts` | 同上 |
| `src/components/LAMAvatar.astro` | アバターは変更なし |
| `support-base/api_integrations.py` | 外部API連携は変更なし |
| `support-base/long_term_memory.py` | 長期記憶は変更なし |
| `CLAUDE.md` | 変更禁止 |
| `docs/` 配下の既存ファイル | 変更禁止 |
| `.github/workflows/` | CI/CDは変更なし |
