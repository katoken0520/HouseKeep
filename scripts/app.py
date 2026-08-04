import os
import sqlite3
from datetime import date
from flask import Flask, abort, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
    TemplateSendMessage, ButtonsTemplate, PostbackAction, PostbackEvent,
    DatetimePickerAction  # 追加：カレンダーUIを呼び出すアクション
)
from db_manager import DBManager
from dotenv import load_dotenv
load_dotenv()

# LINE Developersで取得したアクセストークンとチャンネルシークレットを設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

app = Flask(__name__)
db = DBManager()

# --- ユーザーの入力状態を一時的に記憶する辞書 ---
user_states = {}

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    profile = line_bot_api.get_profile(user_id)
    member_name = profile.display_name

    confirm_button = QuickReplyButton(action=MessageAction(label="✅ 確定", text="確定"))
    cancel_button = QuickReplyButton(action=MessageAction(label="❌ キャンセル", text="キャンセル"))
    
    if text == "キャンセル":
        if user_id in user_states:
            user_states.pop(user_id, None)
            reply_text = "入力をキャンセルしました。データは登録されていません。"
        else:
            reply_text = "現在、入力中のセッションはありません。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    state = user_states.get(user_id, {"mode": None, "step": 0})

    # ==========================================
    # 初期状態 (メニュー選択)
    # ==========================================
    if state["mode"] is None:
        if text == "支出を入力":
            user_states[user_id] = {"mode": "EXPENSE", "step": 1}
            expense_categories = db.get_categories("expense_categories", True)
            items = [QuickReplyButton(action=MessageAction(label=cat, text=cat)) for cat in expense_categories[:12]]
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="【支出】\n何の支出ですか？項目を選んでください。", quick_reply=QuickReply(items=items)))
            return
            
        elif text == "収入を入力":
            user_states[user_id] = {"mode": "INCOME", "step": 1}
            income_categories = db.get_categories("income_categories", True)
            items = [QuickReplyButton(action=MessageAction(label=cat, text=cat)) for cat in income_categories[:12]]
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="【収入】\n何の収入ですか？項目を選んでください。", quick_reply=QuickReply(items=items)))
            return
            
        elif text == "直近のデータを取り消し":
            transactions = db.get_recent_transactions(user_id, limit=5)
            if not transactions:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="直近のデータはありません。"))
                return
            items = []
            text_lines = ["【直近5件の履歴】\n取り消したいデータのボタンをタップしてください。\n"]
            for i, tx in enumerate(transactions):
                tx_type, tx_id, d, cat, amount = tx
                label = "出" if tx_type == "EXPENSE" else "入"
                text_lines.append(f"{i+1}. [{label}] {cat} {amount:,}円 ({d[-5:]})")
                postback_data = f"delete,{tx_type},{tx_id},{cat},{amount}"
                items.append(QuickReplyButton(action=PostbackAction(label=f"{i+1}番を削除", data=postback_data)))
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(text_lines), quick_reply=QuickReply(items=items)))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="メニューからタップしてください。"))
            return

    # 共通のプレフィックス
    prefix = "【支出】\n" if state["mode"] == "EXPENSE" else "【収入】\n"
    table_name = "expense_categories" if state["mode"] == "EXPENSE" else "income_categories"

    # ==========================================
    # ステップ1: カテゴリーのバリデーション
    # ==========================================
    if state["step"] == 1:
        valid_categories = db.get_categories(table_name, True)
        if text in valid_categories:
            state["category"] = text
            state["step"] = 2
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{prefix}「{text}」ですね。\n次に、金額を「数字のみ」で入力してください。（例：1200）", quick_reply=QuickReply(items=[cancel_button])))
            return
        else:
            items = [QuickReplyButton(action=MessageAction(label=cat, text=cat)) for cat in valid_categories[:12]]
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{prefix}エラー：「{text}」は登録されていない項目です。\n以下のボタンから選択してください。", quick_reply=QuickReply(items=items)))
            return

    # ==========================================
    # ステップ2: 金額入力 ➡️ 日付選択へ
    # ==========================================
    elif state["step"] == 2:
        if text.isdigit():
            state["amount"] = int(text)
            state["step"] = 3
            
            # 今日の日付を初期値に設定
            today_str = date.today().strftime("%Y-%m-%d")
            
            # DatetimePickerActionを使ったカレンダーボタン
            date_picker = QuickReplyButton(
                action=DatetimePickerAction(
                    label="📅 カレンダーから選ぶ",
                    data="set_date",
                    mode="date",
                    initial=today_str
                )
            )
            # 早く入力したい人向けの「今日」ボタン
            today_btn = QuickReplyButton(action=MessageAction(label="今日", text="今日"))
            
            items = [today_btn, date_picker, cancel_button]
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text=f"{prefix}金額: {state['amount']:,}円\n\nいつの記録ですか？", quick_reply=QuickReply(items=items))
            )
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{prefix}エラー：金額は「数字のみ」で入力してください。"))
            return

    # ==========================================
    # ステップ3: 日付のバリデーション (テキストで「今日」と送られた場合)
    # ==========================================
    elif state["step"] == 3:
        if text == "今日":
            state["date"] = date.today().strftime("%Y-%m-%d")
            state["step"] = 4
            items = [confirm_button, cancel_button]
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text=f"{prefix}日付: {state['date']}\n\nよろしければ「確定」を、備考を加える場合はテキストを入力してください。", quick_reply=QuickReply(items=items))
            )
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{prefix}下部のボタンから日付を選択してください。"))
            return

    # ==========================================
    # ステップ4: 備考入力 ＆ 確定
    # ==========================================
    elif state["step"] == 4:
        memo = "" if text == "確定" else text
        
        # db_manager.py はすでに tx_date を受け取れるようになっているため、ここで渡す
        success, detail = db.insert_transaction(
            state["mode"], member_name, user_id, state["category"], state["amount"], memo, tx_date=state["date"]
        )
        if success:
            reply_text = f"【登録完了】\n日付: {state['date']}\n項目: {state['category']}\n金額: {state['amount']:,}円\n備考: {memo}"
        else:
            reply_text = f"データベース登録中にエラーが発生しました。最初からやり直してください。\n原因: {detail}"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        user_states.pop(user_id, None)
        return


# ==========================================
# PostbackEvent ハンドラ (日付選択と削除用)
# ==========================================
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    postback_data = event.postback.data
    
    # 1. カレンダーUIから日付が選択された場合の処理
    if postback_data == "set_date":
        selected_date = event.postback.params['date']
        state = user_states.get(user_id)
        
        if state and state.get("step") == 3:
            state["date"] = selected_date
            state["step"] = 4
            prefix = "【支出】\n" if state["mode"] == "EXPENSE" else "【収入】\n"
            
            items = [
                QuickReplyButton(action=MessageAction(label="✅ 確定", text="確定")),
                QuickReplyButton(action=MessageAction(label="❌ キャンセル", text="キャンセル"))
            ]
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text=f"{prefix}日付: {selected_date}\n\nよろしければ「確定」を、備考を加える場合はテキストを入力してください。", quick_reply=QuickReply(items=items))
            )
        return

    # 2. 直近データの削除処理
    data = postback_data.split(',')
    if data[0] == "delete":
        tx_type = data[1]
        tx_id = int(data[2])
        cat = data[3]
        amount = int(data[4])
        
        success = db.delete_transaction(tx_type, tx_id)
        if success:
            label = "支出" if tx_type == "EXPENSE" else "収入"
            reply_text = f"【削除完了】\n過去の{label}データを取り消しました。\n項目: {cat}\n金額: {amount:,}円"
        else:
            reply_text = "削除処理中にエラーが発生しました。最初からやり直してください。"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == '__main__':
    app.run(port=5000)