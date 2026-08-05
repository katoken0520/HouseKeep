import os
import json
from datetime import date
from flask import Flask, abort, request, render_template, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
from db_manager import DBManager
from dotenv import load_dotenv

# 💡 新しい公式ライブラリをインポート
from google import genai
from google.genai import types

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

# 💡 新しい公式ライブラリでの初期化
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

# =========================================================================
# 💬 LINE テキストメッセージの処理
# =========================================================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    profile = line_bot_api.get_profile(user_id)
    current_name = profile.display_name

    if not check_user_registration(user_id, current_name, event, text_message=text):
        return

    if text == "管理者サイトのURLを表示":
        reply_text = f"💻 管理者用システムはこちらです👇\n{ADMIN_APP_URL}\n\n※ログインにはパスワードが必要です。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return
        
    elif text == "確定":
        state = user_states.pop(user_id, None)
        if state and state.get("status") == "pending_ai":
            ai_data = state["data"]
            success, detail = db.insert_transaction(
                ai_data['type'], 
                current_name, 
                user_id, 
                ai_data['category'], 
                ai_data['amount'], 
                ai_data['memo'], 
                tx_date=date.today().strftime("%Y-%m-%d"), 
                is_shared=ai_data['is_shared']
            )
            if success:
                reply_text = "🎯 データベースに正常に記録しました！"
            else:
                reply_text = f"❌ データの保存に失敗しました。\n{detail}"
        else:
            reply_text = "確認待ちのデータがありません。メニューからフォームを開いて入力してください📱"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    elif text == "キャンセル":
        user_states.pop(user_id, None)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="登録をキャンセルしました。"))
        return

    if not client:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="AIの初期設定が完了していません。"))
        return

    # 💡 抽出ルールの作成
    active_exp_cats = db.get_categories('expense_categories', only_active=True)
    system_prompt = f"""
    あなたは優秀な家計簿アシスタントです。ユーザーの入力テキストから家計簿データを抽出し、以下のJSONフォーマットのみを出力してください。余計な文章や装飾は一切不要です。

    【抽出ルール】
    - type: 支出なら "EXPENSE"、収入なら "INCOME"
    - category: 以下のリストから最も意味が近いものを1つ選ぶこと。
      {active_exp_cats}
    - amount: 金額を数値（整数）のみで抽出。
    - is_shared: 共有の支払い（「共」「共有」「二人で」など）なら 1、個人の支払いなら 0。指定がなければ 0。
    - memo: 買った場所、決済方法、品物など。なければ空文字 ""。

    【出力JSON例】
    {{"type": "EXPENSE", "category": "食費", "amount": 600, "is_shared": 0, "memo": "コンビニ弁当"}}
    """

    try:
        # 💡 新しいライブラリを使ったクリーンな呼び出し
        response = client.models.generate_content(
            model='models/gemini-2.5-flash',
            contents=text, # ユーザーの入力テキスト
            config=types.GenerateContentConfig(
                system_instruction=system_prompt, # システムプロンプトを分離して指定
            )
        )
        
        json_text = response.text.strip().replace('```json', '').replace('```', '')
        ai_data = json.loads(json_text)
        
        user_states[user_id] = {
            "status": "pending_ai",
            "data": ai_data
        }
        
        tx_label = "支出" if ai_data['type'] == 'EXPENSE' else "収入"
        shared_str = "👪 共有用" if ai_data['is_shared'] == 1 else "👤 個人用"
        
        confirm_text = (
            f"🤖 AI解析結果:\n"
            f"----------------------\n"
            f"種別: {tx_label}\n"
            f"区分: {shared_str}\n"
            f"項目: {ai_data['category']}\n"
            f"金額: {ai_data['amount']:,}円\n"
            f"備考: {ai_data['memo'] if ai_data['memo'] else 'なし'}\n"
            f"----------------------\n"
            f"この内容で登録しますか？"
        )
        
        quick_reply_items = [
            QuickReplyButton(action=MessageAction(label="✅ 確定", text="確定")),
            QuickReplyButton(action=MessageAction(label="❌ キャンセル", text="キャンセル"))
        ]
        
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text=confirm_text, quick_reply=QuickReply(items=quick_reply_items))
        )

    except Exception as e:
        print(f"AI Parsing Error: {e}")
        user_states.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="うまく読み取れませんでした💦\n下部のメニューから「入力フォーム」を開いて手動で登録してください📱")
        )

# =========================================================================
# 🌟 Render起床用 (cron-job.org) & LINE Webhook
# =========================================================================
@app.route('/')
def index():
    return 'Render is awake!'

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 🌟 関所関数
def check_user_registration(user_id, current_name, event, text_message=None):
    member_id = db.get_and_sync_member(user_id, current_name)
    if member_id:
        return True

    if text_message and text_message == APP_PASSWORD:
        db.register_member(user_id, current_name)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"認証成功！🎉\n「{current_name}」さん、家計簿Botへようこそ！\nメニューからフォームを開いてください。")
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⛔ 【未認証ユーザー】\n合言葉（パスワード）を送信してください。")
        )
    return False


# =========================================================================
# 🌐 LIFF 画面用ルーティング＆API
# =========================================================================
@app.route('/liff')
def liff_page():
    return render_template('liff.html')

@app.route('/api/categories', methods=['GET'])
def api_get_categories():
    tx_type = request.args.get('type', 'expense_categories')
    categories = db.get_categories(tx_type, only_active=True)
    return jsonify({"status": "success", "categories": categories})

@app.route('/api/transaction', methods=['POST'])
def api_add_transaction():
    data = request.json
    user_id = data.get('user_id')
    tx_type = data.get('type') 
    category = data.get('category')
    amount = int(data.get('amount', 0))
    memo = data.get('memo', '')
    tx_date = data.get('date')
    is_shared = int(data.get('is_shared', 0))

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
        # 💡 【追加】登録完了後、LINEのトーク画面にフィードバックを送信
        try:
            tx_label = "支出" if tx_type == 'EXPENSE' else "収入"
            shared_str = "👪 共有用" if (tx_type == 'EXPENSE' and is_shared == 1) else "👤 個人用" if tx_type == 'EXPENSE' else ""
            
            reply_text = f"【{tx_label}を登録しました】\n"
            if shared_str:
                reply_text += f"区分: {shared_str}\n"
            reply_text += f"日付: {tx_date}\n項目: {category}\n金額: {amount:,}円"
            if memo:
                reply_text += f"\n備考: {memo}"
                
            line_bot_api.push_message(user_id, TextSendMessage(text=reply_text))
        except Exception as e:
            print(f"Push Message Error: {e}")
            
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": detail}), 400

@app.route('/api/recent', methods=['GET'])
def api_get_recent():
    user_id = request.args.get('user_id')
    transactions = db.get_liff_transactions(user_id, limit=100)
    res = []
    for tx in transactions:
        res.append({
            "type": tx[0], "id": tx[1], "date": tx[2], 
            "category": tx[3], "amount": tx[4], "is_shared": tx[5]
        })
    return jsonify({"status": "success", "transactions": res})

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

@app.route('/api/send_monthly_report', methods=['GET'])
def send_monthly_report():
    # セキュリティ対策：パラメーターに正しい合言葉が含まれていないと実行しない
    req_key = request.args.get('key')
    if req_key != APP_PASSWORD:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    members = db.get_all_members()
    # "pc_user_" から始まる初期データ等を除外し、実際のLINEユーザーIDだけを抽出
    real_users = list(set([m[1] for m in members if not str(m[1]).startswith('pc_user_')]))
    
    send_count = 0
    for user_id in real_users:
        stats = db.get_monthly_report_stats(user_id)
        if not stats:
            continue # 先月の記録が1件もない人はスキップ
            
        last_total = stats['last_month_total']
        avg_total = stats['past_avg_total']
        
        msg_lines = [
            "📊 【先月の家計簿レポート】",
            f"先月の総支出は {last_total:,}円 でした！"
        ]
        
        # 平均との比較メッセージ
        if avg_total == 0:
            msg_lines.append("（過去のデータが貯まると、平均との比較ができるようになります💡）")
        elif last_total <= avg_total:
            diff = avg_total - last_total
            msg_lines.append(f"過去の平均 {avg_total:,}円 より {diff:,}円 の節約です✨")
            msg_lines.append("今月もこの調子でいきましょう！")
        else:
            diff = last_total - avg_total
            msg_lines.append(f"過去の平均 {avg_total:,}円 より {diff:,}円 オーバーしました📈")
            msg_lines.append("いつもよりいいお買い物をしましたね！")
            
        msg_lines.append("")
        msg_lines.append("📂 多く使った項目トップ3:")
        
        # トップ3の整形
        for i, cat in enumerate(stats['top_categories'], 1):
            cat_avg = cat['past_avg']
            avg_str = f"平均: {cat_avg:,}円" if cat_avg > 0 else "過去データなし"
            msg_lines.append(f"{i}. {cat['name']}: {cat['amount']:,}円")
            msg_lines.append(f"（{avg_str}）")
            
        try:
            line_bot_api.push_message(user_id, TextSendMessage(text="\n".join(msg_lines)))
            send_count += 1
        except Exception as e:
            print(f"Error sending report to {user_id}: {e}")
            
    return jsonify({"status": "success", "sent_count": send_count})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)