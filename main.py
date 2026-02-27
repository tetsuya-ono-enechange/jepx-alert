import os
import requests

def main():
    print("--- 簡易LINE送信テスト ---", flush=True)
    
    # GitHub Secretsから情報を取得
    LINE_TOKEN = os.environ.get("LINE_TOKEN")
    USER_ID = os.environ.get("LINE_USER_ID")
    
    if not LINE_TOKEN or not USER_ID:
        print("【エラー】GitHubのSecretsにTOKENかUSER_IDが設定されていません！", flush=True)
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": USER_ID,
        "messages": [{"type": "text", "text": "【送信テスト】\nこのメッセージが届いていれば、LINE連携は完璧に成功しています！"}]
    }
    
    print("LINE APIへ送信リクエストを送ります...", flush=True)
    response = requests.post(url, headers=headers, json=payload)
    
    print(f"HTTPステータス: {response.status_code}", flush=True)
    print(f"レスポンス詳細: {response.text}", flush=True)
    
    if response.status_code == 200:
        print("✅ APIへの送信は成功しました！スマホを確認してください。", flush=True)
    else:
        print("❌ APIへの送信でエラーが発生しました。", flush=True)

if __name__ == "__main__":
    main()
