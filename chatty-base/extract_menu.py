#!/usr/bin/env python3
"""
メニューPDFからGemini APIでMarkdown形式のメニューデータを生成
画像はPDFから抽出しSupabase Storageにアップロード

使い方:
  python extract_menu.py dennys
  python extract_menu.py kfc

環境変数:
  GEMINI_API_KEY: Gemini APIキー
  SUPABASE_URL: Supabase URL
  SUPABASE_SERVICE_KEY: Supabase Service Role Key
"""

import sys
import os
import io
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


def extract_images_from_pdf(pdf_path: str, shop_id: str) -> dict:
    """PDFから画像を抽出しSupabase Storageにアップロード。ページ番号→URL のマッピングを返す"""
    import pdfplumber
    from PIL import Image
    from supabase import create_client

    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        logger.warning("[Menu] SUPABASE_URL/KEY未設定。画像アップロードスキップ")
        return {}

    supabase = create_client(url, key)
    image_urls = {}  # "page_N_img_M" → public URL
    img_counter = 0

    logger.info(f"[Menu] PDFから画像を抽出中...")
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            if not hasattr(page, 'images') or not page.images:
                continue

            for img_idx, img_info in enumerate(page.images):
                try:
                    # 画像のバウンディングボックスからクロップ
                    x0 = img_info['x0']
                    y0 = img_info['top']
                    x1 = img_info['x1']
                    y1 = img_info['bottom']

                    # 小さすぎる画像（アイコン等）はスキップ
                    if (x1 - x0) < 50 or (y1 - y0) < 50:
                        continue

                    cropped = page.crop((x0, y0, x1, y1))
                    pil_image = cropped.to_image(resolution=150).original

                    # JPEGに変換
                    img_buffer = io.BytesIO()
                    if pil_image.mode == 'RGBA':
                        pil_image = pil_image.convert('RGB')
                    pil_image.save(img_buffer, format='JPEG', quality=80)
                    img_bytes = img_buffer.getvalue()

                    # Supabase Storageにアップロード
                    file_path = f"{shop_id}/page{page_num}_img{img_idx}.jpg"
                    supabase.storage.from_('menu').upload(
                        file_path,
                        img_bytes,
                        file_options={"content-type": "image/jpeg", "upsert": "true"}
                    )

                    # 公開URLを取得
                    public_url = f"{url}/storage/v1/object/public/menu/{file_path}"
                    image_key = f"page{page_num}_img{img_idx}"
                    image_urls[image_key] = public_url
                    img_counter += 1

                except Exception as e:
                    logger.debug(f"[Menu] 画像抽出スキップ (p{page_num}, img{img_idx}): {e}")
                    continue

    logger.info(f"[Menu] 画像抽出完了: {img_counter}枚アップロード")
    return image_urls


def extract_menu_markdown(pdf_path: str, shop_id: str, image_urls: dict) -> str:
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

    # 画像URLリストをプロンプトに含める
    image_list_text = ""
    if image_urls:
        image_list_text = "\n\n【利用可能な画像URL一覧】\n"
        for key, url in image_urls.items():
            image_list_text += f"- {key}: {url}\n"
        image_list_text += "\n各メニューアイテムに最も関連する画像があれば、![メニュー名](URL) 形式で含めてください。"

    # カテゴリ一覧を先に取得
    logger.info(f"[Menu] Step 1: カテゴリ一覧を取得中...")
    cat_response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[
            pdf_part,
            f"""このPDFは「{shop_name}」のメニューです。
メニューのカテゴリ（大分類）を全て列挙してください。
1行に1カテゴリ、日本語のみで出力。英語名は不要。"""
        ],
        config=types.GenerateContentConfig(temperature=0.1),
    )
    categories_text = cat_response.text.strip()
    logger.info(f"[Menu] カテゴリ一覧:\n{categories_text}")

    # カテゴリごとにMarkdown抽出
    all_markdown = f"# {shop_name} メニュー\n\n"

    categories = [c.strip() for c in categories_text.strip().split('\n') if c.strip()]
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
{image_list_text}

【出力Markdown形式】— 各アイテムを以下の形式で出力

### メニュー名
![メニュー名](画像URL)
**価格:** ¥税込価格
**メニュー番号:** 5桁番号
**説明:** 説明文
**ドリンクバー付き:** ¥価格（あれば）
**セット価格:** ¥価格（あれば）
**販売時間:** 時間制限（あれば）

---
"""

        max_retries = 3
        for attempt in range(max_retries):
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
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    import time
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"[Menu]   「{cat}」失敗（リトライ {attempt+1}/{max_retries}、{wait}秒後）: {e}")
                    time.sleep(wait)
                else:
                    logger.warning(f"[Menu]   「{cat}」抽出失敗（全リトライ失敗）: {e}")

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

    # 2. PDFから画像抽出 → Supabase Storageにアップロード
    image_urls = extract_images_from_pdf(pdf_path, shop_id)

    # 3. Gemini APIでMarkdown抽出（画像URL埋め込み）
    markdown = extract_menu_markdown(pdf_path, shop_id, image_urls)

    # 4. Markdownファイルを保存
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{shop_id}_menu.md')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown)
    logger.info(f"[Menu] Markdown保存完了: {output_path}")

    # サマリー
    item_count = markdown.count('### ')
    logger.info(f"[Menu] 合計: 約{item_count}品, 画像: {len(image_urls)}枚")
    logger.info(f"[Menu] 完了！")


if __name__ == '__main__':
    main()
