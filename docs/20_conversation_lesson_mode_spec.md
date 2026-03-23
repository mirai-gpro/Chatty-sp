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

#### D) 名前・パーソナライゼーション

**AI講師の名前：**
- デフォルト名: **Emma**（英会話講師として自然で覚えやすい名前）
- ユーザーが「名前を変えて」「○○と呼ばせて」等と言えば変更可能
- 変更後の名前は長期記憶（Supabase）に保存し、次回セッションから反映

**ユーザーの名前：**
- 初回セッションで「お名前を教えてください」と聞く
- 長期記憶に保存し、以降「○○さん、いい発音ですね！」のように呼びかける
- コンシェルジュモードと同じ長期記憶テーブルを共用（ユーザー名はモード共通）

**長期記憶で管理する項目（会話レッスン・モード）：**

| キー | 内容 | デフォルト |
|------|------|-----------|
| `user_name` | ユーザーの名前 | なし（初回に聞く） |
| `lesson_teacher_name` | AI講師の名前 | `Emma` |
| ※将来追加 | 学習履歴、苦手分野等 | — |

### 2.2 非機能要件

- **コンシェルジュモードをベースに移植**（アバター + A2Eリップシンク搭載）
- 既存のLiveAPI音声対話基盤をそのまま活用
- LAMAvatar（Gaussian Splatting 3D アバター）+ A2Eリップシンクを会話レッスン・モードでも使用
- **長期記憶（Supabase）を活用**: ユーザー名、AI講師名の記憶・呼びかけ
- 多言語UIの仕組み（i18n）はそのまま引き継ぎ
- ショップ検索（search_shops）機能は会話レッスン・モードでは不要

---

## 3. 変更仕様

### 3.1 フロントエンド変更

#### 3.1.0 設計方針: コンシェルジュモードからの移植

会話レッスン・モードは**コンシェルジュモード（`concierge-controller.ts` + `Concierge.astro`）をベースに移植**する。
理由: アバター + A2Eリップシンクを搭載するため、同じ基盤が必要。

```
移植元:                          移植先:
concierge.astro            →    index.astro（lesson用ページ）
Concierge.astro            →    LessonChat.astro（lesson用コンポーネント）
concierge-controller.ts    →    lesson-controller.ts（lesson用コントローラ）
LAMAvatar.astro            →    そのまま共用
lam-websocket-manager.ts   →    そのまま共用
audio-sync-player.ts       →    そのまま共用
live-audio-manager.ts      →    そのまま共用
```

#### 3.1.1 ページ構成

| ファイル | 変更内容 |
|----------|----------|
| `src/pages/index.astro` | コンシェルジュモードのUI構成をベースに、会話レッスン・モードとして再構成（アバター搭載） |
| `src/pages/concierge.astro` | 変更なし |
| `src/pages/chat.astro` | 廃止 or リダイレクト |

#### 3.1.2 コンポーネント

| ファイル | 変更内容 |
|----------|----------|
| `src/components/Concierge.astro` | 変更なし（コンシェルジュモード用として維持） |
| `src/components/LessonChat.astro` | **新規作成**: `Concierge.astro` をベースに複製・改修 |
| `src/components/LAMAvatar.astro` | 変更なし（会話レッスン・モードでも共用） |
| `src/components/GourmetChat.astro` | 廃止（旧グルメモード用。参照がなくなれば削除） |
| `src/components/ShopCardList.astro` | 会話レッスン・モードでは非表示（コンシェルジュモードでは継続使用） |
| `src/components/ReservationModal.astro` | 会話レッスン・モードでは非表示（コンシェルジュモードでは継続使用） |

**`LessonChat.astro` での主な差分（vs `Concierge.astro`）：**
- ShopCardList、ReservationModal を除外
- 相手先言語プルダウンを追加（英語固定）
- カラーテーマ変更
- タイトル: 「会話レッスンAI」

#### 3.1.3 コントローラ

| ファイル | 変更内容 |
|----------|----------|
| `src/scripts/chat/lesson-controller.ts` | **新規作成**: `concierge-controller.ts` をベースに複製・改修 |
| `src/scripts/chat/core-controller.ts` | モード型定義に `'lesson'` 追加 |
| `src/scripts/chat/concierge-controller.ts` | 変更なし |
| `src/scripts/chat/chat-controller.ts` | 廃止（旧グルメモード用。参照がなくなれば削除） |

**`lesson-controller.ts` での主な差分（vs `concierge-controller.ts`）：**
- `this.currentMode = 'lesson'`
- アバター関連のロジック（`linkLamAvatar()`, `speakTextGCP()`, A2E連携）はそのまま継承
- ショップ検索・予約関連ロジックを除外
- `toggleMode()` でコンシェルジュモード（`/concierge`）への切替
- `updateUILanguage()` でタイトルを「会話レッスンAI」に設定

#### 3.1.4 i18n（`src/constants/i18n.ts`）

**各言語に追加するキー：**
```typescript
pageTitleLesson: '会話レッスンAI',    // ja
// en: 'Conversation Practice AI'
// zh: '会话练习AI'
// ko: '회화 연습 AI'

initialGreetingLesson: 'こんにちは！会話レッスンAIです。英語の会話練習をお手伝いします。...'

// 相手先言語選択ラベル
targetLanguageLabel: '相手先言語',     // ja
// en: 'Target language'
// zh: '目标语言'
// ko: '대상 언어'
```

#### 3.1.5 言語選択UI

- 既存の言語選択（UI表示言語）はそのまま
- **追加**: 相手先言語プルダウン（会話レッスン・モード専用）
  - 初期テストフェーズ: 英語のみ（プルダウンは表示するが選択肢は英語固定）
  - 将来: 多言語選択可能

#### 3.1.6 UI変更（会話レッスン・モード）

- ヘッダー: 「会話レッスンAI」タイトル表示
- **アバターステージ**: コンシェルジュモードと同様にLAMAvatarを表示
- カラーテーマ: 新規（コンシェルジュのシアン系とは別の色。例: グリーン系 `#10b981` ～ `#059669`）
- ShopCardList: 非表示
- 予約ボタン: 非表示
- モード切替トグル: 「Concierge」ラベルはそのまま

### 3.2 バックエンド変更

#### 3.2.1 セッション管理（`support_core.py`）

- `mode` の許容値に `'lesson'` を追加
- `lesson` モード時のプロンプト読み込みロジック追加
- `lesson` モード時は `search_shops` ツールを無効化
- `lesson` モード時は `save_user_preference` ツールを有効化（名前保存用）
- 初期メッセージを会話レッスン用に変更
- セッション開始時に長期記憶から `user_name`、`lesson_teacher_name` を取得し、プロンプトに埋め込む

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
あなたの名前は{teacher_name}です。ユーザーの英会話の先生です。
ユーザーの名前は{user_name}です。名前で呼びかけてください。

【自己紹介（初回セッション）】
- 「こんにちは！私は{teacher_name}です。英会話のレッスンを担当します。お名前を教えてください。」
- ユーザーが名前を教えてくれたら、save_user_preference で保存する
- 2回目以降のセッション: 「{user_name}さん、こんにちは！今日はどんな練習をしましょうか？」

【名前の変更】
- ユーザーが「名前を変えて」「○○って呼んで」等と言ったら、save_user_preference で保存する
- AI自身の名前変更も同様（「あなたの名前を○○にして」等）

【基本動作】
- ユーザーからは日本語で「〇〇の場合は何と言えばいいですか？」と聞かれます
- そのフレーズを英語のテキストで画面に表示し、音声で発話してください
- ユーザーに復唱させてください
- 英語として通用するレベルであれば、{user_name}さんの名前を使って褒めてください
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

### Phase 2: フロントエンド - 会話レッスン・モードUI（コンシェルジュから移植）
**優先度: 高 ｜ 想定作業: 中**

1. `Concierge.astro` をベースに `LessonChat.astro` を新規作成
   - アバターステージ（LAMAvatar）をそのまま搭載
   - ShopCardList、ReservationModal を除外
   - カラーテーマ変更（グリーン系）
   - 相手先言語プルダウン追加（英語固定）
2. `concierge-controller.ts` をベースに `lesson-controller.ts` を新規作成
   - `currentMode = 'lesson'`
   - アバター/A2E連携ロジックはそのまま継承
   - ショップ検索・予約ロジックを除外
3. `index.astro` を会話レッスン・モード（LessonChat + LAMAvatar）に切り替え
4. `chat.astro` を廃止 or リダイレクト
5. 旧 `GourmetChat.astro`、`chat-controller.ts` は参照がなくなれば削除

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

- 会話レッスン・モードでもアバター + A2Eリップシンクを搭載する（確定）
- コンシェルジュモードと同じ LAMAvatar + AudioSyncPlayer + LAMWebSocketManager を使用

---

## 6. 影響範囲

### 新規作成するファイル

| ファイル | 内容 |
|----------|------|
| `src/components/LessonChat.astro` | `Concierge.astro` をベースに複製・改修（アバター搭載） |
| `src/scripts/chat/lesson-controller.ts` | `concierge-controller.ts` をベースに複製・改修 |
| `support-base/prompts/lesson_ja.txt` | 会話レッスン・モード用プロンプト |

### 変更するファイル

| ファイル | 変更種別 |
|----------|----------|
| `package.json` | 名称変更 |
| `astro.config.mjs` | PWA名変更 |
| `src/pages/index.astro` | LessonChat + LAMAvatar に差し替え |
| `src/scripts/chat/core-controller.ts` | モード型定義に `'lesson'` 追加 |
| `src/constants/i18n.ts` | レッスン・モード用キー追加 |
| `support-base/support_core.py` | lessonモード対応追加 |
| `support-base/live_api_handler.py` | lessonモード対応追加 |

### 廃止するファイル

| ファイル | 理由 |
|----------|------|
| `src/pages/chat.astro` | 旧グルメモードのテストページ |
| `src/components/GourmetChat.astro` | 旧グルメモード用（LessonChat.astro に置き換え） |
| `src/scripts/chat/chat-controller.ts` | 旧グルメモード用（lesson-controller.ts に置き換え） |

### 変更しないファイル

| ファイル | 理由 |
|----------|------|
| `src/pages/concierge.astro` | コンシェルジュモードは変更なし |
| `src/components/Concierge.astro` | 同上（会話レッスンの移植元として残す） |
| `src/scripts/chat/concierge-controller.ts` | 同上（移植元として残す） |
| `src/components/LAMAvatar.astro` | アバターコンポーネントは共用（変更不要） |
| `src/scripts/chat/live-audio-manager.ts` | 音声・A2E基盤は共通利用 |
| `src/scripts/chat/audio-sync-player.ts` | アバター同期は共通利用 |
| `src/scripts/chat/lam-websocket-manager.ts` | GaussianSplatレンダラーは共通利用 |
| `src/scripts/chat/audio-manager.ts` | レガシー音声は共通利用 |
| `support-base/api_integrations.py` | 外部API連携は変更なし |
| `support-base/long_term_memory.py` | 長期記憶は変更なし |
| `CLAUDE.md` | 変更禁止 |
| `docs/` 配下の既存ファイル | 変更禁止 |
| `.github/workflows/` | CI/CDは変更なし |
