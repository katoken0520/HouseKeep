import pandas as pd
from datetime import datetime, date
import os
import streamlit as st
from db_manager import DBManager
from dotenv import load_dotenv

# .envの読み込み（ローカル実行用）
load_dotenv()

# Streamlitのページ基本設定
st.set_page_config(page_title="家計簿管理システム", layout="wide")

# =========================================================================
# 🔒 ログイン認証機能
# =========================================================================
def check_password():
    """正しいパスワードが入力されているか検証し、未認証ならログイン画面を表示して処理を止める"""
    
    # 既に認証済みの場合は True を返して後続の処理を続行
    if st.session_state.get("password_correct", False):
        return True

    # ログイン画面の表示
    st.title("🔒 家計簿管理システム - ログイン")
    st.write("アクセスするには管理者用パスワードを入力してください。")

    # パスワード入力フォーム
    input_password = st.text_input("パスワード", type="password", key="password_input")
    
    if st.button("ログイン"):
        # 環境変数（.env または Streamlit Secrets）からパスワードを取得
        # ※ Streamlit Cloud では st.secrets からも参照できます
        target_password = os.environ.get("ADMIN_APP_PASSWORD")
        if not target_password and "ADMIN_APP_PASSWORD" in st.secrets:
            target_password = st.secrets["ADMIN_APP_PASSWORD"]

        # パスワードの判定
        if input_password == target_password:
            st.session_state["password_correct"] = True
            st.rerun()  # 画面を再読み込みして本来の管理画面を表示
        else:
            st.error("パスワードが正しくありません。")

    return False

# 🌟 関所の実行：認証に成功していなければ、ここでプログラムの実行を停止（以下の描画を行わない）
if not check_password():
    st.stop()

# =========================================================================
# 📊 これより下が本来のメイン画面（認証成功時のみ実行される）
# =========================================================================
# （※ sidebar に「ログアウト」ボタンを置いておくと便利です）
if st.sidebar.button("🔒 ログアウト"):
    st.session_state["password_correct"] = False
    st.rerun()

db = DBManager()

def load_data(tx_type):
    # 【変更】sqlite3 ではなく、db_manager のクラウド接続を使用
    conn = db._connect()
    try:
        if tx_type == "EXPENSE":
            query = """
                SELECT e.expense_id AS "ID", e.date AS "日付", m.member_name AS "入力者",
                       c.category_name AS "項目", e.amount AS "金額", e.memo AS "備考"
                FROM expenses e
                JOIN members m ON e.member_id = m.member_id
                JOIN expense_categories c ON e.category_id = c.category_id
                ORDER BY e.date DESC, e.expense_id DESC
            """
        else:
            query = """
                SELECT i.income_id AS "ID", i.date AS "日付", m.member_name AS "入力者",
                       c.category_name AS "項目", i.amount AS "金額", i.memo AS "備考"
                FROM incomes i
                JOIN members m ON i.member_id = m.member_id
                JOIN income_categories c ON i.category_id = c.category_id
                ORDER BY i.date DESC, i.income_id DESC
            """
        # PostgreSQLからデータを取得してPandasデータフレームに変換
        with conn.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(rows, columns=cols)
        return df
    finally:
        conn.close()

tab1, tab2, tab3 = st.tabs(["📊 データ一覧・修正・削除", "➕ データ手動追加", "⚙️ カテゴリーマスター管理"])

# =========================================================================
# タブ1: データ一覧・修正・削除
# =========================================================================
with tab1:
    st.header("データ明細の閲覧と編集")
    
    mode = st.radio("データ種別", ["支出", "収入"], horizontal=True)
    tx_type = "EXPENSE" if mode == "支出" else "INCOME"
    table_name = "expense_categories" if mode == "支出" else "income_categories"
    
    df = load_data(tx_type)
    
    if df.empty:
        st.info("データがありません。")
    else:
        # 日付文字列・オブジェクトをdatetime型に変換
        df["日付"] = pd.to_datetime(df["日付"]).dt.date
        min_date = df["日付"].min()
        max_date = df["日付"].max()

        st.subheader("🔍 フィルター条件")
        c1, c2, c3, c4 = st.columns(4)
        
        with c1:
            date_range = st.date_input("期間で絞り込み", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        with c2:
            filter_member = st.multiselect("入力者で絞り込み", options=df["入力者"].unique())
        with c3:
            filter_cat = st.multiselect("項目で絞り込み", options=df["項目"].unique())
        with c4:
            search_memo = st.text_input("備考欄のキーワード検索")
            
        df_filtered = df.copy()
        
        if isinstance(date_range, tuple):
            if len(date_range) == 2:
                df_filtered = df_filtered[(df_filtered["日付"] >= date_range[0]) & (df_filtered["日付"] <= date_range[1])]
            elif len(date_range) == 1:
                df_filtered = df_filtered[df_filtered["日付"] == date_range[0]]
                
        if filter_member:
            df_filtered = df_filtered[df_filtered["入力者"].isin(filter_member)]
        if filter_cat:
            df_filtered = df_filtered[df_filtered["項目"].isin(filter_cat)]
        if search_memo:
            df_filtered = df_filtered[df_filtered["備考"].str.contains(search_memo, na=False)]
            
        st.subheader(f"データ一覧（全 {len(df_filtered)} 件）")
        st.dataframe(df_filtered, use_container_width=True, hide_index=True)
        
        st.write("---")
        st.subheader("📝 選択したデータの修正・削除")
        
        selected_id = st.selectbox("操作するデータの ID を選択してください", options=df_filtered["ID"].unique())
        
        if selected_id:
            row = df[df["ID"] == selected_id].iloc[0]
            with st.form("edit_form"):
                st.write(f"データID: {selected_id} の編集")
                all_cats = db.get_categories(table_name, only_active=False)
                default_cat_idx = all_cats.index(row["項目"]) if row["項目"] in all_cats else 0
                
                new_cat = st.selectbox("項目", options=all_cats, index=default_cat_idx)
                new_amount = st.number_input("金額", value=int(row["金額"]), step=100)
                new_memo = st.text_input("備考", value=str(row["備考"] if pd.notna(row["備考"]) else ""))
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    submit_update = st.form_submit_button("✨ 変更を保存する", use_container_width=True)
                with col_btn2:
                    submit_delete = st.form_submit_button("🗑️ このデータを削除する", use_container_width=True)
                    
                if submit_update:
                    success, msg = db.update_transaction(tx_type, selected_id, new_cat, new_amount, new_memo)
                    if success:
                        st.success("データを更新しました！")
                        st.rerun()
                    else:
                        st.error(f"エラー: {msg}")
                        
                if submit_delete:
                    success, msg = db.delete_transaction(tx_type, selected_id)
                    if success:
                        st.success("データを削除しました。")
                        st.rerun()
                    else:
                        st.error(f"エラー: {msg}")

# =========================================================================
# タブ2: データ手動追加
# =========================================================================
with tab2:
    st.header("データの新規追加")
    
    with st.form("add_transaction_form"):
        add_mode = st.radio("種別", ["支出", "収入"], horizontal=True, key="add_mode")
        add_tx_type = "EXPENSE" if add_mode == "支出" else "INCOME"
        add_table_name = "expense_categories" if add_mode == "支出" else "income_categories"
        
        input_date = st.date_input("日付", value=date.today())
        
        members = db.get_all_members()
        if members:
            member_dict = {}
            for name, line_id in members:
                line_id_str = str(line_id)
                if line_id_str.startswith("pc_user_") and name in member_dict:
                    continue
                member_dict[name] = line_id_str
                
            unique_names = list(member_dict.keys())
            input_member = st.selectbox("入力者名", options=unique_names)
            target_line_id = member_dict[input_member]
        else:
            input_member = st.text_input("入力者名 (初回のみ)", value="Keita Kato")
            target_line_id = "pc_user_initial"
            
        active_cats = db.get_categories(add_table_name, only_active=True)
        input_cat = st.selectbox("項目 (現在有効な選択肢)", options=active_cats)
        input_amount = st.number_input("金額", min_value=0, step=100, value=0)
        input_memo = st.text_input("備考（メモ）")
        
        submit_add = st.form_submit_button("🚀 データを登録")
        
        if submit_add:
            if input_amount <= 0:
                st.error("金額は1円以上で入力してください。")
            elif not input_cat:
                st.error("項目を選択してください。")
            else:
                success, msg = db.insert_transaction(
                    add_tx_type, input_member, target_line_id, input_cat, input_amount, input_memo, tx_date=input_date
                )
                if success:
                    st.success(f"【登録完了】 {input_date} / {input_cat} : {input_amount:,}円 を登録しました。")
                else:
                    st.error(f"登録エラー: {msg}")

# =========================================================================
# タブ3: カテゴリーマスター管理
# =========================================================================
with tab3:
    st.header("カテゴリーマスター（項目）の管理")
    
    cat_mode = st.radio("マスター種別", ["支出項目", "収入項目"], horizontal=True)
    target_table = "expense_categories" if cat_mode == "支出項目" else "income_categories"
    
    # 【変更】sqlite3 ではなく、db_manager のクラウド接続を使用
    conn = db._connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT category_name, is_active FROM {target_table} ORDER BY category_id ASC")
            cat_rows = cursor.fetchall()
    finally:
        conn.close()
    
    active_count = sum(1 for _, is_active in cat_rows if is_active == 1)
    
    if active_count >= 12:
        st.warning(f"⚠️ 現在表示中の項目数: **{active_count} / 12 個** (LINE上限に達しています)")
    else:
        st.info(f"💡 現在表示中の項目数: **{active_count} / 12 個** (あと {12 - active_count} 個追加可能)")
    
    c_add, c_rename, c_vis, c_del = st.columns([1, 1.2, 1, 1.2])
    
    with c_add:
        st.subheader("➕ 項目の追加")
        new_cat_name = st.text_input("追加する項目名")
        if st.button("カテゴリーを追加", use_container_width=True):
            if new_cat_name.strip():
                success, msg = db.add_category(target_table, new_cat_name.strip())
                if success:
                    st.success(f"「{new_cat_name}」を追加しました。")
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("名前を入力してください。")

    with c_rename:
        st.subheader("✏️ 項目の名称変更")
        if cat_rows:
            all_cat_names = [row[0] for row in cat_rows]
            target_rename = st.selectbox("変更する項目", options=all_cat_names, key="rename_select")
            renamed_name = st.text_input("新しい項目名", value=target_rename, key="rename_input")
            
            if st.button("名前を変更する", use_container_width=True):
                success, msg = db.rename_category(target_table, target_rename, renamed_name)
                if success:
                    st.success(f"「{target_rename}」を「{renamed_name}」に変更しました。")
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.info("カテゴリーがありません。")

    with c_vis:
        st.subheader("👁️ 表示切替")
        if cat_rows:
            st.write("LINEでの表示/非表示")
            for cat_name, is_active in cat_rows:
                checked = st.checkbox(cat_name, value=(is_active == 1), key=f"chk_{target_table}_{cat_name}")
                if checked != (is_active == 1):
                    success, msg = db.update_category_visibility(target_table, cat_name, checked)
                    if success:
                        st.success(f"「{cat_name}」の表示状態を更新しました。")
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.info("カテゴリーがありません。")

    with c_del:
        st.subheader("🗑️ 完全削除")
        st.write("※明細で未使用の項目のみ")
        
        if cat_rows:
            all_cat_names = [row[0] for row in cat_rows]
            delete_target = st.selectbox("削除する項目", options=all_cat_names, key="del_select")
            
            if st.button("⚠️ 選択項目を削除", type="primary", use_container_width=True):
                success, msg = db.delete_category(target_table, delete_target)
                if success:
                    st.success(f"「{delete_target}」を削除しました。")
                    st.rerun()
                else:
                    st.error(msg)