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

async def analyze_page(page, step_name):
    """【診断機能】画面上の「ダウンロード」という文字をすべて収集する"""
    try:
        elements = await page.evaluate('''() => {
            let results = [];
            // ボタンやリンクの中から関連しそうなものを探す
            document.querySelectorAll('a, button, span, div').forEach(el => {
                let txt = el.innerText || "";
                if(txt.includes("ダウンロード") || txt.includes("CSV")) {
                    results.push(`<${el.tagName.toLowerCase()}> ${txt.trim().substring(0, 20)}`);
                }
            });
            return Array.from(new Set(results)); // 重複削除
        }''')
        
        if not elements:
            return f"[{step_name}] 画面上に「ダウンロード」という文字が一切存在しません。"
        return f"[{step_name}] 発見された関連ボタン:\n" + "\n".join(elements[:5])
    except Exception as e:
        return f"[{step_name}] 診断エラー: {e}"

async def main_logic():
    send_line_message("【診断モード起動】\nサイトの構造を解析しながら安全に進行します...")
    
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    file_path = ""
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # サイトが重い場合を考慮し、全体の待機時間を45秒に延長
            page.set_default_timeout(45000)
            
            await page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
            
            # 【対策1】通信が静かになるまで待ち、さらに「強制的に5秒」待機して描画を完了させる
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(5000)
            
            # 【対策2】サイト訪問時に「お知らせ」ポップアップ等が出ているとクリックを邪魔するため消す
            try:
                close_btns = page.get_by_text("閉じる")
                if await close_btns.count() > 0:
                    await close_btns.first.click(timeout=3000)
                    await page.wait_for_timeout(1000)
            except:
                pass # 閉じるボタンがなければ無視

            # 診断チェック1：最初のボタンを押す前の状態を記録
            diag_1 = await analyze_page(page, "アクセス直後")

            # 手順1: 1回目の「データダウンロード」ボタンをクリック
            try:
                # 曖昧検索で確実に文字を捉え、強制クリック（上に透明なバナーがあっても貫通する）
                dl_button_1 = page.get_by_text("データダウンロード").first
                await dl_button_1.scroll_into_view_if_needed(timeout=10000)
                await dl_button_1.click(force=True, timeout=10000)
            except Exception as e:
                # エラー時は「何が見えていたか」の診断結果を添えてLINEに送る
                send_line_message(f"【エラー】1回目のボタンが押せませんでした。\n\n{diag_1}\n\n詳細: {e}")
                await browser.close()
                return

            await page.wait_for_timeout(2000) # モーダルのアニメーションを待つ
            
            # 診断チェック2：モーダルが出た後の状態を記録
            diag_2 = await analyze_page(page, "モーダル展開後")

            # 手順2: 2回目のボタンを押してダウンロード
            try:
                # 画面上に複数ある「データダウンロード」のうち、一番最後（手前に出たモーダル内）を狙う
                dl_button_2 = page.get_by_text("データダウンロード").last
                
                async with page.expect_download(timeout=45000) as download_info:
                    await dl_button_2.click(force=True, timeout=10000)
                    
                download = await download_info.value
                file_path = await download.path()
            except Exception as e:
                send_line_message(f"【エラー】2回目のボタン(CSV保存)が押せませんでした。\n\n{diag_2}\n\n詳細: {e}")
                await browser.close()
                return
                
            await browser.close()
            send_line_message("【報告】CSVデータのダウンロードに成功しました！解析に移行します。")
            
    except Exception as e:
        send_line_message(f"【致命的エラー】Playwrightの操作中に予期せぬエラーが発生しました。\n詳細: {e}")
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
