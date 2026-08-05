import os
from datetime import date
from flask import Flask, abort, request, render_template, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, MessageAction, QuickReplyButton, QuickReply
from db_manager import DBManager
import google.generativeai as genai
import json
from dotenv import load_dotenv
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
APP_PASSWORD = os.environ.get('APP_PASSWORD')
ADMIN_APP_URL = os.environ.get('ADMIN_APP_URL')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_states = {}

app = Flask(__name__)
db = DBManager()

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

    print("=== 🟢 使用可能なAIモデル一覧 🟢 ===")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(m.name)
    except Exception as e:
        print(f"モデル一覧取得エラー: {e}")
    print("====================================")
    
    # DBから現在有効なカテゴリー一覧をあらかじめ取得してシステムプロンプトに埋め込む
    active_exp_cats = db.get_categories('expense_categories', only_active=True)
    
    # 🌟 ここに概要やルールをすべて詰め込みます
    system_prompt = f"""
    あなたは家計簿アシスタントです。
    ユーザーの入力テキストから毎度、家計簿項目を推測して指定のJSONフォーマットのみを出力してください。
    余計な文章や解説、```json などのマークダウン装飾は一切不要です。
    必ず純粋なJSON文字列だけを返してください。
    
    ただし、ユーザーの入力テキストが明らかに家計簿への記帳ではない場合は、以下のJSONフォーマットのみを出力してください。
    {{"type": "", "category": "", "amount": 0, "is_shared": 0, "memo": ""}}

    【抽出ルール】
    - type: 支出なら "EXPENSE"、収入なら "INCOME"
    - category: 有効な項目のリストが収入、支出それぞれに対し与えられるので、その中から最も適する物を一つ選び、valueは文字列とする。このカテゴリーは毎回変わる可能性がある。
      （例: INCOME: ["給与", "配当・利子", "その他"], EXPENSE: ["食費", "日用品", "その他"])
    - amount: 金額を数値（整数）のみで抽出。
    - is_shared: ユーザーが家族であることを想定して、共有の支払いとすべきなら 1、個人の支払いなら 0とする。スーパーでの買い物などが共有の代表例である。曖昧ならば 0とする。
    - memo: 日常的な買いもであれば空文字 ""とする。特殊ケースと思われる場合はここに備考として日本語の文字列を定める。
    - date: 日付を文字列で書く。分からない場合は入力されたtodayと同じものを出力とする。（例: 2026-08-06）

    【入力例】
    【text】
    昨日、旅行先でご飯、2000円
    【active_category】
    INCOME: ["給与", "配当・利子", "その他"], EXPENSE: ["食費", "日用品", "その他"]
    【today】
    2026-08-06

    【出力例】
    {{"type": "EXPENSE", "category": "食費", "amount": 2000, "is_shared": 1, "memo": "旅行先での食事", "date": "2026-08-05"}}
    """
    
    # モデル作成時に指示文を渡す
    model = genai.GenerativeModel(
        model_name='gemini-1.5-flash',
        system_instruction=system_prompt
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
# 💬 LINE テキストメッセージの処理（LIFF移行により大幅縮小！）
# =========================================================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    profile = line_bot_api.get_profile(user_id)
    current_name = profile.display_name

    if not check_user_registration(user_id, current_name, event, text_message=text):
        return

    # 管理者URLの呼び出しなどは既存のまま
    if text == "管理者サイトのURLを表示":
        reply_text = f"💻 管理者用システムはこちらです👇\n{ADMIN_APP_URL}\n\n※ログインにはパスワードが必要です。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 前のステップでのAIからの解答
    state = user_states.pop(user_id, None)
    if state and state.get("status") == "pending_ai":
        if text == "確定":
            ai_data = state["data"]
            success, detail = db.insert_transaction(
                ai_data['type'], 
                current_name, 
                user_id, 
                ai_data['category'], 
                ai_data['amount'], 
                ai_data['memo'], 
                ai_data["date"], 
                ai_data['is_shared'])
            if success:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✨ データを保存しました！"))
                return
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"データの保存に失敗しました。\n{detail}"))
                return
        elif text == "キャンセル":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"データの保存をキャンセルしました。"))
            return
        else:
            user_states[user_id] = {"status": "pending_ai", "data": ai_data}
            
            confirm_text = f"""
            🤖 AI解析結果:
            ----------------------
            種別: {"支出" if ai_data['type'] == "EXPENSE" else "収入"}
            区分: {"共有用" if ai_data['is_shared'] == 1 else "個人用"}
            項目: {ai_data['category']}
            金額: {ai_data['amount']:,}円
            備考: {ai_data['memo'] if ai_data['memo'] else 'なし'}
            ----------------------
            この内容で家計簿に登録してもよろしいですか？"""
            quick_reply_items = [QuickReplyButton(action=MessageAction(label="✅ 確定", text="確定")), QuickReplyButton(action=MessageAction(label="❌ キャンセル", text="キャンセル"))]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=confirm_text, quick_reply=QuickReply(items=quick_reply_items)))
            return

    # 💡 ここからAIによる自然言語解析
    # DBから現在有効なカテゴリー一覧を取得してAIに教える
    active_exp_cats = db.get_categories('expense_categories', only_active=True)
    active_inc_cats = db.get_categories('income_categories', only_active=True)
    
    prompt = f"""
    【text】
    {text}
    【active_category】
    INCOME: {active_inc_cats}, EXPENSE: {active_exp_cats}
    【today】
    {date.today().strftime("%Y-%m-%d")}
    """

    try:
        response = model.generate_content(prompt)
        json_text = response.text.strip()
        ai_data = json.loads(json_text)

        if ai_data['type'] == "":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"AIがあなたのメッセージから収支項目を判断します！（1日1500回まで）\n「昨日、スーパーで1000円」などと送信してみてください！"))
            return
        else:
            user_states[user_id] = {"status": "pending_ai", "data": ai_data}

            confirm_text = f"""
            🤖 AI解析結果:
            ----------------------
            種別: {"支出" if ai_data['type'] == "EXPENSE" else "収入"}
            区分: {"共有用" if ai_data['is_shared'] == 1 else "個人用"}
            項目: {ai_data['category']}
            金額: {ai_data['amount']:,}円
            備考: {ai_data['memo'] if ai_data['memo'] else 'なし'}
            ----------------------
            この内容で家計簿に登録してもよろしいですか？"""
            quick_reply_items = [QuickReplyButton(action=MessageAction(label="✅ 確定", text="確定")), QuickReplyButton(action=MessageAction(label="❌ キャンセル", text="キャンセル"))]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=confirm_text, quick_reply=QuickReply(items=quick_reply_items)))
            return

    except Exception as e:
        print(f"AI Parsing Error: {e}")
        # AIがうまく解析できなかった場合はLIFFへ誘導
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"うまく読み取れませんでした💦\n下部のメニューから「入力フォーム」を開いて手動で登録してください📱\n\nエラー: {e}"))
        return

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