import os
from datetime import date
from flask import Flask, abort, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
    PostbackAction, PostbackEvent, DatetimePickerAction
)
from flask import Flask, abort, request, render_template, jsonify
from db_manager import DBManager
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
APP_PASSWORD = os.environ.get('APP_PASSWORD')
ADMIN_APP_URL = os.environ.get('ADMIN_APP_URL')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

app = Flask(__name__)
db = DBManager()

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

# 🌟 関所関数：ユーザーが未登録ならブロックする
def check_user_registration(user_id, current_name, event, text_message=None):
    member_id = db.get_and_sync_member(user_id, current_name)
    
    # 登録済みならTrueを返す
    if member_id:
        return True

    # 未登録の場合：合言葉が送られてきたかチェック
    if text_message and text_message == APP_PASSWORD:
        db.register_member(user_id, current_name)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"認証成功！🎉\n「{current_name}」さん、家計簿Botへようこそ！\nリッチメニューのボタンから操作を開始してください。")
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⛔ 【未認証ユーザー】\nこのBotを利用するには、管理者が設定した「合言葉（パスワード）」を送信して登録を行ってください。")
        )
    return False


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    profile = line_bot_api.get_profile(user_id)
    current_name = profile.display_name

    # 🌟 ここで必ず関所を通す！未登録なら処理を中断
    if not check_user_registration(user_id, current_name, event, text_message=text):
        return

    # --- 以下、既存のロジック（変更なし） ---
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

    if state["mode"] is None:
        if text == "支出を入力":
            user_states[user_id] = {"mode": "EXPENSE", "step": 1}
            expense_categories = db.get_categories("expense_categories", True)
            items = [QuickReplyButton(action=MessageAction(label=cat, text=cat)) for cat in expense_categories]
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="【支出】\n何の支出ですか？項目を選んでください。", quick_reply=QuickReply(items=items)))
            return
        elif text == "収入を入力":
            user_states[user_id] = {"mode": "INCOME", "step": 1}
            income_categories = db.get_categories("income_categories", True)
            items = [QuickReplyButton(action=MessageAction(label=cat, text=cat)) for cat in income_categories]
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="【収入】\n何の収入ですか？項目を選んでください。", quick_reply=QuickReply(items=items)))
            return
        elif text == "直近のデータを取り消し":
            transactions = db.get_recent_transactions(user_id, limit=5)
            if not transactions:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="直近のデータはありません。"))
                return
            items = []
            text_lines = ["【直近5件の履歴】\n消したいデータのボタンをタップしてください。\n"]
            for i, tx in enumerate(transactions):
                tx_type, tx_id, d, cat, amount = tx
                label = "出" if tx_type == "EXPENSE" else "入"
                text_lines.append(f"{i+1}. [{label}] {cat} {amount:,}円 ({d[-5:]})")
                postback_data = f"delete,{tx_type},{tx_id},{cat},{amount}"
                items.append(QuickReplyButton(action=PostbackAction(label=f"{i+1}番を削除", data=postback_data)))
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(text_lines), quick_reply=QuickReply(items=items)))
            return
        elif text == "30日間の総括":
            summary = db.get_monthly_summary(user_id)
            total_shared, user_shared = db.get_monthly_shared_stats(user_id)
            
            if not summary and total_shared == 0:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="過去30日間の支出データはありません。"))
                return
            
            total_amount = sum(row[1] for row in summary) if summary else 0
            text_lines = [
                "📊 【過去30日間のあなたの支出総括】",
                f"💰 総支払額: {total_amount:,}円",
                "----------------------",
                "📂 項目別内訳:"
            ]
            
            if summary:
                for cat, amount in summary:
                    percentage = (amount / total_amount) * 100
                    text_lines.append(f"・{cat}: {amount:,}円 ({percentage:.1f}%)")
            else:
                text_lines.append("・支払記録はありません")
                
            text_lines.append("----------------------")
            text_lines.append("👪 【共有会計の負担状況】")
            
            if total_shared > 0:
                share_percentage = (user_shared / total_shared) * 100
                text_lines.append(f"全体の共有支出: {total_shared:,}円")
                text_lines.append(f"あなたの負担額: {user_shared:,}円 ({share_percentage:.1f}%)")
            else:
                text_lines.append("・共有支出の記録はありません")
                
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(text_lines)))
            return
        elif text == "管理者サイトのURLを表示":
            reply_text = f"💻 管理者用システムはこちらです👇\n{ADMIN_APP_URL}\n\n※ログインにはパスワードが必要です。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="メニューからタップしてください。"))
            return

    prefix = "【支出】\n" if state["mode"] == "EXPENSE" else "【収入】\n"
    table_name = "expense_categories" if state["mode"] == "EXPENSE" else "income_categories"

    if state["step"] == 1:
        valid_categories = db.get_categories(table_name, True)
        if text in valid_categories:
            state["category"] = text
            state["step"] = 2
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{prefix}「{text}」ですね。\n次に、金額を「数字のみ」で入力してください。\n（例：1200）", quick_reply=QuickReply(items=[cancel_button])))
            return
        else:
            items = [QuickReplyButton(action=MessageAction(label=cat, text=cat)) for cat in valid_categories]
            items.append(cancel_button)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{prefix}エラー：「{text}」は登録されていない項目です。\n以下のボタンから選択してください。", quick_reply=QuickReply(items=items)))
            return

    elif state["step"] == 2:
        # 💡 全角・半角スペースを取り除いて解析しやすくする
        input_text = text.replace(" ", "").replace(" ", "")
        is_shared = 0

        # 先頭の「共有」や「共」をチェック
        if input_text.startswith("共有"):
            is_shared = 1
            input_text = input_text[2:] # 「共有」を取り除く
        elif input_text.startswith("共"):
            is_shared = 1
            input_text = input_text[1:] # 「共」を取り除く

        if input_text.isdigit():
            state["amount"] = int(input_text)
            state["is_shared"] = is_shared # 💡 判定結果をステートに保存
            state["step"] = 3
            today_str = date.today().strftime("%Y-%m-%d")
            date_picker = QuickReplyButton(
                action=DatetimePickerAction(label="📅 カレンダーから選ぶ", data="set_date", mode="date", initial=today_str)
            )
            today_btn = QuickReplyButton(action=MessageAction(label="今日", text="今日"))
            items = [today_btn, date_picker, cancel_button]
            
            # 確認メッセージに共有/個人を表示
            shared_str = "👪 共有用" if is_shared == 1 else "👤 個人用"
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text=f"{prefix}{shared_str} / 金額: {state['amount']:,}円\n\nいつの記録ですか？", quick_reply=QuickReply(items=items))
            )
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{prefix}エラー：金額は「数字のみ」または「共(空白)数字」で入力してください。"))
            return

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

    elif state["step"] == 4:
        memo = "" if text == "確定" else text
        is_shared = state.get("is_shared", 0) # 💡 ステートからフラグを取得（収入の時はデフォルト0になるので安全）

        # 💡 引数に is_shared を追加
        success, detail = db.insert_transaction(
            state["mode"], current_name, user_id, state["category"], state["amount"], memo, tx_date=state["date"], is_shared=is_shared
        )
        if success:
            shared_str = "👪 共有用" if is_shared == 1 else "👤 個人用"
            reply_text = f"【登録完了】\n区分: {shared_str}\n日付: {state['date']}\n項目: {state['category']}\n金額: {state['amount']:,}円\n備考: {memo}"
        else:
            reply_text = f"データベース登録中にエラーが発生しました。最初からやり直してください。\n原因: {detail}"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        user_states.pop(user_id, None)
        return

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    profile = line_bot_api.get_profile(user_id)
    current_name = profile.display_name
    
    # 🌟 ボタン操作時も未登録ならブロック
    if not check_user_registration(user_id, current_name, event):
        return

    postback_data = event.postback.data
    
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

# pingを送り続けることでrenderサーバーを寝かさない。cronjobを使用。
@app.route('/')
def index():
    return 'Render is awake!'

# =========================================================================
# 🌐 LIFF 画面用ルーティング＆API
# =========================================================================

# 1. LIFF 画面本体（HTML）の返却
@app.route('/liff')
def liff_page():
    return render_template('liff.html')

# 2. カテゴリー一覧の取得API
@app.route('/api/categories', methods=['GET'])
def api_get_categories():
    tx_type = request.args.get('type', 'expense_categories')
    categories = db.get_categories(tx_type, only_active=True)
    return jsonify({"status": "success", "categories": categories})

# 3. トランザクション（支出・収入）の追加API
@app.route('/api/transaction', methods=['POST'])
def api_add_transaction():
    data = request.json
    user_id = data.get('user_id')
    tx_type = data.get('type') # 'EXPENSE' or 'INCOME'
    category = data.get('category')
    amount = int(data.get('amount', 0))
    memo = data.get('memo', '')
    tx_date = data.get('date')
    is_shared = int(data.get('is_shared', 0))

    # ユーザー名取得（またはDB検索）
    # ※ 本来はLINE APIから名前を取るかDBのmembersから引く
    conn = db._connect()
    with conn.cursor() as cursor:
        cursor.execute("SELECT member_name FROM members WHERE line_user_id = %s", (user_id,))
        row = cursor.fetchone()
        current_name = row[0] if row else "Guest"
    conn.close()

    success, detail = db.insert_transaction(
        tx_type, current_name, user_id, category, amount, memo, tx_date=tx_date, is_shared=is_shared
    )
    if success:
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": detail}), 400

# 4. 直近の履歴取得API
@app.route('/api/recent', methods=['GET'])
def api_get_recent():
    user_id = request.args.get('user_id')
    transactions = db.get_recent_transactions(user_id, limit=5)
    # transactions: [(type, id, date, cat, amount), ...]
    res = []
    for tx in transactions:
        res.append({
            "type": tx[0],
            "id": tx[1],
            "date": tx[2],
            "category": tx[3],
            "amount": tx[4]
        })
    return jsonify({"status": "success", "transactions": res})

# 5. 履歴削除API
@app.route('/api/delete', methods=['POST'])
def api_delete():
    data = request.json
    tx_type = data.get('type')
    tx_id = data.get('id')
    success, detail = db.delete_transaction(tx_type, tx_id)
    if success:
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": detail}), 400

# 6. 30日間サマリー取得API
@app.route('/api/summary', methods=['GET'])
def api_get_summary():
    user_id = request.args.get('user_id')
    summary = db.get_monthly_summary(user_id)
    total_shared, user_shared = db.get_monthly_shared_stats(user_id)
    
    total_amount = sum(row[1] for row in summary) if summary else 0
    categories = [{"name": row[0], "amount": row[1]} for row in summary] if summary else []
    
    return jsonify({
        "status": "success",
        "total_amount": total_amount,
        "categories": categories,
        "total_shared": total_shared,
        "user_shared": user_shared
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

