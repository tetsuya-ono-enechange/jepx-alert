import os
import pandas as pd
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# 環境変数からLINEの認証情報を取得
LINE_TOKEN = os.environ.get("LINE_TOKEN")
USER_ID = os.environ.get("LINE_USER_ID")
TARGET_AREA = "エリアプライス東京(円/kWh)" # 対象エリア
PRICE_LIMIT = 15.0

def send_line_message(text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": text}]}
    requests.post(url, headers=headers, json=payload)

def main():
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y/%m/%d")

    # Playwrightでブラウザを自動操作し、CSVをダウンロードする
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
        
        # 「データダウンロード」ボタンをクリックしてCSVを取得（Qiita記事の方式）
        with page.expect_download() as download_info:
            # ※ボタンのテキストは実際のJEPXサイトに合わせています
            page.get_by_text("データダウンロード").first.click()
            
        download = download_info.value
        file_path = download.path()
        browser.close()

    # ダウンロードしたCSVをPandasで解析
    df = pd.read_csv(file_path, encoding="shift_jis")
    
    # 明日のデータを抽出
    df_tomorrow = df[df["受渡日"] == tomorrow_str]
    
    if df_tomorrow.empty:
        print("明日のデータがまだ公開されていません。")
        return

    # 15円以下の時間帯を抽出
    cheap_slots = df_tomorrow[df_tomorrow[TARGET_AREA] <= PRICE_LIMIT]
    
    if cheap_slots.empty:
        send_line_message(f"【蓄電池アラート】\n明日は{PRICE_LIMIT}円以下の時間がありません。")
    else:
        # 最安値を探す
        min_row = cheap_slots.loc[cheap_slots[TARGET_AREA].idxmin()]
        message = (
            f"【明日の充電推奨】\n"
            f"最安値: {min_row[TARGET_AREA]}円\n"
            f"時間帯: {min_row['時刻コード']}枠目\n"
            f"※15円以下は計 {len(cheap_slots)} コマ"
        )
        send_line_message(message)

if __name__ == "__main__":
    main()
