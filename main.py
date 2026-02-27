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
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": text}]}
    requests.post(url, headers=headers, json=payload)

async def main_logic():
    send_line_message("【最終チェック】\nファイルの保存処理を修正し、解析を実行します...")
    
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    
    # 【対策】消されないように保存先ファイル名を明確に指定
    saved_file_path = "jepx_spot.csv"
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_default_timeout(45000)
            
            await page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(5000)

            # 手順1: 1回目のボタン強制クリック
            try:
                dl_button_1 = page.locator('button:has-text("データダウンロード")').first
                await dl_button_1.evaluate("node => node.click()")
            except Exception as e:
                send_line_message(f"【エラー】1回目のボタンが押せませんでした。\n詳細: {e}")
                await browser.close()
                return

            await page.wait_for_timeout(2000)

            # 手順2: 2回目のボタン強制クリック
            try:
                dl_button_2 = page.locator('button:has-text("データダウンロード")').last
                async with page.expect_download(timeout=45000) as download_info:
                    await dl_button_2.evaluate("node => node.click()")
                    
                download = await download_info.value
                
                # 【ここが最重要の修正点】ブラウザを閉じる前に、安全な場所に保存する！
                await download.save_as(saved_file_path)
                
            except Exception as e:
                send_line_message(f"【エラー】2回目のボタン(CSV保存)が押せませんでした。\n詳細: {e}")
                await browser.close()
                return
                
            await browser.close()
            send_line_message("【報告】CSVデータの確実な保存に成功しました！解析に移行します。")
            
    except Exception as e:
        send_line_message(f"【致命的エラー】Playwrightの操作中にエラーが発生しました。\n詳細: {e}")
        return

    # --- CSV解析 ---
    try:
        # さきほど保存したファイルを読み込む
        df = pd.read_csv(saved_file_path, encoding="shift_jis")
        
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
