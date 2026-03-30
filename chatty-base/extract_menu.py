#!/usr/bin/env python3
"""
メニューPDFからGemini APIでMarkdown形式のメニューデータを生成

使い方:
  python extract_menu.py dennys
  python extract_menu.py kfc

環境変数:
  GEMINI_API_KEY: Gemini APIキー
"""

import sys
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SHOP_NAMES = {
    'dennys': 'デニーズ',
    'kfc': 'KFC',
}


def get_pdf_path(shop_id: str) -> str:
    """PDFのパスを取得（ローカル優先、GCSフォールバック）"""
    local_path = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, 'menu.pdf')
    if os.path.exists(local_path):
        logger.info(f"[Menu] ローカルPDFを使用: {local_path}")
        return local_path

    try:
        from google.cloud import storage
        import tempfile
        bucket_name = os.getenv('PROMPTS_BUCKET_NAME')
        if bucket_name:
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(f'menu_data/{shop_id}/menu.pdf')
            if blob.exists():
                tmp_path = os.path.join(tempfile.gettempdir(), f'{shop_id}_menu.pdf')
                blob.download_to_filename(tmp_path)
                logger.info(f"[Menu] GCSからダウンロード完了: {tmp_path}")
                return tmp_path
    except Exception as e:
        logger.info(f"[Menu] GCSスキップ: {e}")

    logger.error(f"[Menu] PDFが見つかりません: menu_data/{shop_id}/menu.pdf")
    sys.exit(1)


def extract_menu_markdown(pdf_path: str, shop_id: str) -> str:
    """Gemini APIにPDFを送ってMarkdown形式のメニューデータを生成"""
    from google import genai
    from google.genai import types

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.error("[Menu] GEMINI_API_KEY が設定されていません")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    shop_name = SHOP_NAMES.get(shop_id, shop_id)

    logger.info(f"[Menu] PDFを読み込み中...")
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf')
    logger.info(f"[Menu] PDF読み込み完了: {len(pdf_bytes)} bytes")

    # カテゴリ一覧を先に取得
    logger.info(f"[Menu] Step 1: カテゴリ一覧を取得中...")
    cat_response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[
            pdf_part,
            f"""このPDFは「{shop_name}」のメニューです。
メニューのカテゴリ（大分類）を全て列挙してください。
カンマ区切りのテキストのみ出力。"""
        ],
        config=types.GenerateContentConfig(temperature=0.1),
    )
    categories_text = cat_response.text.strip()
    logger.info(f"[Menu] カテゴリ一覧: {categories_text}")

    # カテゴリごとにMarkdown抽出
    all_markdown = f"# {shop_name} メニュー\n\n"

    categories = [c.strip() for c in categories_text.split(',')]
    for cat in categories:
        logger.info(f"[Menu] Step 2: 「{cat}」カテゴリを抽出中...")
        prompt = f"""このPDFは「{shop_name}」のメニューです。
「{cat}」カテゴリに属するメニューアイテムのみを全て抽出し、以下のMarkdown形式で出力してください。

【ルール】
- 「{cat}」カテゴリのアイテムのみ
- 価格は税込価格で記載
- メニュー番号（5桁）があれば記載
- 説明文はPDFに記載のものを簡潔に
- 販売時間制限があれば記載
- ドリンクバー付き価格、セット価格があれば記載
- カテゴリ見出し（##）は不要（こちらで付けます）

【出力Markdown形式】— 各アイテムを以下の形式で出力

### メニュー名
**価格:** ¥税込価格
**メニュー番号:** 5桁番号
**説明:** 説明文
**ドリンクバー付き:** ¥価格（あれば）
**セット価格:** ¥価格（あれば）
**販売時間:** 時間制限（あれば）

---
"""

        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[pdf_part, prompt],
                config=types.GenerateContentConfig(temperature=0.1),
            )
            cat_markdown = response.text.strip()
            item_count = cat_markdown.count('### ')
            all_markdown += f"\n## {cat}\n\n{cat_markdown}\n"
            logger.info(f"[Menu]   「{cat}」: {item_count}品 抽出")
        except Exception as e:
            logger.warning(f"[Menu]   「{cat}」抽出失敗: {e}")
            continue

    logger.info(f"[Menu] 全カテゴリ抽出完了")
    return all_markdown


def main():
    if len(sys.argv) < 2:
        print("使い方: python extract_menu.py <shop_id>")
        print("  例: python extract_menu.py dennys")
        sys.exit(1)

    shop_id = sys.argv[1]
    logger.info(f"[Menu] {shop_id} のメニューPDF → Markdown変換開始")

    # 1. PDFパスを取得
    pdf_path = get_pdf_path(shop_id)

    # 2. Gemini APIでMarkdown抽出
    markdown = extract_menu_markdown(pdf_path, shop_id)

    # 3. Markdownファイルを保存
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{shop_id}_menu.md')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown)
    logger.info(f"[Menu] Markdown保存完了: {output_path}")

    # サマリー
    item_count = markdown.count('### ')
    logger.info(f"[Menu] 合計: 約{item_count}品")
    logger.info(f"[Menu] 完了！")


if __name__ == '__main__':
    main()
