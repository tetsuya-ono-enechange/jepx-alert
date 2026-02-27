import os
import requests
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

# --- 設定項目 ---
LINE_TOKEN = os.environ.get("LINE_TOKEN")
USER_ID = os.environ.get("LINE_USER_ID")
PRICE_LIMIT = 15.0
# --------------

def send_line_message(text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": text}]}
    requests.post(url, headers=headers, json=payload)

async def main_logic():
    send_line_message("【総当たり探索モード】\n本物のスポット市場データを探し出します...")
    
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    correct_csv_path = None
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_default_timeout(30000)
            
            await page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            # --- カレンダーの必須操作（これをしないと本物のデータが落ちてこない仕様に対応） ---
            try:
                # 日付入力欄をクリックしてカレンダーを開く
                cal_input = page.locator('input[placeholder*="日付"], .flatpickr-input').first
                await cal_input.click(timeout=5000)
                await page.wait_for_timeout(1000)
                # 選択可能な日付（今日など）をクリック
                day_cell = page.locator('.flatpickr-day:not(.prevMonthDay):not(.nextMonthDay)').last
                await day_cell.click(timeout=5000)
                await page.wait_for_timeout(1000)
            except Exception as e:
                pass # カレンダー操作ができなくても続行

            # --- 総当たりダウンロード作戦 ---
            # 「ダウンロード」という文字が含まれるボタンやリンクをすべて取得
            buttons = page.locator('button:has-text("ダウンロード"), a:has-text("ダウンロード")')
            count = await buttons.count()
            
            for i in range(count):
                button = buttons.nth(i)
                try:
                    # ボタンをクリックしてダウンロードを待機
                    async with page.expect_download(timeout=15000) as dl_info:
                        await button.evaluate("node => node.click()")
                        
                    download = await dl_info.value
                    temp_path = f"jepx_candidate_{i}.csv"
                    await download.save_as(temp_path)
                    
                    # ダウンロードしたCSVの中身を確認
                    try:
                        df_temp = pd.read_csv(temp_path, encoding="shift_jis")
                        cols = df_temp.columns.tolist()
                        # スポットデータ特有の列「東京」が含まれているか判定
                        if any("東京" in col for col in cols):
                            correct_csv_path = temp_path
                            break # 正解が見つかったら探索を終了！
                    except Exception as parse_e:
                        continue # CSVじゃなければ次へ
                        
                except Exception as e:
                    continue # ダウンロードが始まらなければ次へ
                    
            await browser.close()
            
    except Exception as e:
        send_line_message(f"【システムエラー】ブラウザ操作中にエラーが発生しました。\n詳細: {e}")
        return

    # 正解のファイルが見つからなかった場合
    if not correct_csv_path:
        send_line_message("【エラー】画面上のすべてのボタンを試しましたが、本物のスポット市場データ（東京）が見つかりませんでした。")
        return

    send_line_message("【解析フェーズ】\n本物のCSVデータの取得に成功しました！解析を行います...")

    # --- CSV解析（正解のファイルを使用） ---
    try:
        df = pd.read_csv(correct_csv_path, encoding="shift_jis")
        columns = df.columns.tolist()
        
        # 「東京」と「プライス」が含まれる列を正確に特定
        target_area = next((col for col in columns if "東京" in col and "プライス" in col), None)
        
        df = df.dropna(subset=["受渡日", target_area])
        
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
                send_line_message("【エラー】CSV内に今日・明日のデータがまだ反映されていません。")
                return

        cheap_slots = df_target[df_target[target_area] <= PRICE_LIMIT]
        
        if cheap_slots.empty:
            send_line_message(f"【結果報告】\n{target_date_str}は{PRICE_LIMIT}円以下の時間がありませんでした。\n(充電見送り推奨)")
        else:
            min_row = cheap_slots.loc[cheap_slots[target_area].idxmin()]
            time_code = int(min_row['時刻コード'])
            hour = (time_code - 1) // 2
            minute = "30" if time_code % 2 == 0 else "00"
            
            message = (
                f"【{target_date_str}の充電推奨】\n"
                f"最安値: {min_row[target_area]}円\n"
                f"時間帯: {hour:02d}:{minute}〜\n"
                f"※15円以下は計 {len(cheap_slots)} コマ"
            )
            send_line_message(message)
            
    except Exception as e:
        send_line_message(f"【エラー】CSV解析中にエラーが発生しました。\n詳細: {e}")

if __name__ == "__main__":
    asyncio.run(main_logic())
