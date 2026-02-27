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
    """LINEへメッセージを送信する関数"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": text}]}
    requests.post(url, headers=headers, json=payload)

async def main_logic():
    send_line_message("【開始通知】\nJEPX価格チェッカーが起動しました。\n最新データを取得しています...")
    
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    file_path = ""
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
            await page.wait_for_load_state("networkidle")
            
            # 【重要修正】ダミーを避け、画面に見えている本物のボタンだけを狙う
            
            # 手順1: 1回目の「データダウンロード」ボタン（メイン画面のボタン）
            # クラス名やリンク構造で明確に指定します
            first_dl_button = page.locator('a.btn-download, a:has-text("データダウンロード")').first
            await first_dl_button.scroll_into_view_if_needed()
            await first_dl_button.click(force=True)
            
            # モーダル（ポップアップ画面）が開くのを確実に待つ
            await page.wait_for_timeout(2000) 
            
            # 手順2: モーダル内にある2回目の「データダウンロード」ボタン
            # モーダル領域（.modal, .dialog など）の中にあるボタンを狙うのが確実ですが、
            # サイト構造が不明確な場合を考慮し、「画面上に表示されている（visible）」ボタンを狙う
            second_dl_button = page.locator('button:has-text("データダウンロード"):visible, a:has-text("データダウンロード"):visible').last
            
            async with page.expect_download(timeout=60000) as download_info:
                await second_dl_button.click(force=True)
                
            download = await download_info.value
            file_path = await download.path()
            await browser.close()
            
    except Exception as e:
        send_line_message(f"【エラー】サイトからのデータダウンロードに失敗しました。\n詳細: {e}")
        return

    # --- CSV解析 ---
    try:
        df = pd.read_csv(file_path, encoding="shift_jis")
        
        if TARGET_AREA not in df.columns:
            send_line_message(f"【エラー】エリア名「{TARGET_AREA}」がCSV内に見つかりません。")
            return
            
        df = df.dropna(subset=["受渡日", TARGET_AREA])
        
        tomorrow_str_padded = tomorrow.strftime("%Y/%m/%d")
        tomorrow_str_unpadded = f"{tomorrow.year}/{tomorrow.month}/{tomorrow.day}"
        
        df_target = df[(df["受渡日"] == tomorrow_str_padded) | (df["受渡日"] == tomorrow_str_unpadded)]
        target_date_str = "明日"
        
        if df_target.empty:
            today_str_padded = now.strftime("%Y/%m/%d")
            today_str_unpadded = f"{now.year}/{now.month}/{now.day}"
            df_target = df[(df["受渡日"] == today_str_padded) | (df["受渡日"] == today_str_unpadded)]
            target_date_str = "今日"
            
            if df_target.empty:
                send_line_message("【エラー】解析可能なデータ（今日・明日）が見つかりませんでした。")
                return

        cheap_slots = df_target[df_target[TARGET_AREA] <= PRICE_LIMIT]
        
        if cheap_slots.empty:
            send_line_message(f"【結果報告】\n{target_date_str}は{PRICE_LIMIT}円以下の時間がありませんでした。\n(充電見送り推奨)")
        else:
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
    asyncio.run(main_logic())
