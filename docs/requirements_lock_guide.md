# requirements.txt 完全固定化 手順書

## 背景

Cloud Runの自動デプロイ（GitHub連携）では、同じ`requirements.txt`でも再ビルドのたびに間接依存のバージョンが変わる可能性がある。これにより、コードを変更していないのにリップシンク等の機能が壊れる問題が発生した。

### 原因
`requirements.txt`に直接依存のみ記載（例: `supabase==2.28.3`）していると、その間接依存（例: `pyiceberg`, `zstandard`等）のバージョンはビルド時のpip解決に任される。ビルドタイミングによって間接依存のバージョンが変わり、`scipy`や`numpy`との相互作用でA2Eリップシンクが壊れた。

### 解決策
`pip freeze`で全依存（間接含む）のバージョンを完全固定した`requirements.txt`を使う。

---

## 手順

### 1. 仮想環境を作成してインストール

```powershell
cd <プロジェクト>/chatty-base    # or support-base
python -m venv .venv_freeze
.\.venv_freeze\Scripts\activate
pip install -r requirements.txt
```

### 2. 全依存をfreezeして保存

```powershell
pip freeze > requirements-lock.txt
```

### 3. requirements.txtを差し替え

`requirements-lock.txt`の内容を`requirements.txt`にコピーする。
先頭にコメントを追加:

```
# 全依存完全固定版（pip freeze から生成）
# Cloud Runの再ビルドで依存解決が変わる問題を防ぐため、間接依存も含めて全て固定
# 開発ツール（pdfplumber等）はrequirements-dev.txtに分離
```

### 4. 仮想環境を削除

```powershell
deactivate
Remove-Item -Recurse -Force .venv_freeze
```

### 5. コミット＆プッシュ

```powershell
git add requirements.txt
git commit -m "requirements.txtを全依存完全固定版に差し替え"
git push
```

### 6. デプロイ後の確認

- 初期あいさつのリップシンクが正常か確認
- ソフトリセット不要で初回から動くか確認

---

## 注意事項

### パッケージを追加する場合
1. 仮想環境で`pip install 新パッケージ`
2. `pip freeze > requirements.txt`で再固定
3. **開発ツール（pdfplumber等Cloud Runで不要なもの）は`requirements-dev.txt`に分離**
4. デプロイ後にリップシンク含む全機能を確認

### パッケージをアップデートする場合
1. 仮想環境で`pip install --upgrade 対象パッケージ`
2. `pip freeze > requirements.txt`で再固定
3. デプロイ後に確認

### 障害時の対応
1. **即座**: GCPコンソール → Cloud Run → 正常だった旧リビジョンにトラフィック100%
2. **Git revert + 再ビルドでは復旧しない場合がある**（同じコードでもビルド結果が異なる）
3. 旧リビジョンで安定化後、原因特定してから修正

---

## Travel-sp への適用

Travel-spリポジトリでも同じ手順で実施する:

```powershell
cd C:\Users\hamad\Travel-sp\support-base
python -m venv .venv_freeze
.\.venv_freeze\Scripts\activate
pip install -r requirements.txt
pip freeze > requirements-lock.txt
deactivate
```

`requirements-lock.txt`の内容を`requirements.txt`に差し替えてコミット。

**注意**: Travel-spは現在正常動作中なので、**正常リビジョンを記録してから**差し替えを行うこと。万が一問題が起きても旧リビジョンに戻せるようにする。
