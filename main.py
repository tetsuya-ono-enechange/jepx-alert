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
    response = requests.post(url, headers=headers, json=payload)
    print("LINE送信結果:", response.text)

def main():
    # 明日の日付を YYYY/MM/DD 形式で取得 (JEPXのCSV内の形式に合わせる)
    # ※日付のゼロ埋めが不要な場合は "%Y/%-m/%-d" に変更が必要な場合があります
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y/%m/%d")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # サイトが重い場合を考慮し、全体のタイムアウトを60秒に延長
        page.set_default_timeout(60000)
        
        print("JEPXのサイトにアクセスしています...")
        page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
        
        # 【修正1】JavaScriptのグラフ等が完全に描画されるまで待機する
        print("ページの読み込み完了を待機中...")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000) # 念のためさらに5秒待機
        
        # 【修正2】「データダウンロード」ボタンを正確に狙う
        # ボタンタグまたはリンクタグの中にあるテキストを探す
        download_button = page.locator('button:has-text("データダウンロード"), a:has-text("データダウンロード")').first
        download_button.scroll_into_view_if_needed()
        
        print("ダウンロードボタンをクリックします...")
        with page.expect_download(timeout=60000) as download_info:
            # 【修正3】他の要素が被っていても強制的にクリック(force=True)する
            download_button.click(force=True)
            
        download = download_info.value
        file_path = download.path()
        print(f"ダウンロード成功: {file_path}")
        browser.close()

    # ダウンロードしたCSVをPandasで解析
    df = pd.read_csv(file_path, encoding="shift_jis")
    
    # 明日のデータを抽出
    df_tomorrow = df[df["受渡日"] == tomorrow_str]
    
    if df_tomorrow.empty:
        print(f"明日のデータ ({tomorrow_str}) がまだ公開されていません。")
        return

    # 15円以下の時間帯を抽出
    cheap_slots = df_tomorrow[df_tomorrow[TARGET_AREA] <= PRICE_LIMIT]
    
    if cheap_slots.empty:
        send_line_message(f"【蓄電池アラート】\n明日は{PRICE_LIMIT}円以下の時間がありません。")
