import os
import requests
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

# --- 設定項目 ---
LINE_TOKEN = os.environ.get("LINE_TOKEN")
USER_ID = os.environ.get("LINE_USER_ID")
TARGET_AREA = "エリアプライス東京(円/kWh)" # お住まいのエリア
PRICE_LIMIT = 15.0
# --------------

def send_line_message(text):
    """LINEへメッセージを送信する関数（ここはそのまま）"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": text}]}
    requests.post(url, headers=headers, json=payload)

async def main_logic():
    """データ取得から解析までのメイン処理（非同期モード）"""
    send_line_message("【開始通知】\nJEPX価格チェッカーが起動しました。\n現在、最新のデータを取得・解析中です...")
    
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    file_path = ""
    
    try:
        # 非同期モード(async_playwright)でブラウザを起動
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
            await page.wait_for_load_state("networkidle")
            
            # 手順1: 1回目の「データダウンロード」ボタンを押し、モーダルを出す
            dl_buttons = page.locator('text="データダウンロード"')
            await dl_buttons.first.click(force=True)
            await page.wait_for_timeout(1500) # モーダルが開くのを待つ
            
            # 手順2: モーダル内にある2回目のボタンを押してCSVを受け取る
            async with page.expect_download(timeout=60000) as download_info:
                await dl_buttons.last.click(force=True)
                
            download = await download_info.value
            file_path = await download.path()
            await browser.close()
            
    except Exception as e:
        send_line_message(f"【エラー】サイトからのデータダウンロードに失敗しました。\n詳細: {e}")
        return

    # --- CSV解析（ここは通常のPython処理） ---
    try:
        df = pd.read_csv(file_path, encoding="shift_jis")
        
        # エリア名の列が存在するかチェック
        if TARGET_AREA not in df.columns:
            send_line_message(f"【エラー】エリア名「{TARGET_AREA}」がCSV内に見つかりません。")
            return
            
        # 【データ整形】価格や日付が空欄（NaN）の不正な行を事前に除外
        df = df.dropna(subset=["受渡日", TARGET_AREA])
        
        # 日付フォーマットの揺れに対応
        tomorrow_str_padded = tomorrow.strftime("%Y/%m/%d")
        tomorrow_str_unpadded = f"{tomorrow.year}/{tomorrow.month}/{tomorrow.day}"
        
        df_target = df[(df["受渡日"] == tomorrow_str_padded) | (df["受渡日"] == tomorrow_str_unpadded)]
        target_date_str = "明日"
        
        # 明日のデータがない場合は「今日」のデータで代替
        if df_target.empty:
            today_str_padded = now.strftime("%Y/%m/%d")
            today_str_unpadded = f"{now.year}/{now.month}/{now.day}"
            df_target = df[(df["受渡日"] == today_str_padded) | (df["受渡日"] == today_str_unpadded)]
            target_date_str = "今日"
            
            if df_target.empty:
                send_line_message("【エラー】解析可能なデータ（今日・明日）が見つかりませんでした。")
                return

        # 15円以下の時間帯を抽出
        cheap_slots = df_target[df_target[TARGET_AREA] <= PRICE_LIMIT]
        
        if cheap_slots.empty:
            send_line_message(f"【結果報告】\n{target_date_str}は{PRICE_LIMIT}円以下の時間がありませんでした。\n(充電見送り推奨)")
        else:
            # 最安値を取得し、時刻コードを実時間に変換
            min_row = cheap_slots.loc[cheap_slots[TARGET_AREA].idxmin()]
            time_code = int(min_row['時刻コード'])
            hour = (time_code - 1) // 2
            minute = "30" if time_code % 2 == 0 else "00"
            
            message = (
                f"【{target_date_str}の充電推奨】\n"
                f"最安値: {min_row[TARGET_AREA]}円\n"
                f"時間帯: {hour:02d}:{minute}〜\n"
                f"※15円以下は計 {len(cheap_slots)} コマ"
            )
            send_line_message(message)
            
    except Exception as e:
        send_line_message(f"【エラー】CSV解析中にエラーが発生しました。\n詳細: {e}")

if __name__ == "__main__":
    # イベントループの衝突を避けるための実行コマンド
    asyncio.run(main_logic())
