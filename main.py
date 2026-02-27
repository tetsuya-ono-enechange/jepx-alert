import os
import requests
import pandas as pd
import io
import traceback
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
    # 1. 起動したことを即座にLINEへ通知
    send_line_message("【デバッグ実行】\nプログラムが起動しました。JEPXデータを取得します...")
    
    try:
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        fiscal_year = tomorrow.year if tomorrow.month >= 4 else tomorrow.year - 1
        
        csv_url = f"https://www.jepx.jp/electricpower/market-data/spot/csv/spot_{fiscal_year}.csv"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(csv_url, headers=headers)
        
        if response.status_code != 200:
            send_line_message(f"【エラー】CSVの取得に失敗しました。(Status: {response.status_code})")
            return
            
        df = pd.read_csv(io.BytesIO(response.content), encoding="shift_jis")
        
        # ターゲットエリアのカラムが存在するか確認
        if TARGET_AREA not in df.columns:
            send_line_message(f"【エラー】エリア名「{TARGET_AREA}」がCSV内に見つかりません。\n設定を確認してください。")
            return

        # 最新の日付を特定
        latest_date = df["受渡日"].iloc[-1]
        
        tomorrow_str_padded = tomorrow.strftime("%Y/%m/%d")
        tomorrow_str_unpadded = f"{tomorrow.year}/{tomorrow.month}/{tomorrow.day}"
        
        df_target = df[(df["受渡日"] == tomorrow_str_padded) | (df["受渡日"] == tomorrow_str_unpadded)]
        target_date_str = "明日"
        
        # もし明日のデータがなければ、今日のデータで代用する
        if df_target.empty:
            send_line_message(f"【報告】明日のデータがまだ公開されていません。\n(CSV内の最新日付: {latest_date})\n\n代わりに『今日』のデータで判定を行います。")
            
            today_str_padded = now.strftime("%Y/%m/%d")
            today_str_unpadded = f"{now.year}/{now.month}/{now.day}"
            df_target = df[(df["受渡日"] == today_str_padded) | (df["受渡日"] == today_str_unpadded)]
            target_date_str = "今日"
            
            if df_target.empty:
                send_line_message("【エラー】今日のデータも見つかりませんでした。処理を終了します。")
                return

        # 15円以下の時間帯を抽出
        cheap_slots = df_target[df_target[TARGET_AREA] <= PRICE_LIMIT]
        
        if cheap_slots.empty:
            send_line_message(f"【結果報告】\n{target_date_str}は{PRICE_LIMIT}円以下の時間がありませんでした。\n(充電見送り推奨)")
        else:
            min_row = cheap_slots.loc[cheap_slots[TARGET_AREA].idxmin()]
            time_code = int(min_row['時刻コード'])
            hour = (time_code - 1) // 2
            minute = "30" if time_code % 2 == 0 else "00"
            
            msg = (
                f"【{target_date_str}の充電推奨】\n"
                f"最安値: {min_row[TARGET_AREA]}円\n"
                f"時間帯: {hour:02d}:{minute}〜\n"
                f"※15円以下は計 {len(cheap_slots)} コマ"
            )
            send_line_message(msg)

    except Exception as e:
        # 万が一プログラムがエラーで落ちた場合も、原因をLINEに送る
        send_line_message(f"【システムエラー発生】\nプログラム内でエラーが起きました:\n{e}")

if __name__ == "__main__":
    main()
