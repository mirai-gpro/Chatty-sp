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
            model='gemini-1.5-flash',
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


def run_matching(shop_id: str, retry_failed: bool = False):
    """全画像のマッチングを実行（retry_failed=Trueで失敗分のみリトライ）"""
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

    # 既存結果の読み込み（リトライ用）
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    output_path = os.path.join(output_dir, 'image_matches.json')
    existing_results = []
    failed_files = set()
    if retry_failed and os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            existing_results = json.load(f)
        failed_files = {r['image_file'] for r in existing_results if r.get('confidence', 0) == 0}
        logger.info(f"[Match] リトライ対象: {len(failed_files)}枚 ({', '.join(sorted(failed_files))})")
        if not failed_files:
            logger.info("[Match] 失敗画像なし。リトライ不要です。")
            return existing_results

    # 2. 画像一覧を取得
    if retry_failed and existing_results:
        # リトライモード: 既存jsonからURLを取得（Supabase API不要）
        images = [
            {'file_name': r['image_file'], 'url': r['image_url']}
            for r in existing_results if r['image_file'] in failed_files
        ]
        logger.info(f"[Match] 既存jsonからリトライ対象画像: {len(images)}枚")
    else:
        # 通常モード: Supabase Storageから取得
        images = list_supabase_images(shop_id)

    # 3. 1枚ずつマッチング
    new_results = []
    for i, img in enumerate(images):
        logger.info(f"[Match] {i+1}/{len(images)}: {img['file_name']} をマッチング中...")
        match = match_image_to_menu(img['url'], menu_names, client)
        match['image_file'] = img['file_name']
        match['image_url'] = img['url']
        match['status'] = 'ok' if match.get('confidence', 0) >= 80 else 'review'
        new_results.append(match)

        # レート制限対策
        if (i + 1) % 3 == 0:
            time.sleep(2)

    # 4. 結果をマージ（リトライモード: 失敗分を差し替え）
    if retry_failed and existing_results:
        new_by_file = {r['image_file']: r for r in new_results}
        results = []
        for r in existing_results:
            if r['image_file'] in new_by_file:
                results.append(new_by_file[r['image_file']])
            else:
                results.append(r)
        # 既存になかった新規結果も追加
        existing_files = {r['image_file'] for r in existing_results}
        for r in new_results:
            if r['image_file'] not in existing_files:
                results.append(r)
    else:
        results = new_results

    # 5. 結果を保存
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
        print("使い方: python match_images.py <shop_id> [--retry-failed]")
        print("  例: python match_images.py dennys")
        print("  例: python match_images.py dennys --retry-failed")
        sys.exit(1)

    shop_id = sys.argv[1]
    retry_failed = '--retry-failed' in sys.argv

    if retry_failed:
        logger.info(f"[Match] {shop_id} の失敗画像リトライ開始")
    else:
        logger.info(f"[Match] {shop_id} の画像マッチング開始")

    # マッチング実行
    results = run_matching(shop_id, retry_failed=retry_failed)

    # Markdownに反映
    apply_matches_to_markdown(shop_id, results)

    logger.info(f"[Match] 完了！ image_matches.json を確認してください")


if __name__ == '__main__':
    main()
