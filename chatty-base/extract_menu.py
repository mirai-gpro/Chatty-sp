#!/usr/bin/env python3
"""
GCSからメニューPDFをダウンロードしてテキスト抽出 → menu.json生成

使い方:
  python extract_menu.py dennys
  python extract_menu.py kfc

環境変数:
  PROMPTS_BUCKET_NAME: GCSバケット名
"""

import sys
import os
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """PDFからページごとにテキストを抽出"""
    import pdfplumber

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        logger.info(f"[Menu] PDF読み込み: {len(pdf.pages)} ページ")
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            tables = page.extract_tables()
            pages.append({
                'page': i + 1,
                'text': text or '',
                'tables': tables or [],
                'has_text': bool(text and text.strip()),
                'has_tables': bool(tables)
            })
            if text and text.strip():
                logger.info(f"  ページ {i+1}: テキストあり ({len(text)} 文字)")
            else:
                logger.info(f"  ページ {i+1}: テキストなし（画像のみの可能性）")
    return pages


def save_raw_extraction(shop_id: str, pages: list[dict]):
    """生のテキスト抽出結果をJSONで保存（デバッグ・確認用）"""
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    os.makedirs(output_dir, exist_ok=True)

    raw_path = os.path.join(output_dir, 'raw_extraction.json')
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)
    logger.info(f"[Menu] 生テキスト抽出結果を保存: {raw_path}")

    # テキストのみのサマリーも保存
    text_path = os.path.join(output_dir, 'raw_text.txt')
    with open(text_path, 'w', encoding='utf-8') as f:
        for page in pages:
            f.write(f"=== ページ {page['page']} ===\n")
            f.write(page['text'] + '\n\n')
    logger.info(f"[Menu] テキストサマリーを保存: {text_path}")


def main():
    if len(sys.argv) < 2:
        print("使い方: python extract_menu.py <shop_id>")
        print("  例: python extract_menu.py dennys")
        sys.exit(1)

    shop_id = sys.argv[1]
    logger.info(f"[Menu] {shop_id} のメニューPDFを処理開始")

    # 1. GCSからPDFをダウンロード
    try:
        pdf_path = download_pdf_from_gcs(shop_id)
    except FileNotFoundError:
        # ローカルフォールバック
        local_path = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, 'menu.pdf')
        if os.path.exists(local_path):
            pdf_path = local_path
            logger.info(f"[Menu] ローカルPDFを使用: {local_path}")
        else:
            logger.error(f"[Menu] PDFが見つかりません: GCS menu_data/{shop_id}/menu.pdf")
            sys.exit(1)

    # 2. テキスト抽出
    pages = extract_text_from_pdf(pdf_path)

    # 3. 生の抽出結果を保存
    save_raw_extraction(shop_id, pages)

    # サマリー
    text_pages = sum(1 for p in pages if p['has_text'])
    table_pages = sum(1 for p in pages if p['has_tables'])
    logger.info(f"[Menu] 完了: 全{len(pages)}ページ, テキストあり={text_pages}, テーブルあり={table_pages}")
    logger.info(f"[Menu] 次のステップ: raw_text.txt を確認し、menu.json のフォーマットに整形")


if __name__ == '__main__':
    main()
