import os
import requests
import pandas as pd
import io
from datetime import datetime, timedelta

LINE_TOKEN = os.environ.get("LINE_TOKEN")
USER_ID = os.environ.get("LINE_USER_ID")
TARGET_AREA = "エリアプライス東京(円/kWh)"
PRICE_LIMIT = 15.0

def send_line_message(text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": text}]}
    requests.post(url, headers=headers, json=payload)

def main():
    print("--- 実行開始 ---", flush=True)
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    
    # 1. 年度（Fiscal Year）の計算
    # 日本の年度は4月始まり。1〜3月は前年になる（例: 2026年2月 -> 2025年度）
    fiscal_year = tomorrow.year if tomorrow.month >= 4 else tomorrow.year - 1
    
    # 2. 直接CSVのURLを推測して取得を試みる（超高速・確実）
    csv_url = f"https://www.jepx.jp/electricpower/market-data/spot/csv/spot_{fiscal_year}.csv"
    print(f"【方法A】直接ダウンロードを試行: {csv_url}", flush=True)
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    response = requests.get(csv_url, headers=headers)
    
    # 3. もしエラーになった場合、ページからCSVのリンクを自動で探す（バックアップ機能）
    if response.status_code != 200:
        print(f"直接取得に失敗 (Status: {response.status_code})。ページからリンクを検索します...", flush=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
            page.wait_for_load_state("networkidle")
            
            # ページ内のリンク(href)をすべて取得
            hrefs = page.evaluate("Array.from(document.querySelectorAll('a')).map(a => a.href)")
            browser.close()
            
            # 「spot_」が含まれるCSVのリンクを探し出す
            for href in hrefs:
                if "spot_" in href and href.endswith(".csv"):
                    csv_url = href
                    break
        
        print(f"【方法B】ページからリンクを発見: {csv_url}", flush=True)
        response = requests.get(csv_url, headers=headers)

    if response.status_code != 200:
        print("エラー: CSVデータを取得できませんでした。", flush=True)
        return
        
    print("ダウンロード成功！データ解析を開始します...", flush=True)
    
    # CSVデータを読み込む
    df = pd.read_csv(io.BytesIO(response.content), encoding="shift_jis")
    
    # 日付フォーマットの揺れ（ゼロあり・ゼロなし）に両対応
    tomorrow_str_padded = tomorrow.strftime("%Y/%m/%d")
    tomorrow_str_unpadded = f"{tomorrow.year}/{tomorrow.month}/{tomorrow.day}"
    
    df_tomorrow = df[(df["受渡日"] == tomorrow_str_padded) | (df["受渡日"] == tomorrow_str_unpadded)]
    
    if df_tomorrow.empty:
        print("明日のデータがまだ公開されていません。", flush=True)
        return

    # 15円以下の時間帯を抽出
    cheap_slots = df_tomorrow[df_tomorrow[TARGET_AREA] <= PRICE_LIMIT]
    
    if cheap_slots.empty:
        message = f"【蓄電池アラート】\n明日は{PRICE_LIMIT}円以下の時間がありません。"
        send_line_message(message)
        print("通知完了: 15円以下なし", flush=True)
    else:
        # 最安値の行を取得
        min_row = cheap_slots.loc[cheap_slots[TARGET_AREA].idxmin()]
        time_code = int(min_row['時刻コード'])
        hour = (time_code - 1) // 2
        minute = "30" if time_code % 2 == 0 else "00"
        
        message = (
            f"【明日の充電推奨】\n"
            f"最安値: {min_row[TARGET_AREA]}円\n"
            f"時間帯: {hour:02d}:{minute}〜\n"
            f"※15円以下は計 {len(cheap_slots)} コマ"
        )
        send_line_message(message)
        print("通知完了: 成功！", flush=True)

if __name__ == "__main__":
    main()
