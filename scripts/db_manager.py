import os
import psycopg2
from datetime import date
from dotenv import load_dotenv

load_dotenv()

class DBManager:
    def __init__(self):
        self.db_uri = os.environ.get('SUPABASE_URI')

    def _connect(self):
        return psycopg2.connect(self.db_uri)

    # =========================================================================
    # 1. メンバー（ユーザー）管理と認証
    # =========================================================================
    def get_all_members(self):
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT member_name, line_user_id FROM members")
                return cursor.fetchall()
        finally:
            conn.close()

    def get_and_sync_member(self, line_user_id, current_name):
        """メンバーが登録済みか確認し、LINE名が変わっていればDBを自動更新する"""
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT member_id, member_name FROM members WHERE line_user_id = %s", (line_user_id,))
                row = cursor.fetchone()
                if row:
                    member_id, old_name = row
                    # 💡 LINEの表示名が変わっていたら更新！
                    if old_name != current_name:
                        cursor.execute("UPDATE members SET member_name = %s WHERE member_id = %s", (current_name, member_id))
                        conn.commit()
                    return member_id
                return None
        finally:
            conn.close()

    def register_member(self, line_user_id, member_name):
        """パスワード正解時に新規メンバーとして登録する"""
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO members (member_name, line_user_id) VALUES (%s, %s)", (member_name, line_user_id))
                conn.commit()
                return True
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    # =========================================================================
    # 2. カテゴリー（項目）管理 (変更なし)
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
            with conn.cursor() as cursor:
                cursor.execute(query)
                categories = [row[0] for row in cursor.fetchall()]
                if "その他" in categories:
                    categories.remove("その他")
                    categories.append("その他")
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
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE is_active = 1")
                active_count = cursor.fetchone()[0]
                cursor.execute(f"SELECT category_id, is_active FROM {table_name} WHERE category_name = %s", (category_name,))
                row = cursor.fetchone()
                if row:
                    category_id, is_active = row
                    if is_active == 0:
                        if active_count >= 12:
                            return False, "表示中の項目が既に上限の12個に達しています。"
                        cursor.execute(f"UPDATE {table_name} SET is_active = 1 WHERE category_id = %s", (category_id,))
                        conn.commit()
                        return True, f"「{category_name}」を再表示しました"
                    return False, f"「{category_name}」は既に登録されています"
                if active_count >= 12:
                    return False, "表示中の項目が既に上限の12個に達しています。"
                cursor.execute(f"INSERT INTO {table_name} (category_name, is_active) VALUES (%s, 1)", (category_name,))
                conn.commit()
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
            with conn.cursor() as cursor:
                if is_active:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE is_active = 1")
                    active_count = cursor.fetchone()[0]
                    cursor.execute(f"SELECT is_active FROM {table_name} WHERE category_name = %s", (category_name,))
                    row = cursor.fetchone()
                    if row and row[0] == 0 and active_count >= 12:
                        return False, "表示中の項目が上限の12個に達しています。"
                cursor.execute(f"UPDATE {table_name} SET is_active = %s WHERE category_name = %s", (1 if is_active else 0, category_name))
                conn.commit()
                if cursor.rowcount == 0:
                    return False, f"「{category_name}」が見つかりませんでした"
                return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def rename_category(self, table_name, old_name, new_name):
        if table_name not in ['expense_categories', 'income_categories']:
            return False, "無効なテーブル名です"
        new_name = new_name.strip()
        if not new_name or old_name == new_name:
            return False, "無効な名前です。"
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT category_id FROM {table_name} WHERE category_name = %s", (new_name,))
                if cursor.fetchone():
                    return False, f"「{new_name}」は既に登録されています。"
                cursor.execute(f"UPDATE {table_name} SET category_name = %s WHERE category_name = %s", (new_name, old_name))
                conn.commit()
                return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def delete_category(self, table_name, category_name):
        if table_name not in ['expense_categories', 'income_categories']:
            return False, "無効なテーブル名です"
        data_table = 'expenses' if table_name == 'expense_categories' else 'incomes'
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT category_id FROM {table_name} WHERE category_name = %s", (category_name,))
                row = cursor.fetchone()
                if not row:
                    return False, "指定されたカテゴリーが見つかりません"
                category_id = row[0]
                cursor.execute(f"SELECT COUNT(*) FROM {data_table} WHERE category_id = %s", (category_id,))
                count = cursor.fetchone()[0]
                if count > 0:
                    return False, f"この項目は既に {count} 件の明細データで使用されているため削除できません。"
                cursor.execute(f"DELETE FROM {table_name} WHERE category_id = %s", (category_id,))
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
    def insert_transaction(self, tx_type, member_name, line_user_id, category_name, amount, memo="", tx_date=None, is_shared=0):
        if tx_type not in ['EXPENSE', 'INCOME']:
            return False, "無効なトランザクションタイプです"
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT member_id FROM members WHERE line_user_id = %s', (line_user_id,))
                row = cursor.fetchone()
                if row is None:
                    return False, "未登録のユーザーからの送信のため拒否されました。"
                member_id = row[0]
                
                cat_table = 'expense_categories' if tx_type == 'EXPENSE' else 'income_categories'
                cursor.execute(f"SELECT category_id FROM {cat_table} WHERE category_name = %s", (category_name,))
                row = cursor.fetchone()
                if not row:
                    return False, f"項目「{category_name}」がマスターに存在しません"
                category_id = row[0]
                
                target_date = tx_date if tx_date else date.today()
                
                # 💡 支出と収入でINSERT文を分岐（is_sharedは支出のみ）
                if tx_type == 'EXPENSE':
                    cursor.execute("""
                        INSERT INTO expenses (date, member_id, category_id, amount, memo, is_shared)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (target_date, member_id, category_id, amount, memo, is_shared))
                else:
                    cursor.execute("""
                        INSERT INTO incomes (date, member_id, category_id, amount, memo)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (target_date, member_id, category_id, amount, memo))
                
                conn.commit()
                return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def get_recent_transactions(self, line_user_id, limit=5):
        query = """
            SELECT 'EXPENSE' as type, e.expense_id as id, TO_CHAR(e.date, 'YYYY-MM-DD') as date, c.category_name, e.amount
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.category_id
            JOIN members m ON e.member_id = m.member_id
            WHERE m.line_user_id = %s
            UNION ALL
            SELECT 'INCOME' as type, i.income_id as id, TO_CHAR(i.date, 'YYYY-MM-DD') as date, c.category_name, i.amount
            FROM incomes i
            JOIN income_categories c ON i.category_id = c.category_id
            JOIN members m ON i.member_id = m.member_id
            WHERE m.line_user_id = %s
            ORDER BY date DESC, id DESC
            LIMIT %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (line_user_id, line_user_id, limit))
                return cursor.fetchall()
        finally:
            conn.close()

    def get_monthly_shared_stats(self, line_user_id):
        """過去30日間の全体の共有支出と、特定のユーザーの共有負担額を取得する"""
        query = """
            SELECT 
                COALESCE(SUM(e.amount), 0) as total_shared,
                COALESCE(SUM(CASE WHEN m.line_user_id = %s THEN e.amount ELSE 0 END), 0) as user_shared
            FROM expenses e
            JOIN members m ON e.member_id = m.member_id
            WHERE e.is_shared = 1 AND e.date >= CURRENT_DATE - INTERVAL '30 days'
        """
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (line_user_id,))
                row = cursor.fetchone()
                return row[0], row[1]
        finally:
            conn.close()

    def get_monthly_summary(self, line_user_id):
        """過去30日間の総支出額と項目別の集計を取得する"""
        query = """
            SELECT c.category_name, SUM(e.amount) as total
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.category_id
            JOIN members m ON e.member_id = m.member_id
            WHERE m.line_user_id = %s AND e.date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY c.category_name
            ORDER BY total DESC
        """
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (line_user_id,))
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
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table_name} WHERE {id_column} = %s", (tx_id,))
                conn.commit()
                return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def update_transaction(self, tx_type, tx_id, category_name, amount, memo, is_shared=0):
        if tx_type not in ['EXPENSE', 'INCOME']:
            return False, "無効なタイプです"
        table_name = 'expenses' if tx_type == 'EXPENSE' else 'incomes'
        id_column = 'expense_id' if tx_type == 'EXPENSE' else 'income_id'
        cat_table = 'expense_categories' if tx_type == 'EXPENSE' else 'income_categories'
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT category_id FROM {cat_table} WHERE category_name = %s", (category_name,))
                row = cursor.fetchone()
                if not row:
                    return False, f"項目「{category_name}」が存在しません"
                category_id = row[0]
                
                # 💡 支出の場合は is_shared も更新する
                if tx_type == 'EXPENSE':
                    cursor.execute(f"""
                        UPDATE {table_name} 
                        SET category_id = %s, amount = %s, memo = %s, is_shared = %s
                        WHERE {id_column} = %s
                    """, (category_id, amount, memo, is_shared, tx_id))
                else:
                    cursor.execute(f"""
                        UPDATE {table_name} 
                        SET category_id = %s, amount = %s, memo = %s
                        WHERE {id_column} = %s
                    """, (category_id, amount, memo, tx_id))
                conn.commit()
                return True, "Success"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()