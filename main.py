import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# 環境変数から取得
LINE_TOKEN = os.environ.get("LINE_TOKEN")
USER_ID = os.environ.get("LINE_USER_ID")
TARGET_AREA = "エリアプライス東京(円/kWh)"
PRICE_LIMIT = 15.0

def send_line_message(text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": text}]}
    response = requests.post(url, headers=headers, json=payload)
    
    # 確実に出力させる
    print(f"◆LINE送信結果(ステータス): {response.status_code}", flush=True)
    print(f"◆LINE送信結果(詳細): {response.text}", flush=True)

def main():
    print("--- 実行開始 ---", flush=True)
    
    # 【最重要テスト】まずは無条件でテストメッセージを送る
    print("LINEの接続テストを開始します...", flush=True)
    send_line_message("【システムテスト】プログラムが正常に起動しました。")

    tomorrow = datetime.now() + timedelta(days=1)
    tomorrow_str_padded = tomorrow.strftime("%Y/%m/%d")
    tomorrow_str_unpadded = f"{tomorrow.year}/{tomorrow.month}/{tomorrow.day}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(60000)
        
        print("JEPXのサイトにアクセスしています...", flush=True)
        page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
        
        print("ページの読み込み完了を待機中...", flush=True)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)
        
        download_button = page.locator('button:has-text("データダウンロード"), a:has-text("データダウンロード")').first
        download_button.scroll_into_view_if_needed()
        
        print("ダウンロードボタンをクリックします...", flush=True)
        with page.expect_download(timeout=60000) as download_info:
            download_button.click(force=True)
            
        file_path = download_info.value.path()
        print("ダウンロード成功", flush=True)
        browser.close()

    df = pd.read_csv(file_path, encoding="shift_jis")
    df_tomorrow = df[(df["受渡日"] == tomorrow_str_padded) | (df["受渡日"] == tomorrow_str_unpadded)]
    
    if df_tomorrow.empty:
        print("明日のデータがまだ公開されていません。", flush=True)
        return

    cheap_slots = df_tomorrow[df_tomorrow[TARGET_AREA] <= PRICE_LIMIT]
    
    if cheap_slots.empty:
        send_line_message(f"明日は{PRICE_LIMIT}円以下の時間がありません。")
        print("通知完了（15円以下なし）", flush=True)
    else:
        min_row = cheap_slots.loc[cheap_slots[TARGET_AREA].idxmin()]
        time_code = int(min_row['時刻コード'])
        hour = (time_code - 1) // 2
        minute = "30" if time_code % 2 == 0 else "00"
        
        message = (
            f"【明日の充電推奨】\n最安値: {min_row[TARGET_AREA]}円\n"
            f"時間帯: {hour:02d}:{minute}〜\n※15円以下は計 {len(cheap_slots)} コマ"
        )
        send_line_message(message)
        print("通知完了（価格あり）", flush=True)

if __name__ == "__main__":
    main()
