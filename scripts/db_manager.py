import os
import sqlite3

class DBManager:
    def __init__(self, db_name='housekeep.db'):
        # 1. このファイルの絶対パスを取得
        current_file_path = os.path.abspath(__file__)
        # 2. scripts の親である housekeep フォルダのパスを取得
        project_root = os.path.dirname(os.path.dirname(current_file_path))
        # 3. db フォルダのパス
        db_dir = os.path.join(project_root, 'db')
        
        # もし db フォルダが存在しなければ自動作成
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        self.db_name = os.path.join(db_dir, db_name)

    def _connect(self):
        conn = sqlite3.connect(self.db_name)
        conn.execute('PRAGMA foreign_keys = ON;')
        return conn

    # =========================================================================
    # 1. メンバー（ユーザー）管理
    # =========================================================================
    def get_or_create_member(self, member_name, line_user_id):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT member_id, member_name FROM members WHERE line_user_id = ?', (line_user_id,))
            row = cursor.fetchone()
            
            if row is None:
                cursor.execute('INSERT INTO members (member_name, line_user_id) VALUES (?, ?)', (member_name, line_user_id))
                member_id = cursor.lastrowid
            else:
                member_id, old_name = row
                if old_name != member_name:
                    cursor.execute('UPDATE members SET member_name = ? WHERE member_id = ?', (member_name, member_id))
            
            conn.commit()
            return member_id
        finally:
            conn.close()

    def get_all_members(self):
        """登録されている全メンバーの名前とLINE_IDを取得する"""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            # 【変更】名前だけでなく、line_user_id も取得する
            cursor.execute("SELECT member_name, line_user_id FROM members")
            return cursor.fetchall()
        finally:
            conn.close()

    # =========================================================================
    # 2. カテゴリー（項目）管理
    # =========================================================================
    def get_categories(self, table_name, only_active=True):
        if table_name not in ['expense_categories', 'income_categories']:
            return []
        
        query = f"SELECT category_name FROM {table_name}"
        if only_active:
            query += " WHERE is_active = 1"
            
        query += " ORDER BY category_id ASC"
            
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            categories = [row[0] for row in cursor.fetchall()]
            
            if "その他" in categories:
                categories.remove("その他")
                categories.append("その他")
                
            # LINEのクイックリプライ上限（キャンセル1個 + 項目12個 = 13個）のため、最大12個に制限
            if only_active:
                return categories[:12]
            return categories
        finally:
            conn.close()

    def add_category(self, table_name, category_name):
        if table_name not in ['expense_categories', 'income_categories']:
            return False, "無効なテーブル名です"
        
        conn = self._connect()
        try:
            cursor = conn.cursor()
            # 現在表示中(is_active=1)の項目数をカウント
            cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE is_active = 1")
            active_count = cursor.fetchone()[0]

            cursor.execute(f"SELECT category_id, is_active FROM {table_name} WHERE category_name = ?", (category_name,))
            row = cursor.fetchone()
            
            if row:
                category_id, is_active = row
                if is_active == 0:
                    if active_count >= 12:
                        return False, "表示中の項目が既に上限の12個に達しています。不要な項目を非表示にしてから再試行してください。"
                    cursor.execute(f"UPDATE {table_name} SET is_active = 1 WHERE category_id = ?", (category_id,))
                    conn.commit()
                    return True, f"「{category_name}」を再表示しました"
                return False, f"「{category_name}」は既に登録されています"
            
            # 新規追加時に表示中項目が12個以上ある場合
            if active_count >= 12:
                return False, "表示中の項目が既に上限の12個に達しています。不要な項目を非表示または削除してから追加してください。"

            cursor.execute(f"INSERT INTO {table_name} (category_name, is_active) VALUES (?, 1)", (category_name,))
            conn.commit()
            return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def rename_category(self, table_name, old_name, new_name):
        """カテゴリーの名前を変更する（重複防止チェック付き）"""
        if table_name not in ['expense_categories', 'income_categories']:
            return False, "無効なテーブル名です"
        
        new_name = new_name.strip()
        if not new_name:
            return False, "新しいカテゴリー名を入力してください。"
        if old_name == new_name:
            return False, "変更前と同じ名前です。"

        conn = self._connect()
        try:
            cursor = conn.cursor()
            # 変更後の名前が既に存在するか確認
            cursor.execute(f"SELECT category_id FROM {table_name} WHERE category_name = ?", (new_name,))
            if cursor.fetchone():
                return False, f"「{new_name}」は既に登録されています。"

            # 名前を変更
            cursor.execute(f"UPDATE {table_name} SET category_name = ? WHERE category_name = ?", (new_name, old_name))
            conn.commit()
            if cursor.rowcount == 0:
                return False, f"「{old_name}」が見つかりませんでした。"
            return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def update_category_visibility(self, table_name, category_name, is_active):
        if table_name not in ['expense_categories', 'income_categories']:
            return False, "無効なテーブル名です"
        
        conn = self._connect()
        try:
            cursor = conn.cursor()
            
            # 非表示(0)から表示(1)に変更する場合の上限チェック
            if is_active:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE is_active = 1")
                active_count = cursor.fetchone()[0]
                
                # 対象カテゴリーの現在の状態を確認
                cursor.execute(f"SELECT is_active FROM {table_name} WHERE category_name = ?", (category_name,))
                row = cursor.fetchone()
                if row and row[0] == 0 and active_count >= 12:
                    return False, "表示中の項目が既に上限の12個に達しています（キャンセルボタンを含めて13個制限のため）。他の項目を非表示にしてから変更してください。"

            cursor.execute(f"UPDATE {table_name} SET is_active = ? WHERE category_name = ?", (1 if is_active else 0, category_name))
            conn.commit()
            if cursor.rowcount == 0:
                return False, f"「{category_name}」が見つかりませんでした"
            return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def delete_category(self, table_name, category_name):
        """
        カテゴリーを完全に削除する。
        ただし、既に支出・収入データに紐付いている場合はエラーを返す安全設計。
        """
        if table_name not in ['expense_categories', 'income_categories']:
            return False, "無効なテーブル名です"

        data_table = 'expenses' if table_name == 'expense_categories' else 'incomes'

        conn = self._connect()
        try:
            cursor = conn.cursor()
            # 1. カテゴリーIDを取得
            cursor.execute(f"SELECT category_id FROM {table_name} WHERE category_name = ?", (category_name,))
            row = cursor.fetchone()
            if not row:
                return False, "指定されたカテゴリーが見つかりません"
            category_id = row[0]

            # 2. データテーブルで既に使用されているか件数をチェック
            cursor.execute(f"SELECT COUNT(*) FROM {data_table} WHERE category_id = ?", (category_id,))
            count = cursor.fetchone()[0]

            if count > 0:
                # 1件でも使われていたら削除ブロック
                return False, f"この項目は既に {count} 件の明細データで使用されているため削除できません。代わりに上のチェックを外して「非表示」にしてください。"

            # 3. 未使用であれば安全に削除実行
            cursor.execute(f"DELETE FROM {table_name} WHERE category_id = ?", (category_id,))
            conn.commit()
            return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    # =========================================================================
    # 3. トランザクション（明細データ）管理
    # =========================================================================
    def insert_transaction(self, tx_type, member_name, line_user_id, category_name, amount, memo="", tx_date=None):
        if tx_type not in ['EXPENSE', 'INCOME']:
            return False, "無効なトランザクションタイプです"
        
        conn = self._connect()
        try:
            cursor = conn.cursor()
            
            # メンバーの確認・登録
            cursor.execute('SELECT member_id, member_name FROM members WHERE line_user_id = ?', (line_user_id,))
            row = cursor.fetchone()
            if row is None:
                cursor.execute('INSERT INTO members (member_name, line_user_id) VALUES (?, ?)', (member_name, line_user_id))
                member_id = cursor.lastrowid
            else:
                member_id, old_name = row
                if old_name != member_name:
                    cursor.execute('UPDATE members SET member_name = ? WHERE member_id = ?', (member_name, member_id))
            
            # カテゴリーIDの取得
            cat_table = 'expense_categories' if tx_type == 'EXPENSE' else 'income_categories'
            cursor.execute(f"SELECT category_id FROM {cat_table} WHERE category_name = ?", (category_name,))
            row = cursor.fetchone()
            if not row:
                return False, f"項目「{category_name}」がマスターに存在しません"
            category_id = row[0]
            
            # データ挿入（tx_dateが指定されていればその日付、なければ現在日時）
            data_table = 'expenses' if tx_type == 'EXPENSE' else 'incomes'
            if tx_date:
                cursor.execute(f"""
                    INSERT INTO {data_table} (date, member_id, category_id, amount, memo)
                    VALUES (?, ?, ?, ?, ?)
                """, (str(tx_date), member_id, category_id, amount, memo))
            else:
                cursor.execute(f"""
                    INSERT INTO {data_table} (date, member_id, category_id, amount, memo)
                    VALUES (date('now', 'localtime'), ?, ?, ?, ?)
                """, (member_id, category_id, amount, memo))
            
            conn.commit()
            return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def get_recent_transactions(self, line_user_id, limit=5):
        """指定されたLINEユーザーの直近のデータを新しい順に取得する（LINE表示用）"""
        query = """
            SELECT 'EXPENSE' as type, e.expense_id as id, e.date, c.category_name, e.amount
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.category_id
            JOIN members m ON e.member_id = m.member_id
            WHERE m.line_user_id = ?
            UNION ALL
            SELECT 'INCOME' as type, i.income_id as id, i.date, c.category_name, i.amount
            FROM incomes i
            JOIN income_categories c ON i.category_id = c.category_id
            JOIN members m ON i.member_id = m.member_id
            WHERE m.line_user_id = ?
            ORDER BY date DESC, id DESC
            LIMIT ?
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            # 引数の ? が3つあるので、順番に (line_user_id, line_user_id, limit) を渡す
            cursor.execute(query, (line_user_id, line_user_id, limit))
            return cursor.fetchall()
        finally:
            conn.close()

    def delete_transaction(self, tx_type, tx_id):
        if tx_type not in ['EXPENSE', 'INCOME']:
            return False, "無効なタイプです"
        
        table_name = 'expenses' if tx_type == 'EXPENSE' else 'incomes'
        id_column = 'expense_id' if tx_type == 'EXPENSE' else 'income_id'
        
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {table_name} WHERE {id_column} = ?", (tx_id,))
            conn.commit()
            return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def update_transaction(self, tx_type, tx_id, category_name, amount, memo):
        if tx_type not in ['EXPENSE', 'INCOME']:
            return False, "無効なタイプです"
        
        table_name = 'expenses' if tx_type == 'EXPENSE' else 'incomes'
        id_column = 'expense_id' if tx_type == 'EXPENSE' else 'income_id'
        cat_table = 'expense_categories' if tx_type == 'EXPENSE' else 'income_categories'
        
        conn = self._connect()
        try:
            cursor = conn.cursor()
            
            cursor.execute(f"SELECT category_id FROM {cat_table} WHERE category_name = ?", (category_name,))
            row = cursor.fetchone()
            if not row:
                return False, f"項目「{category_name}」が存在しません"
            category_id = row[0]
            
            cursor.execute(f"""
                UPDATE {table_name} 
                SET category_id = ?, amount = ?, memo = ?
                WHERE {id_column} = ?
            """, (category_id, amount, memo, tx_id))
            
            conn.commit()
            return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    

    