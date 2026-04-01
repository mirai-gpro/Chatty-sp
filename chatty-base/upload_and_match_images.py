#!/usr/bin/env python3
"""
ローカル画像をSupabase Storageにアップロードし、Geminiでメニュー名とマッチングする

使い方:
  python upload_and_match_images.py kfc
  python upload_and_match_images.py kfc --match-only   (アップロード済みの場合)

環境変数:
  GEMINI_API_KEY: Gemini APIキー
  SUPABASE_URL: Supabase URL
  SUPABASE_SERVICE_KEY: Supabase Service Role Key

入力:
  menu_data/{shop_id}/images/  — ローカル画像フォルダ
  menu_data/{shop_id}/{shop_id}_menu.md — メニューMarkdown

出力:
  menu_data/{shop_id}/image_matches.json — マッチング結果（手動修正用）
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
        name = match.group(1).strip()
        if name not in names:
            names.append(name)

    logger.info(f"[Upload] Markdownからメニュー名 {len(names)}品 抽出（重複除去済み）")
    return names


def upload_images_to_supabase(shop_id: str) -> list[dict]:
    """ローカル画像をSupabase Storageにアップロード"""
    from supabase import create_client

    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        logger.error("[Upload] SUPABASE_URL/KEY未設定")
        sys.exit(1)

    supabase = create_client(url, key)
    images_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, 'images')

    if not os.path.isdir(images_dir):
        logger.error(f"[Upload] 画像フォルダが見つかりません: {images_dir}")
        sys.exit(1)

    image_files = sorted([
        f for f in os.listdir(images_dir)
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
    ])
    logger.info(f"[Upload] ローカル画像: {len(image_files)}枚")

    uploaded = []
    for i, filename in enumerate(image_files):
        filepath = os.path.join(images_dir, filename)
        # 拡張子をjpgに統一
        base_name = os.path.splitext(filename)[0]
        storage_path = f"{shop_id}/hp_{base_name}.jpg"

        with open(filepath, 'rb') as f:
            img_bytes = f.read()

        # 画像をJPEGに変換（webp等の場合）
        if not filename.lower().endswith(('.jpg', '.jpeg')):
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(img_bytes))
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=90)
                img_bytes = buf.getvalue()
            except Exception as e:
                logger.warning(f"[Upload] 変換失敗 {filename}: {e}")

        try:
            supabase.storage.from_('menu').upload(
                storage_path,
                img_bytes,
                file_options={"content-type": "image/jpeg", "upsert": "true"}
            )
            public_url = f"{url}/storage/v1/object/public/menu/{storage_path}"
            uploaded.append({
                'file_name': f"hp_{base_name}.jpg",
                'original_name': filename,
                'url': public_url,
            })
            logger.info(f"[Upload] {i+1}/{len(image_files)}: {filename} → {storage_path}")
        except Exception as e:
            logger.warning(f"[Upload] アップロード失敗 {filename}: {e}")

    logger.info(f"[Upload] アップロード完了: {len(uploaded)}/{len(image_files)}枚")
    return uploaded


def match_image_to_menu(image_url: str, menu_names: list[str], client) -> dict:
    """1枚の画像をGeminiに見せてメニュー名とマッチング"""
    from google.genai import types

    menu_list = '\n'.join([f"{i+1}. {name}" for i, name in enumerate(menu_names)])

    prompt = f"""この画像はファストフード店のメニュー写真です。
以下のメニューリストの中から、この画像に最も合致するメニューを1つだけ選んでください。

【メニューリスト】
{menu_list}

【回答形式】JSON形式のみ出力。それ以外のテキストは不要。
{{"menu_number": 番号（整数）, "menu_name": "選んだメニュー名", "confidence": 確信度（0-100の整数）, "reason": "判断理由を1行で"}}
"""

    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash-lite',
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


def run_upload_and_match(shop_id: str, match_only: bool = False):
    """アップロード＋マッチングを実行"""
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

    # 2. 画像アップロード or 既存結果から取得
    output_dir = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id)
    output_path = os.path.join(output_dir, 'image_matches.json')

    if match_only and os.path.exists(output_path):
        # 既存jsonからhp_画像のみ取得
        with open(output_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        images = [
            {'file_name': r['image_file'], 'url': r['image_url']}
            for r in existing if r['image_file'].startswith('hp_')
        ]
        logger.info(f"[Match] 既存jsonからHP画像: {len(images)}枚")
        if not images:
            logger.info("[Match] HP画像が見つかりません。--match-onlyなしで再実行してください。")
            return
    else:
        images = upload_images_to_supabase(shop_id)

    # 3. 1枚ずつマッチング
    results = []
    for i, img in enumerate(images):
        logger.info(f"[Match] {i+1}/{len(images)}: {img['file_name']} をマッチング中...")
        match = match_image_to_menu(img['url'], menu_names, client)
        match['image_file'] = img['file_name']
        match['image_url'] = img['url']
        match['original_name'] = img.get('original_name', img['file_name'])
        match['status'] = 'ok' if match.get('confidence', 0) >= 70 else 'review'
        results.append(match)

        # レート制限対策
        if (i + 1) % 3 == 0:
            time.sleep(2)

    # 4. 結果を保存
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"[Match] マッチング結果保存: {output_path}")

    # 5. サマリー
    ok_count = sum(1 for r in results if r['status'] == 'ok')
    review_count = sum(1 for r in results if r['status'] == 'review')
    logger.info(f"[Match] 完了: {len(results)}枚中 OK={ok_count}, 要レビュー={review_count}")

    # 6. マッチング結果をMarkdownに反映
    apply_matches_to_markdown(shop_id, results)

    return results


def apply_matches_to_markdown(shop_id: str, results: list[dict]):
    """マッチング結果をMarkdownの画像URLに反映（confidence >= 70のみ）"""
    md_path = os.path.join(os.path.dirname(__file__), 'menu_data', shop_id, f'{shop_id}_menu.md')
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # メニュー名→正しい画像URLのマッピングを構築
    name_to_url = {}
    for r in results:
        if r.get('confidence', 0) >= 70 and r.get('menu_name'):
            # 同名メニューは高い confidence を優先
            existing = name_to_url.get(r['menu_name'])
            if not existing or r['confidence'] > existing['confidence']:
                name_to_url[r['menu_name']] = r

    # Markdownの各メニューアイテムの画像URLを差し替え
    lines = content.split('\n')
    new_lines = []
    current_menu_name = None
    replaced_count = 0

    for line in lines:
        title_match = re.match(r'^###\s+(.+)', line)
        if title_match:
            current_menu_name = title_match.group(1).strip()
            new_lines.append(line)
            continue

        img_match = re.match(r'^!\[(.+?)\]\((.+?)\)', line)
        if img_match and current_menu_name and current_menu_name in name_to_url:
            correct_url = name_to_url[current_menu_name]['image_url']
            new_lines.append(f'![{current_menu_name}]({correct_url})')
            replaced_count += 1
            continue

        new_lines.append(line)

    new_content = '\n'.join(new_lines)

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    logger.info(f"[Match] Markdown画像URL差し替え完了: {replaced_count}品")


def main():
    if len(sys.argv) < 2:
        print("使い方: python upload_and_match_images.py <shop_id> [--match-only]")
        print("  例: python upload_and_match_images.py kfc")
        print("  例: python upload_and_match_images.py kfc --match-only")
        sys.exit(1)

    shop_id = sys.argv[1]
    match_only = '--match-only' in sys.argv

    logger.info(f"[Upload] {shop_id} のHP画像アップロード＋マッチング開始")
    run_upload_and_match(shop_id, match_only=match_only)
    logger.info(f"[Upload] 完了！ image_matches.json を確認して手動修正してください")


if __name__ == '__main__':
    main()
