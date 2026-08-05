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

    def delete_category_safely(self, tx_type, category_name):
        """項目を安全に削除する。明細が存在する場合は『その他』に移行した上で削除する。"""
        if tx_type not in ['EXPENSE', 'INCOME']:
            return False, "無効なタイプです"
            
        table_name = 'expenses' if tx_type == 'EXPENSE' else 'incomes'
        cat_table = 'expense_categories' if tx_type == 'EXPENSE' else 'income_categories'
        id_column = 'expense_id' if tx_type == 'EXPENSE' else 'income_id'
        
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                # 1. 削除対象の category_id を取得
                cursor.execute(f"SELECT category_id FROM {cat_table} WHERE category_name = %s", (category_name,))
                row = cursor.fetchone()
                if not row:
                    return False, f"項目「{category_name}」が見つかりません。"
                target_id = row[0]
                
                # 2. この項目が実際に明細（支出/収入テーブル）で使われているかカウント
                cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE category_id = %s", (target_id,))
                usage_count = cursor.fetchone()[0]
                
                # 3. 使われている場合は「その他」カテゴリーのIDを確保（なければ作る）
                if usage_count > 0:
                    cursor.execute(f"SELECT category_id FROM {cat_table} WHERE category_name = 'その他'")
                    other_row = cursor.fetchone()
                    if other_row:
                        other_id = other_row[0]
                    else:
                        # 『その他』がなければ新規作成（非表示状態にならないようis_active=1）
                        cursor.execute(f"INSERT INTO {cat_table} (category_name, is_active) VALUES ('その他', 1) RETURNING category_id")
                        other_id = cursor.fetchone()[0]
                    
                    # 明細のカテゴリーを『その他』にアップデート
                    cursor.execute(f"UPDATE {table_name} SET category_id = %s WHERE category_id = %s", (other_id, target_id))
                
                # 4. 元のカテゴリーを削除
                cursor.execute(f"DELETE FROM {cat_table} WHERE category_id = %s", (target_id,))
                
                conn.commit()
                if usage_count > 0:
                    return True, f"項目「{category_name}」を削除しました。（使用されていた {usage_count} 件の明細を「その他」に移動しました）"
                else:
                    return True, f"項目「{category_name}」を削除しました。"
        except Exception as e:
            conn.rollback()
            return False, f"エラーが発生しました: {str(e)}"
        finally:
            conn.close()

    def check_category_usage(self, tx_type, category_name):
        """項目が現在何件の明細で使用されているかを確認する（警告表示用）"""
        if tx_type not in ['EXPENSE', 'INCOME']:
            return 0
        table_name = 'expenses' if tx_type == 'EXPENSE' else 'incomes'
        cat_table = 'expense_categories' if tx_type == 'EXPENSE' else 'income_categories'
        
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT COUNT(*) FROM {table_name} e
                    JOIN {cat_table} c ON e.category_id = c.category_id
                    WHERE c.category_name = %s
                """, (category_name,))
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            print(f"check_category_usage error: {e}")
            return 0
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

    def get_liff_transactions(self, line_user_id, limit=100):
        """LIFF用に、ユーザーの過去の履歴を新しい順に取得（共有/個人フラグ付き）"""
        query = """
            SELECT 'EXPENSE' as type, e.expense_id as id, TO_CHAR(e.date, 'YYYY-MM-DD') as date, c.category_name, e.amount, e.is_shared
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.category_id
            JOIN members m ON e.member_id = m.member_id
            WHERE m.line_user_id = %s
            UNION ALL
            SELECT 'INCOME' as type, i.income_id as id, TO_CHAR(i.date, 'YYYY-MM-DD') as date, c.category_name, i.amount, 0 as is_shared
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

    def get_monthly_report_stats(self, line_user_id):
        """月次レポート用の集計データ（先月の総額、過去平均、トップ3項目）を取得する"""
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                # 1. 先月の総支出
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0) FROM expenses e 
                    JOIN members m ON e.member_id = m.member_id
                    WHERE m.line_user_id = %s
                    AND date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                    AND date < date_trunc('month', CURRENT_DATE)
                """, (line_user_id,))
                last_month_total = int(cursor.fetchone()[0] or 0)
                
                # 先月の記録がない場合はNoneを返す
                if last_month_total == 0:
                    return None
                
                # 2. 過去の平均総支出（先月より前の全期間の月平均）
                cursor.execute("""
                    SELECT COALESCE(AVG(monthly_total), 0) FROM (
                        SELECT date_trunc('month', date) as month, SUM(amount) as monthly_total
                        FROM expenses e
                        JOIN members m ON e.member_id = m.member_id
                        WHERE m.line_user_id = %s
                        AND date < date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                        GROUP BY date_trunc('month', date)
                    ) sub
                """, (line_user_id,))
                past_avg_total = int(cursor.fetchone()[0] or 0)
                
                # 3. 先月の支出が多いカテゴリートップ3
                cursor.execute("""
                    SELECT c.category_id, c.category_name, SUM(e.amount) as cat_total
                    FROM expenses e
                    JOIN expense_categories c ON e.category_id = c.category_id
                    JOIN members m ON e.member_id = m.member_id
                    WHERE m.line_user_id = %s
                    AND e.date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                    AND e.date < date_trunc('month', CURRENT_DATE)
                    GROUP BY c.category_id, c.category_name
                    ORDER BY cat_total DESC
                    LIMIT 3
                """, (line_user_id,))
                top_categories_raw = cursor.fetchall()
                
                top_categories = []
                for cat_id, cat_name, cat_total in top_categories_raw:
                    # 該当カテゴリーの過去平均
                    cursor.execute("""
                        SELECT COALESCE(AVG(monthly_total), 0) FROM (
                            SELECT date_trunc('month', date) as month, SUM(amount) as monthly_total
                            FROM expenses e
                            JOIN members m ON e.member_id = m.member_id
                            WHERE m.line_user_id = %s AND e.category_id = %s
                            AND date < date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                            GROUP BY date_trunc('month', date)
                        ) sub
                    """, (line_user_id, cat_id))
                    cat_past_avg = int(cursor.fetchone()[0] or 0)
                    
                    top_categories.append({
                        "name": cat_name,
                        "amount": int(cat_total),
                        "past_avg": cat_past_avg
                    })
                    
                return {
                    "last_month_total": last_month_total,
                    "past_avg_total": past_avg_total,
                    "top_categories": top_categories
                }
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