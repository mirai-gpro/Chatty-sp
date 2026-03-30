#!/usr/bin/env python3
"""
メニューPDFからGemini APIを使ってmenu.jsonを生成

使い方:
  python extract_menu.py dennys
  python extract_menu.py kfc

環境変数:
  GEMINI_API_KEY: Gemini APIキー
  PROMPTS_BUCKET_NAME: GCSバケット名（オプション）
"""

import sys
import os
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SHOP_NAMES = {
    'dennys': 'デニーズ',
    'kfc': 'KFC',
}


def download_pdf_from_gcs(shop_id: str) -> str:
    """GCSからPDFをダウンロードして一時ファイルパスを返す"""
    from google.cloud import storage

    bucket_name = os.getenv('PROMPTS_BUCKET_NAME')
    if not bucket_name:
        raise ValueError("PROMPTS_BUCKET_NAME が設定されていません")

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f'menu_data/{shop_id}/menu.pdf')

    if not blob.exists():
        raise FileNotFoundError(f"GCSに見つかりません: menu_data/{shop_id}/menu.pdf")

    tmp_path = os.path.join(tempfile.gettempdir(), f'{shop_id}_menu.pdf')
    blob.download_to_filename(tmp_path)
    logger.info(f"[Menu] GCSからダウンロード完了: {tmp_path} ({os.path.getsize(tmp_path)} bytes)")
    return tmp_path


def get_pdf_path(shop_id: str) -> str:
    """PDFのパスを取得（GCS優先、ローカルフォールバック）"""
    pdf_path = None
    try:
        pdf_path = download_pdf_from_gcs(shop_id)
    except Exception as e:
        logger.info(f"[Menu] GCSダウンロードスキップ: {e}")

    if not pdf_path:
        local_path = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, 'menu.pdf')
        if os.path.exists(local_path):
            pdf_path = local_path
            logger.info(f"[Menu] ローカルPDFを使用: {local_path}")
        else:
            logger.error(f"[Menu] PDFが見つかりません: menu_data/{shop_id}/menu.pdf")
            sys.exit(1)
    return pdf_path


def extract_menu_with_gemini(pdf_path: str, shop_id: str) -> dict:
    """Gemini APIにPDFを送ってmenu.jsonを生成"""
    import google.generativeai as genai

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.error("[Menu] GEMINI_API_KEY が設定されていません")
        sys.exit(1)

    genai.configure(api_key=api_key)

    shop_name = SHOP_NAMES.get(shop_id, shop_id)

    # PDFをアップロード
    logger.info(f"[Menu] PDFをGemini APIにアップロード中...")
    pdf_file = genai.upload_file(pdf_path, mime_type='application/pdf')
    logger.info(f"[Menu] アップロード完了: {pdf_file.name}")

    prompt = f"""このPDFは「{shop_name}」のメニューです。
全ページを読み取り、以下のJSON形式でメニューデータを抽出してください。

【ルール】
- 全てのメニューアイテムを漏れなく抽出すること
- 価格は税込価格（円）を整数で記載
- カテゴリはPDFの構成に従う（モーニング、ランチ、グランドメニュー、デザート、ドリンク等）
- メニュー番号（5桁）があれば記載
- セット価格がある場合はset_priceに記載
- ドリンクバー付きの価格がある場合はwith_drink_bar_priceに記載
- 説明文はPDFに記載のものを簡潔に記載
- JSON以外のテキストは一切出力しないこと

【出力JSON形式】
{{
  "shop_name": "{shop_name}",
  "categories": [
    {{
      "name": "カテゴリ名",
      "time_restriction": "販売時間制限があれば記載（例: 開店〜11:00）、なければnull",
      "items": [
        {{
          "id": "メニュー番号（5桁）、なければnull",
          "name": "メニュー名（日本語）",
          "name_en": "メニュー名（英語）、あれば",
          "price": 税込価格（整数）,
          "price_without_tax": 税抜価格（整数）、あれば,
          "description": "説明文",
          "with_drink_bar_price": ドリンクバー付き税込価格、あればnullでなければ整数,
          "set_price": セット税込価格、あればnullでなければ整数,
          "is_set_available": セットメニューが選択可能か（true/false）
        }}
      ]
    }}
  ]
}}"""

    logger.info(f"[Menu] Gemini APIでメニュー抽出中...（時間がかかります）")

    model = genai.GenerativeModel('gemini-2.5-flash')
    response = model.generate_content(
        [pdf_file, prompt],
        generation_config=genai.GenerationConfig(
            response_mime_type='application/json',
            temperature=0.1,
        ),
    )

    # レスポンスからJSONを取得
    result_text = response.text
    logger.info(f"[Menu] Gemini応答受信: {len(result_text)} 文字")

    try:
        menu_data = json.loads(result_text)
    except json.JSONDecodeError:
        # JSON部分だけ抽出を試みる
        start = result_text.find('{')
        end = result_text.rfind('}') + 1
        if start >= 0 and end > start:
            menu_data = json.loads(result_text[start:end])
        else:
            logger.error(f"[Menu] JSON解析失敗。レスポンス:\n{result_text[:500]}")
            sys.exit(1)

    return menu_data


def save_menu_json(shop_id: str, menu_data: dict):
    """menu.jsonを保存"""
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, 'menu.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(menu_data, f, ensure_ascii=False, indent=2)
    logger.info(f"[Menu] menu.json保存完了: {output_path}")

    # サマリー表示
    total_items = 0
    for cat in menu_data.get('categories', []):
        items = cat.get('items', [])
        total_items += len(items)
        logger.info(f"  カテゴリ: {cat['name']} ({len(items)}品)")
    logger.info(f"[Menu] 合計: {total_items}品")


def main():
    if len(sys.argv) < 2:
        print("使い方: python extract_menu.py <shop_id>")
        print("  例: python extract_menu.py dennys")
        sys.exit(1)

    shop_id = sys.argv[1]
    logger.info(f"[Menu] {shop_id} のメニューPDF → menu.json 変換開始")

    # 1. PDFパスを取得
    pdf_path = get_pdf_path(shop_id)

    # 2. Gemini APIでメニュー抽出
    menu_data = extract_menu_with_gemini(pdf_path, shop_id)

    # 3. menu.jsonを保存
    save_menu_json(shop_id, menu_data)

    logger.info(f"[Menu] 完了！")


if __name__ == '__main__':
    main()
