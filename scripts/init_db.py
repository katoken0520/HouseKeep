import sqlite3
from db_manager import DBManager

def init_db():
    # DBManagerを使って、確実にadmin_app.pyと同じDBのパスを取得する
    db = DBManager()
    print(f"📦 セットアップ対象のデータベース: {db.db_name}")

    conn = sqlite3.connect(db.db_name)
    cursor = conn.cursor()

    # 外部キー制約の有効化
    cursor.execute('PRAGMA foreign_keys = ON;')

    # 1. メンバーテーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS members (
        member_id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_name TEXT NOT NULL,
        line_user_id TEXT UNIQUE
    );
    """)

    # 2. 支出項目テーブル (is_active を含む)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expense_categories (
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_name TEXT NOT NULL UNIQUE,
        is_active INTEGER NOT NULL DEFAULT 1
    );
    """)

    # 3. 収入項目テーブル (is_active を含む)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS income_categories (
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_name TEXT NOT NULL UNIQUE,
        is_active INTEGER NOT NULL DEFAULT 1
    );
    """)

    # 4. 支出テーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        category_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        memo TEXT,
        FOREIGN KEY (member_id) REFERENCES members(member_id),
        FOREIGN KEY (category_id) REFERENCES expense_categories(category_id)
    );
    """)

    # 5. 収入テーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incomes (
        income_id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        member_id INTEGER NOT NULL,
        category_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        memo TEXT,
        FOREIGN KEY (member_id) REFERENCES members(member_id),
        FOREIGN KEY (category_id) REFERENCES income_categories(category_id)
    );
    """)

    # デフォルト項目の追加 (is_active=1)
    default_expense_cats = ["食費", "日用品", "その他"]
    for cat in default_expense_cats:
        cursor.execute('INSERT OR IGNORE INTO expense_categories (category_name, is_active) VALUES (?, 1)', (cat,))

    default_income_cats = ["給与", "賞与", "その他"]
    for cat in default_income_cats:
        cursor.execute('INSERT OR IGNORE INTO income_categories (category_name, is_active) VALUES (?, 1)', (cat,))

    conn.commit()
    conn.close()
    print("✨ データベースとテーブルの作成・更新が完了しました！")

if __name__ == '__main__':
    init_db()