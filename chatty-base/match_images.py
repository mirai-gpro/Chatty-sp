#!/usr/bin/env python3
"""
Supabase Storageの画像をGeminiに見せてメニュー名とマッチングする

使い方:
  python match_images.py dennys

環境変数:
  GEMINI_API_KEY: Gemini APIキー
  SUPABASE_URL: Supabase URL
  SUPABASE_SERVICE_KEY: Supabase Service Role Key

出力:
  menu_data/{shop_id}/image_matches.json  — マッチング結果
  menu_data/{shop_id}/{shop_id}_menu.md   — 画像URL差し替え済みMarkdown
"""

import sys
import os
import json
import re
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SHOP_NAMES = {
    'dennys': 'デニーズ',
    'kfc': 'KFC',
}


def get_menu_names_from_markdown(md_path: str) -> list[str]:
    """Markdownからメニュー名一覧を抽出"""
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    names = []
    for match in re.finditer(r'^###\s+(.+)', content, re.MULTILINE):
        names.append(match.group(1).strip())

    logger.info(f"[Match] Markdownからメニュー名 {len(names)}品 抽出")
    return names


def list_supabase_images(shop_id: str) -> list[str]:
    """Supabase Storageからshop_idフォルダ内の画像URLリストを取得"""
    from supabase import create_client

    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        logger.error("[Match] SUPABASE_URL/KEY未設定")
        sys.exit(1)

    supabase = create_client(url, key)
    result = supabase.storage.from_('menu').list(shop_id)

    image_urls = []
    for item in result:
        name = item.get('name', '')
        if name.endswith('.jpg') or name.endswith('.png'):
            public_url = f"{url}/storage/v1/object/public/menu/{shop_id}/{name}"
            image_urls.append({
                'file_name': name,
                'url': public_url,
            })

    logger.info(f"[Match] Supabase Storageから画像 {len(image_urls)}枚 取得")
    return image_urls


def match_image_to_menu(image_url: str, menu_names: list[str], client) -> dict:
    """1枚の画像をGeminiに見せてメニュー名とマッチング"""
    from google.genai import types

    # メニュー名リストを番号付きで構成
    menu_list = '\n'.join([f"{i+1}. {name}" for i, name in enumerate(menu_names)])

    prompt = f"""この画像は飲食店のメニュー写真です。
以下のメニューリストの中から、この画像に最も合致するメニューを1つだけ選んでください。

【メニューリスト】
{menu_list}

【回答形式】JSON形式のみ出力。それ以外のテキストは不要。
{{"menu_number": 番号（整数）, "menu_name": "選んだメニュー名", "confidence": 確信度（0-100の整数）, "reason": "判断理由を1行で"}}
"""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_uri(file_uri=image_url, mime_type='image/jpeg'),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                temperature=0.1,
            ),
        )
        result = json.loads(response.text)
        return result
    except Exception as e:
        logger.warning(f"[Match] マッチング失敗: {e}")
        return {"menu_number": 0, "menu_name": "不明", "confidence": 0, "reason": str(e)}


def run_matching(shop_id: str):
    """全画像のマッチングを実行"""
    from google import genai

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.error("[Match] GEMINI_API_KEY未設定")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # 1. Markdownからメニュー名一覧を取得
    md_path = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, f'{shop_id}_menu.md')
    if not os.path.exists(md_path):
        logger.error(f"[Match] Markdownファイルが見つかりません: {md_path}")
        sys.exit(1)
    menu_names = get_menu_names_from_markdown(md_path)

    # 2. Supabase Storageから画像一覧を取得
    images = list_supabase_images(shop_id)

    # 3. 1枚ずつマッチング
    results = []
    for i, img in enumerate(images):
        logger.info(f"[Match] {i+1}/{len(images)}: {img['file_name']} をマッチング中...")
        match = match_image_to_menu(img['url'], menu_names, client)
        match['image_file'] = img['file_name']
        match['image_url'] = img['url']
        match['status'] = 'ok' if match.get('confidence', 0) >= 80 else 'review'
        results.append(match)

        # レート制限対策
        if (i + 1) % 5 == 0:
            time.sleep(1)

    # 4. 結果を保存
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    output_path = os.path.join(output_dir, 'image_matches.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"[Match] マッチング結果保存: {output_path}")

    # サマリー
    ok_count = sum(1 for r in results if r['status'] == 'ok')
    review_count = sum(1 for r in results if r['status'] == 'review')
    logger.info(f"[Match] 完了: {len(results)}枚中 OK={ok_count}, 要レビュー={review_count}")

    return results


def apply_matches_to_markdown(shop_id: str, results: list[dict]):
    """マッチング結果をMarkdownの画像URLに反映"""
    md_path = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, f'{shop_id}_menu.md')
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # メニュー名→正しい画像URLのマッピングを構築（confidence >= 70のみ）
    name_to_url = {}
    for r in results:
        if r.get('confidence', 0) >= 70 and r.get('menu_name'):
            name_to_url[r['menu_name']] = r['image_url']

    # Markdownの各メニューアイテムの画像URLを差し替え
    lines = content.split('\n')
    new_lines = []
    current_menu_name = None

    for line in lines:
        # ### メニュー名 を検出
        title_match = re.match(r'^###\s+(.+)', line)
        if title_match:
            current_menu_name = title_match.group(1).strip()
            new_lines.append(line)
            continue

        # ![alt](url) を検出して差し替え
        img_match = re.match(r'^!\[(.+?)\]\((.+?)\)', line)
        if img_match and current_menu_name and current_menu_name in name_to_url:
            correct_url = name_to_url[current_menu_name]
            new_lines.append(f'![{current_menu_name}]({correct_url})')
            continue

        new_lines.append(line)

    new_content = '\n'.join(new_lines)

    # 保存
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    replaced = sum(1 for name in name_to_url)
    logger.info(f"[Match] Markdown画像URL差し替え完了: {replaced}品")


def main():
    if len(sys.argv) < 2:
        print("使い方: python match_images.py <shop_id>")
        print("  例: python match_images.py dennys")
        sys.exit(1)

    shop_id = sys.argv[1]
    logger.info(f"[Match] {shop_id} の画像マッチング開始")

    # マッチング実行
    results = run_matching(shop_id)

    # Markdownに反映
    apply_matches_to_markdown(shop_id, results)

    logger.info(f"[Match] 完了！ image_matches.json を確認してください")


if __name__ == '__main__':
    main()
