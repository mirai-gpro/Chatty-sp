#!/usr/bin/env python3
"""
Gemini Live API「LLMが先に喋れるか」実証スクリプト

目的:
  Chatty-sp の初期あいさつは「LLMは先に喋れない」という前提で
  ダミーのユーザー発話を送る設計になっている。
  この前提が gemini-3.1-flash-live-preview でも成り立つかを実測する。

本スクリプトはアプリ・本番環境に一切影響しない。
LiveAPI に直接接続し、観測して終了するだけ。

使い方:
    pip install google-genai
    export GEMINI_API_KEY=xxxxx          # Windows: set GEMINI_API_KEY=xxxxx
    python tools/test_speak_first.py

    # 個別条件だけ
    python tools/test_speak_first.py --only T2
    # config水準を絞る
    python tools/test_speak_first.py --config minimal
    # 旧モデルと比較
    python tools/test_speak_first.py --model gemini-2.5-flash-native-audio-preview-12-2025

測定条件:
    T1  何も送らない / プロンプトに挨拶指示なし
    T2  何も送らない / プロンプトに挨拶指示あり     ← 最重要（ダミー廃止の可否）
    T3  ダミー発話を send_client_content で送る     ← 現行コードと同じ方式
    T4  ダミー発話を send_realtime_input で送る     ← 3.1 移行ガイド準拠の方式

config水準:
    minimal  response_modalities + system_instruction のみ
    prod     chatty-base/live_api_handler.py の _build_config() と同等
"""

import argparse
import asyncio
import os
import struct
import sys
import time
import wave
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("ERROR: google-genai が入っていません。  pip install google-genai")
    sys.exit(1)

DEFAULT_MODEL = "gemini-3.1-flash-live-preview"
OUT_DIR = Path("speak_first_results")

# 現行コードのダミー発話（live_api_handler.py: INITIAL_GREETING_TRIGGERS['concierge']['ja']）
DUMMY_TEXT = "こんにちは。"

# 挨拶指示なしのプロンプト
PROMPT_NO_GREETING = (
    "あなたは日本語で応答する音声アシスタントです。"
    "1回の発話は50文字以内で簡潔に話してください。"
)

# 挨拶指示ありのプロンプト（公式 best practices の推奨形）
# "include a prompt asking it to greet the user or begin the conversation"
PROMPT_WITH_GREETING = (
    "あなたは日本語で応答する音声アシスタントです。"
    "1回の発話は50文字以内で簡潔に話してください。\n\n"
    "## 初期あいさつ\n"
    "セッションが開始されたら、ユーザーからの入力を待たずに、"
    "あなたから先に日本語で短く挨拶して会話を始めてください。"
)

CASES = {
    "T1": dict(prompt=PROMPT_NO_GREETING,   send=None,               desc="何も送らない / 挨拶指示なし"),
    "T2": dict(prompt=PROMPT_WITH_GREETING, send=None,               desc="何も送らない / 挨拶指示あり ★最重要"),
    "T3": dict(prompt=PROMPT_NO_GREETING,   send="client_content",   desc="ダミー発話 send_client_content（現行方式）"),
    "T4": dict(prompt=PROMPT_NO_GREETING,   send="realtime_input",   desc="ダミー発話 send_realtime_input（移行ガイド準拠）"),
}


def build_config(level: str, system_instruction: str) -> dict:
    """config を組み立てる。prod は _build_config() と同等（tools は除く）"""
    if level == "minimal":
        return {
            "response_modalities": ["AUDIO"],
            "system_instruction": system_instruction,
        }
    # prod: chatty-base/live_api_handler.py の _build_config() を再現
    return {
        "response_modalities": ["AUDIO"],
        "system_instruction": system_instruction,
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "speech_config": {
            "language_code": "ja-JP",
        },
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": False,
                "start_of_speech_sensitivity": "START_SENSITIVITY_HIGH",
                "end_of_speech_sensitivity": "END_SENSITIVITY_HIGH",
                "prefix_padding_ms": 100,
                "silence_duration_ms": 500,
            }
        },
        "context_window_compression": {
            "sliding_window": {
                "target_tokens": 32000,
            }
        },
    }


def save_wav(path: Path, pcm: bytes, rate: int = 24000):
    """LiveAPI 出力は 24kHz 16bit mono PCM"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


async def run_case(client, model: str, case_id: str, level: str, wait_sec: float) -> dict:
    case = CASES[case_id]
    label = f"{case_id}/{level}"
    result = {
        "case": case_id,
        "level": level,
        "desc": case["desc"],
        "connected": False,
        "first_event_s": None,
        "first_audio_s": None,
        "turn_complete_s": None,
        "audio_bytes": 0,
        "transcript": "",
        "error": "",
    }

    config = build_config(level, case["prompt"])
    pcm = bytearray()
    t0 = time.time()

    print(f"\n{'='*70}")
    print(f"[{label}] {case['desc']}")
    print(f"{'='*70}")

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            result["connected"] = True
            print(f"[{label}] 接続成功 ({time.time()-t0:.2f}s)")

            # 送信条件
            if case["send"] == "client_content":
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=DUMMY_TEXT)]),
                    turn_complete=True,
                )
                print(f"[{label}] send_client_content 送信: '{DUMMY_TEXT}'")
            elif case["send"] == "realtime_input":
                await session.send_realtime_input(text=DUMMY_TEXT)
                print(f"[{label}] send_realtime_input 送信: '{DUMMY_TEXT}'")
            else:
                print(f"[{label}] 何も送らずに {wait_sec:.0f} 秒待機します")

            t_send = time.time()

            async def receive_loop():
                async for response in session.receive():
                    now = time.time() - t_send
                    if result["first_event_s"] is None:
                        result["first_event_s"] = now
                        print(f"[{label}] 最初のイベント受信: {now:.2f}s")

                    sc = getattr(response, "server_content", None)
                    if not sc:
                        continue

                    # 出力トランスクリプション
                    ot = getattr(sc, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        result["transcript"] += ot.text

                    # 音声データ
                    mt = getattr(sc, "model_turn", None)
                    if mt:
                        for part in mt.parts:
                            inline = getattr(part, "inline_data", None)
                            if inline and isinstance(inline.data, bytes):
                                if result["first_audio_s"] is None:
                                    result["first_audio_s"] = now
                                    print(f"[{label}] ★ 最初の音声データ: {now:.2f}s")
                                pcm.extend(inline.data)

                    # ターン完了
                    if getattr(sc, "turn_complete", False):
                        result["turn_complete_s"] = now
                        print(f"[{label}] turn_complete: {now:.2f}s")
                        return

            try:
                await asyncio.wait_for(receive_loop(), timeout=wait_sec)
            except asyncio.TimeoutError:
                print(f"[{label}] {wait_sec:.0f} 秒経過（タイムアウト）")

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"[{label}] エラー: {result['error']}")

    result["audio_bytes"] = len(pcm)
    if pcm:
        out = OUT_DIR / f"{case_id}_{level}.wav"
        save_wav(out, bytes(pcm))
        print(f"[{label}] 音声を保存: {out}  ({len(pcm)} bytes / {len(pcm)/48000:.1f}秒)")
    if result["transcript"]:
        print(f"[{label}] 発話内容: {result['transcript']}")

    return result


def print_summary(model: str, results: list):
    print("\n" + "=" * 100)
    print(f"結果サマリ  model = {model}")
    print("=" * 100)
    hdr = f"{'条件':<10}{'config':<10}{'接続':<6}{'初回音声':<10}{'音声量':<12}{'turn_cmp':<10}{'エラー'}"
    print(hdr)
    print("-" * 100)
    for r in results:
        spoke = "★喋った" if r["audio_bytes"] > 0 else "沈黙"
        fa = f"{r['first_audio_s']:.2f}s" if r["first_audio_s"] is not None else "-"
        tc = f"{r['turn_complete_s']:.2f}s" if r["turn_complete_s"] is not None else "-"
        conn = "OK" if r["connected"] else "NG"
        err = (r["error"][:40] + "…") if len(r["error"]) > 40 else r["error"]
        print(f"{r['case']:<10}{r['level']:<10}{conn:<6}{fa:<10}{spoke:<12}{tc:<10}{err}")
    print("-" * 100)

    print("\n【判定】")
    for lvl in ("minimal", "prod"):
        t2 = next((r for r in results if r["case"] == "T2" and r["level"] == lvl), None)
        if t2 is None:
            continue
        if t2["audio_bytes"] > 0:
            print(f"  [{lvl}] T2 で喋った → **ダミー問い掛けは不要にできる可能性が高い**")
        elif t2["error"]:
            print(f"  [{lvl}] T2 でエラー → {t2['error']}")
        else:
            print(f"  [{lvl}] T2 で沈黙 → ダミー問い掛けは依然として必要")

    for lvl in ("minimal", "prod"):
        t3 = next((r for r in results if r["case"] == "T3" and r["level"] == lvl), None)
        t4 = next((r for r in results if r["case"] == "T4" and r["level"] == lvl), None)
        if t3 and t4:
            s3 = t3["audio_bytes"] > 0
            s4 = t4["audio_bytes"] > 0
            if s3 and s4:
                print(f"  [{lvl}] T3/T4 とも喋った → 現行の send_client_content は 3.1 でも動作")
            elif (not s3) and s4:
                print(f"  [{lvl}] T3 沈黙 / T4 喋った → **現行方式が 3.1 で無効。send_realtime_input への移行が必要**")
            elif s3 and (not s4):
                print(f"  [{lvl}] T3 喋った / T4 沈黙 → 現行方式のまま維持すべき")
            else:
                print(f"  [{lvl}] T3/T4 とも沈黙 → 別要因。エラー列を確認")

    print("\n※ 音声は speak_first_results/ に wav で保存されています。実際に聞いて確認してください。")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"既定: {DEFAULT_MODEL}")
    ap.add_argument("--only", default=None, help="T1/T2/T3/T4 のいずれか")
    ap.add_argument("--config", default="both", choices=["minimal", "prod", "both"])
    ap.add_argument("--wait", type=float, default=20.0, help="各条件の待機秒数（既定20）")
    args = ap.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: 環境変数 GEMINI_API_KEY が設定されていません")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    cases = [args.only] if args.only else list(CASES.keys())
    for c in cases:
        if c not in CASES:
            print(f"ERROR: 不明な条件 {c}（T1/T2/T3/T4）")
            sys.exit(1)
    levels = ["minimal", "prod"] if args.config == "both" else [args.config]

    print(f"model  : {args.model}")
    print(f"条件   : {', '.join(cases)}")
    print(f"config : {', '.join(levels)}")
    print(f"待機   : {args.wait:.0f} 秒/条件")
    print(f"合計   : {len(cases)*len(levels)} セッション（各セッションは新規接続）")

    results = []
    for lvl in levels:
        for c in cases:
            results.append(await run_case(client, args.model, c, lvl, args.wait))
            await asyncio.sleep(1.0)   # セッション間の間隔

    print_summary(args.model, results)


if __name__ == "__main__":
    asyncio.run(main())
