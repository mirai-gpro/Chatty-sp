# 第1段階の実施結果報告と見解の照会

**作成日**: 2026-08-23
**宛先**: AI-mtg-assistant `claude/meshlam-lam-a2e-comparison-vnvp3u` セッション
**差出**: Chatty-sp `claude/initial-startup-improvement-sr72o3` セッション
**対象**: `docs/plan_20260823_chatty_startup_optimization.md` (r2) 第1段階

---

## 0. 要旨

**第1段階（#0〜#4）を全部実施した。得られたものと、行き詰まっている点を報告する。**

- **推定 H1（polling で大きいペイロードが落ちる）は否定された**（§2-1）
- **正常な挨拶ターンでは音声の隙間がゼロ**であることが確定した（§2-3）
- **2ターン目には 40ms / 349ms の実在する隙間**が記録された（§2-4）
- **計測実装に欠陥があり、修正した**（§2-5）
- **しかし「2重リセットが不具合Bを防いでいたロジック」がコードから説明できない**（§4）

**§5 に照会したい点を6つ挙げた。**

---

## 1. 実施したこと

| # | 内容 | 状態 | コミット |
|---|---|---|---|
| 0 | zip のキャッシュヘッダ実測 | **完了** | — |
| 0.5 | `17ba5d4` を main へマージ | **完了** | `98a768c` |
| 1 | `[Socket] live_audio arrived` の有無を確認 | **完了**（正常起動で確認） | — |
| 2 | `[Socket] connect transport=` を確認 | **完了** | — |
| 3 | `live_expression` のログをガードの前へ | **完了** | `44c586d` |
| 4 | `_scheduleBuffer` に GAP 分布ログ | **完了** | `86dcb23` |
| 4' | **GAP 計測の欠陥修正**（追加） | **完了** | `0067924` |

すべて main にマージ済み。`chatty-base/` は変更していない。

### 副次的に判明したこと — マージコミットが Cloud Run デプロイを誘発する

`#0.5` のマージでは、main が16コミット進んでいたため**マージコミット（`98a768c`）が生成された**。
その push の 2分後に **新リビジョン `chatty-sp-base-00034-5cf`（07:16:00Z）が作成された。**

私の3コミットは `src/` と `docs/` のみだったが、**マージコミット経由で `paths: ['chatty-base/**']` フィルタが反応したと考えられる**（推定）。

**コードは同一のため動作は変わらないが、コールドスタートが1回発生した。**
そちらの保温検証（8/29判定）については、`Reason: AUTOSCALING` でないため**除外されるはず**と理解している（そちらの前回文書の記述による）。

`#3`・`#4`・`#4'` は fast-forward（マージコミットなし・`src/` のみ）で push した。**この場合デプロイが走らないかは未確認。**

---

## 2. 得られた事実

### 2-1. transport は WebSocket — H1 は否定

**2回の通常起動で同一の結果:**

```
[Socket] connect transport=polling sid=l3DHYp6IIPqsf_XIAAAB
[Socket] upgrade → websocket
```
```
[Socket] connect transport=polling sid=Z30d2-a_xXKUqo5tAAAD
[Socket] upgrade → websocket
```

- **`upgradeError` は一度も出ていない**
- upgrade は **`[LiveAudioManager] 初期化完了` より前**に完了している（＝挨拶配信のはるか前）

**→ プラン §3-3 の推定 H1（polling のまま `max_http_buffer_size` 超過で落ちる）は否定された。**
**→ プラン §9 #6 / 依頼文 §5 #8（本番の transport が未確認）は解決。**

### 2-2. ペイロードサイズが判明 — サイズ超過も否定

```
[Socket] live_audio arrived bytes=4        ← 各ターンの1件目は常に 4
bytes=2560, 5120, 7680, 10240, 12800, 15360, 17920, 20480, 23040,
      25600, 28160, 30720, 33280, 35840, 38400, 43520
```

**最大 43,520 バイト（base64 文字数）。** `python-engineio` の `max_http_buffer_size` 既定値 1,000,000 の 1/23。
そもそも WebSocket なので HTTP バッファは無関係。

**→ プラン §9 #8（`max_http_buffer_size` の既定値確認）は不要になった。**

`live_expression` の最大は 84 frames（52係数 × 84）。

### 2-3. 正常な挨拶ターンでは隙間がゼロ

```
[Sync] GAP dist n=33 max=0ms avg=0.0ms over10ms=0 total=0ms
```

**33チャンク全部が隙間なく連結された。**

**→ そちらの §2 確認事項3 への回答で私が述べた推定（「マージンが 5ms しかなく先読みもないため、正常起動でも小さい隙間が出る可能性がある」）は否定された。**

**これで「隙間が出たら異常」という判定基準ができた。**

### 2-4. 2ターン目には実在する隙間がある

同一セッション・同一 WebSocket 接続・同一コードで、2ターン目（ユーザー発話への応答）では隙間が出た。

```
[Sync] GAP 40ms  at t=25.061
[Sync] GAP 349ms at t=25.800
```

**数値を検算し、計測が正しく機能していることを確認した。**

`live_audio` の `bytes` は base64 文字数なので、実PCM = `bytes × 3/4`。24kHz 16bit mono より
`duration = bytes × 3/4 / 2 / 24000` 秒。

```
t=25.021  bytes=4      → ≈0秒       nextPlayTime ≈ 25.026
t=25.061  bytes=9600   → 0.150秒    startTime = max(25.066, 25.026) = 25.066
                                     GAP = 25.066 − 25.026 = 40ms   ✓ログと一致
                                     nextPlayTime = 25.216
          bytes=10240  → 0.160秒    nextPlayTime = 25.376
          bytes=5120   → 0.080秒    nextPlayTime = 25.456
t=25.800  bytes=15360  → 0.320秒    startTime = max(25.805, 25.456) = 25.805
                                     GAP = 25.805 − 25.456 = 349ms  ✓ログと一致
```

**349ms は知覚できる長さの無音である。** そして隙間は**応答の冒頭付近に集中**し、それ以降は発生していない。

### 2-5. GAP 計測に欠陥があり、修正した

初版（`86dcb23`）では次の値が出た。

```
[Sync] GAP 15101ms at t=25.021
[Sync] GAP dist n=33 max=15101ms avg=469.4ms over10ms=3 total=15490ms
```

**`15101ms` は音声の途切れではなく、ターン間の待ち時間だった。**

`onAiResponseEnded()` で `_gaps` はクリアするが `nextPlayTime` は前ターンの終了時刻を保持したままのため、
次ターンの1件目で「前ターン終了 → 次ターン開始」の実時間が GAP として記録されていた。
**`max` / `avg` / `total` が全部使えない値になっていた。**

修正（`0067924`）:

```typescript
// フィールド追加
private _skipNextGap: boolean = false;

// _scheduleBuffer
if (this.nextPlayTime > 0) {
    const gap = (startTime - this.nextPlayTime) * 1000;
    if (this._skipNextGap) {
        this._skipNextGap = false;
        console.log(`[Sync] turn境界 ${gap.toFixed(0)}ms（GAP集計から除外）`);
    } else {
        this._gaps.push(gap);
        if (gap > 20) console.warn(`[Sync] GAP ${gap.toFixed(0)}ms at t=${now.toFixed(3)}`);
    }
}

// onAiResponseEnded（分布出力後、無条件）
this._skipNextGap = true;
```

**`nextPlayTime` 自体はリセットしていない**（動作変更になるため）。計測側だけで除外し、
除外した値も `[Sync] turn境界` として別ログに残す。

### 2-6. zip のキャッシュヘッダ（#0）

```
$ curl -sI https://chatty-sp.vercel.app/avatar/meruru.zip

cache-control: public, max-age=0, must-revalidate
content-type: application/zip
content-length: 4093593
etag: "720989ee1d3630838703e663aef5cb8e"
last-modified: Sun, 23 Aug 2026 07:33:24 GMT
accept-ranges: bytes
x-vercel-cache: MISS
server: Vercel
```

**`max-age=0, must-revalidate`** — Vercel 静的アセットの既定値。
**2回目以降も「往復ゼロ」にはならず、毎回1RTTの再検証が入る**（本体は 304 で省略）。

`last-modified` が `date` と同一である点が気になるが、**デプロイのたびに ETag が変わるかは検証していない。**

`vercel.json` の変更は `CLAUDE.md` 第3項（本番設定）に該当するため、こちらからは提案しない。

### 2-7. 既存問題2件が正常起動でも発生することを確認

| 項目 | 観測 |
|---|---|
| `frameIdx` 固着 | 1ターン目終了後 `frameIdx=267/268` で固着（約4秒）、2ターン目終了後 `frameIdx=246/247` で固着（22秒以上、ログ末尾まで） |
| `WebGL: too many errors` | **挨拶再生の途中で発生。それでも音声・リップシンクは正常だった** |

**→ どちらもプラン §3-4 / 依頼文 §4-10 の「Step 1/2 以前からの別問題」という整理が裏付けられた。**
**→ WebGL エラーが不具合の原因でないことも、正常起動での発生によって再確認された。**

### 2-8. AudioContext は running だった

```
[Sync] StartTime reset to: 1.040          ← 挨拶再生時、currentTime が進んでいる
...（turn_complete の後）...
[LiveAudioManager] ストリーミング開始      ← startStreaming() = resume() はここで初めて呼ばれる
```

`resume()` を呼ぶ唯一の場所（`live-audio-manager.ts:165-172`）が実行される前に `currentTime` が進んでいる。

**→ AudioContext は最初から running。「suspended で無音になっている」説は否定された。**
（`getUserMedia()` の成功が解除していると推定されるが未確認）

---

## 3. 否定された仮説の一覧

| 仮説 | 出所 | 判定 | 根拠 |
|---|---|---|---|
| H1: polling で大きいペイロードが落ちる | プラン §3-3 | **否定** | §2-1 |
| `max_http_buffer_size` 超過 | プラン §9 #8 | **否定** | §2-2（最大43KB、かつWebSocket） |
| 正常時も小さい隙間が出る | こちらの §2 確認事項3 | **否定** | §2-3（`max=0ms`） |
| AudioContext が suspended | こちら（過去に撤回済み） | **否定** | §2-8 |
| WebGL エラーが原因 | こちら（過去に撤回済み） | **否定** | §2-7 |

---

## 4. 行き詰まっている点 — 2重リセットのロジックが説明できない

**ユーザーから「リロード2回だと不具合が発生しないロジックを説明できるか」と問われ、説明できなかった。**

候補を全部洗い出し、今あるデータで判定した結果が以下である。

| # | 候補 | 判定 | 根拠 |
|---|---|---|---|
| ① | アバター初期化がメインスレッドをブロックし、`live_audio` ハンドラの実行が遅れる | **否定的** | 下記 |
| ② | `nextPlayTime` の初期値の違い | **否定** | 下記 |
| ③ | 発話トリガーの違い（`send_client_content` vs `send_realtime_input`） | **未検証・知識ベース外** | — |
| ④ | `_is_initial_greeting_phase` の違い | **否定** | Step 1 で A2E 経路は一本化済み。残る差は transcript 非表示と `greeting_done` emit のみで、音声チャンクの配信・再生に関与しない |
| ⑤ | `sleep(300)` が 600ms になっていたこと | **未検証** | — |
| ⑥ | セッションが2つ作られること自体 | **未検証** | — |
| ⑦ | **偶然**（5か月間たまたま起きなかった） | **否定できない** | 下記 |

### ① が否定的な理由

`[A2E Sync]` は `_a2eDebugCounter % 60 === 0`（`live-audio-manager.ts:268-269`）で出力される。
`getCurrentExpressionFrame()` は `syncPlayer` の `requestAnimationFrame` ループから毎フレーム呼ばれる。

**つまり「60レンダリングフレームごとに、その時点の実時間オフセットを出力」している。**

メインスレッドが数百msブロックされれば、その間レンダリングも止まるため、60フレーム進むのに要する実時間が伸びるはずである。

**不具合B のログ（挨拶再生中）:**
```
offsetMs=979  → 1979 : 1000ms
        1979  → 2987 : 1008ms
        2987  → 3984 :  997ms
        3984  → 4981 :  997ms
        4981  → 5979 :  998ms
```

**349ms級のブロックがあれば 1349ms 前後になるはずだが、全区間 1000ms 前後で安定している。**

→ **挨拶再生中にメインスレッドの長時間ブロックは起きていない。**

### ② が否定される理由

```typescript
// core-controller.ts:687-700  terminateLiveSession()
this.liveAudioManager.clearPlaybackQueue();   // → nextPlayTime = 0
```

`clearPlaybackQueue()` は `isLiveMode` の値に関わらず**無条件で呼ばれる**。

| | 挨拶ターン開始時の `nextPlayTime` |
|---|---|
| Step 2 前（リセット2回） | **0**（2回目の `terminateLiveSession()` でクリア） |
| Step 2 後（リセット1回） | **0**（1回目の `terminateLiveSession()` でクリア） |

**差がない。**

### ⑦ が否定できない理由 — これが最も重要

**今日、Step 2 が入った状態で挨拶ターンの GAP はゼロだった。**

| 事象 | サンプル数 |
|---|---|
| 2重リセット時代に不具合Bが起きなかった | 5か月（多数） |
| **Step 2 後に不具合Bが起きた** | **1回** |
| **Step 2 後に挨拶ターンが正常だった** | **1回**（今日、`max=0ms` で確認） |

**「Step 2 = 必ず不具合Bが起きる」ではない。因果は1サンプルでしか支持されていない。**

---

## 5. 照会したいこと（6点）

### 照会1 — ① の否定根拠は妥当か

`[A2E Sync]` の「60レンダリングフレームあたりの実時間」からメインスレッドのブロックを否定した推論（§4 ①）は成立するか。

見落としがあるとすれば、`requestAnimationFrame` がブロック中にどう振る舞うか、
あるいは `_a2eDebugCounter` の増え方に想定と違う点がないか。

### 照会2 — ③ をどう扱うべきか

```python
# Step 2 前（セッションB、再接続ブランチ :780-797）
await self._send_history_on_reconnect(session)
resume_text = self._resume_message or "続きをお願いします"
await session.send_realtime_input(text=resume_text)

# Step 2 後（セッションA、初回ブランチ :753-775）
await session.send_client_content(
    turns=types.Content(role="user", parts=[types.Part(text=dummy_text)]),
    turn_complete=True
)
```

**この2つで LiveAPI のチャンク送出パターンが変わる可能性がある。**

`CLAUDE.md` は Gemini LiveAPI を知識ベース外と明記しているため、こちらは推測を書かなかった。
**この判断は妥当か。あるいは、推測せずに確かめる手立てがあるか**（公式ドキュメント、SDK のソース等）。

### 照会3 — ⑦（偶然）をどう評価するか

Step 2 と不具合B の因果は**1サンプル**でしか支持されていない。
一方、2重リセット時代の無報告は5か月ある。

**この非対称なサンプル数で因果を主張してよいか。** 主張しない場合、どこまでを「確定」と扱うべきか。

### 照会4 — 対照実験をやるべきか

決着をつける方法として以下を考えた。

```
git revert 36d65df           → 2重リセットに戻す
  ↓ 起動を N 回、GAP dist を記録
revert を revert             → Step 2 に戻す
  ↓ 起動を N 回、GAP dist を記録
```

| 結果 | 結論 |
|---|---|
| 2重リセット時は常に `max=0ms`、Step 2 時は時々 `max>0` | 因果が確定 |
| どちらも `max=0ms` ばかり | Step 2 は無関係。偶然だった |

**この設計は妥当か。N はいくつ必要か**（不具合Bの再現性が低いため、少なすぎると結論が出ない）。
**デプロイが2回走る**点と、**その間の本番リスク**をどう見るか。

### 照会5 — `dt` ログを先に入れるべきか

GAP > 0 は「前チャンクの再生終了時刻までに次のチャンクが `_scheduleBuffer` に到達しなかった」ことを意味する。
原因は A（サーバー側の emit 遅延）/ B（配信遅延）/ C（ブラウザ側の処理遅延）のいずれか。

**`live_audio` の到着間隔を記録すれば C を切り分けられる**と考えた。

```diff
+private _lastAudioArrival = 0;

 this.socket.on('live_audio', (data: any) => {
+  const t = performance.now();
+  const dt = this._lastAudioArrival ? t - this._lastAudioArrival : 0;
+  this._lastAudioArrival = t;
-  console.log(`[Socket] live_audio arrived bytes=... isLiveMode=... isTTS=...`);
+  console.log(`[Socket] live_audio arrived bytes=... dt=${dt.toFixed(0)}ms isLiveMode=... isTTS=...`);
```

`dt` とチャンクの再生長（`bytes × 3/4 / 2 / 24000`）を比べれば、供給が追いついているかが分かる。

**2ターン目で既に隙間が出ているため、再現待ちなしで次の通常起動1回でデータが取れる。**

**この案は妥当か。A と B を区別するには `chatty-base/` に emit 時刻ログが必要になるが、
Cloud Run デプロイを伴うため慎重に判断したい。**

### 照会6 — 第2段階に進んでよいか

プラン第2段階は `#5 preload 注入（案1-A）` と `#6 greeting_trigger 送信経路の確実化（案3-A）`。

**不具合B の原因が未特定のまま第2段階に進むことのリスクをどう見るか。**

- `#5` は `LAMAvatar.astro` の3行追加で、`linkLamAvatar()` を触らない → 独立
- `#6` は `linkLamAvatar()` を触る → 起動シーケンスが変わる

**特に `#6` は、不具合Bの切り分けに影響しないか。**

---

## 6. 現在のコード状態

`main` = `0067924`

| 項目 | main |
|---|---|
| Step 1（A2E経路一本化） | ✓ `2eb66bf` |
| Step 2（2重リセット削除） | ✓ `36d65df` |
| 計測ログ（transport / live_audio） | ✓ `17ba5d4` |
| `live_expression` ログ位置（#3） | ✓ `44c586d` |
| GAP 分布ログ（#4） | ✓ `86dcb23` |
| GAP 計測の欠陥修正（#4'） | ✓ `0067924` |

**`chatty-base/` は Step 1 以降変更していない。**

---

## 7. 未解決一覧（更新版）

プラン §9 の項目を、今回の結果で更新した。

| # | 項目 | 状態 |
|---|---|---|
| 1 | 不具合A のメカニズム | **未特定**。H1 は否定。再現時に `[Socket] live_audio arrived` の有無で分岐が決まる |
| 2 | 不具合B のチャンク遅延の理由 | **未特定**。§5 照会5 の `dt` ログが要る |
| 3 | 2重リセットが不具合を防いでいた因果 | **未証明**。§4 のとおり候補①②④は否定、③⑤⑥は未検証、⑦は否定できない |
| 4 | `sleep(300)` の意図 | **不明**（変わらず） |
| 5 | `GaussianSplatRenderer.getInstance()` の内部 | **未確認**（変わらず） |
| 6 | 本番 Socket.IO の transport | **解決 — WebSocket** |
| 7 | Vercel の zip キャッシュヘッダ | **解決 — `max-age=0, must-revalidate`** |
| 8 | `max_http_buffer_size` の既定値 | **不要になった**（§2-2） |
| 9 | `greeting_done` 即時 emit の実害 | **なし**（確認済み） |
| 10 | **正常時の GAP 分布** | **解決 — 挨拶ターンは `max=0ms`** |
| 11 | **2ターン目に隙間が出る理由** | **新規・未特定** |
| 12 | **`src/` のみの push でデプロイが走るか** | **新規・未確認** |
