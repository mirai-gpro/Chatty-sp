#!/usr/bin/env python3
"""
メニューPDFからGemini APIでメニューデータを抽出 → Supabase DBに投入

使い方:
  python extract_menu.py dennys
  python extract_menu.py kfc

環境変数:
  GEMINI_API_KEY: Gemini APIキー
  SUPABASE_URL: Supabase URL
  SUPABASE_SERVICE_KEY: Supabase Service Role Key
  PROMPTS_BUCKET_NAME: GCSバケット名（オプション）
"""

import sys
import os
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SHOP_NAMES = {
    'dennys': 'デニーズ',
    'kfc': 'KFC',
}


def get_pdf_path(shop_id: str) -> str:
    """PDFのパスを取得（ローカル優先、GCSフォールバック）"""
    # ローカル
    local_path = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, 'menu.pdf')
    if os.path.exists(local_path):
        logger.info(f"[Menu] ローカルPDFを使用: {local_path}")
        return local_path

    # GCS
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


def extract_menu_with_gemini(pdf_path: str, shop_id: str) -> list[dict]:
    """Gemini APIにPDFを送ってメニューデータを抽出"""
    import google.generativeai as genai

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.error("[Menu] GEMINI_API_KEY が設定されていません")
        sys.exit(1)

    genai.configure(api_key=api_key)
    shop_name = SHOP_NAMES.get(shop_id, shop_id)

    logger.info(f"[Menu] PDFをGemini APIにアップロード中...")
    pdf_file = genai.upload_file(pdf_path, mime_type='application/pdf')
    logger.info(f"[Menu] アップロード完了: {pdf_file.name}")

    prompt = f"""このPDFは「{shop_name}」のメニューです。
全ページを読み取り、以下のJSON配列形式でメニューデータを抽出してください。

【ルール】
- 全てのメニューアイテムを漏れなく抽出すること
- 価格は税込価格（円）を整数で記載
- カテゴリはPDFの構成に従う（モーニング、ランチ、グランドメニュー、デザート、ドリンク等）
- メニュー番号（5桁）があれば id に記載
- ドリンクバー付き価格がある場合は with_drink_bar_price に記載
- セット価格がある場合は set_price に記載
- 販売時間制限があれば time_restriction に記載（例: "開店〜11:00"）
- 説明文はPDFに記載のものを簡潔に
- JSON以外のテキストは一切出力しないこと

【出力JSON形式】 — 配列のみ出力
[
  {{
    "id": "メニュー番号5桁（なければshop_id + 連番で生成。例: dennys_001）",
    "shop_id": "{shop_id}",
    "name": "メニュー名（日本語）",
    "name_en": "メニュー名（英語）あれば、なければnull",
    "category": "カテゴリ名",
    "price": 税込価格（整数）,
    "price_without_tax": 税抜価格（整数）あれば、なければnull,
    "description": "説明文、なければnull",
    "with_drink_bar_price": ドリンクバー付き税込価格（整数）あれば、なければnull,
    "set_price": セット税込価格（整数）あれば、なければnull,
    "is_set_available": セットメニューが選択可能か（true/false）,
    "time_restriction": "販売時間制限、なければnull"
  }}
]"""

    logger.info(f"[Menu] Gemini APIでメニュー抽出中...（時間がかかります）")

    model = genai.GenerativeModel('gemini-2.5-flash')
    response = model.generate_content(
        [pdf_file, prompt],
        generation_config=genai.GenerationConfig(
            response_mime_type='application/json',
            temperature=0.1,
        ),
    )

    result_text = response.text
    logger.info(f"[Menu] Gemini応答受信: {len(result_text)} 文字")

    try:
        items = json.loads(result_text)
    except json.JSONDecodeError:
        start = result_text.find('[')
        end = result_text.rfind(']') + 1
        if start >= 0 and end > start:
            items = json.loads(result_text[start:end])
        else:
            logger.error(f"[Menu] JSON解析失敗。レスポンス:\n{result_text[:500]}")
            sys.exit(1)

    logger.info(f"[Menu] 抽出完了: {len(items)} アイテム")
    return items


def save_to_supabase(items: list[dict]):
    """Supabase DBのmenusテーブルに投入"""
    from supabase import create_client

    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        logger.error("[Menu] SUPABASE_URL / SUPABASE_SERVICE_KEY が設定されていません")
        sys.exit(1)

    supabase = create_client(url, key)

    # 既存データを削除（shop_id単位）
    if items:
        shop_id = items[0].get('shop_id')
        if shop_id:
            supabase.table('menus').delete().eq('shop_id', shop_id).execute()
            logger.info(f"[Menu] 既存データ削除: shop_id={shop_id}")

    # バッチ投入（100件ずつ）
    batch_size = 100
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        # None値をnullに変換
        for item in batch:
            for k, v in item.items():
                if v is None:
                    item[k] = None
        result = supabase.table('menus').insert(batch).execute()
        logger.info(f"[Menu] DB投入: {i+1}〜{i+len(batch)} / {len(items)}")

    logger.info(f"[Menu] DB投入完了: {len(items)} アイテム")


def save_local_json(shop_id: str, items: list[dict]):
    """ローカルにもJSONバックアップを保存"""
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, 'menu.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    logger.info(f"[Menu] ローカルバックアップ保存: {output_path}")


def print_summary(items: list[dict]):
    """カテゴリ別サマリー表示"""
    categories = {}
    for item in items:
        cat = item.get('category', '不明')
        categories[cat] = categories.get(cat, 0) + 1

    logger.info(f"\n[Menu] === カテゴリ別サマリー ===")
    for cat, count in sorted(categories.items()):
        logger.info(f"  {cat}: {count}品")
    logger.info(f"  合計: {len(items)}品")


def main():
    if len(sys.argv) < 2:
        print("使い方: python extract_menu.py <shop_id>")
        print("  例: python extract_menu.py dennys")
        sys.exit(1)

    shop_id = sys.argv[1]
    logger.info(f"[Menu] {shop_id} のメニュー抽出 → Supabase投入 開始")

    # 1. PDFパスを取得
    pdf_path = get_pdf_path(shop_id)

    # 2. Gemini APIでメニュー抽出
    items = extract_menu_with_gemini(pdf_path, shop_id)

    # 3. ローカルバックアップ
    save_local_json(shop_id, items)

    # 4. Supabase DBに投入
    try:
        save_to_supabase(items)
    except Exception as e:
        logger.warning(f"[Menu] Supabase投入スキップ: {e}")
        logger.info("[Menu] ローカルのmenu.jsonは保存済みです")

    # 5. サマリー
    print_summary(items)

    logger.info(f"[Menu] 完了！")


if __name__ == '__main__':
    main()
