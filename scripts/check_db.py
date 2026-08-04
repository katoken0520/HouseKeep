import sqlite3

CHECK_MODE = "EXPENSE"

# データベースに接続
conn = sqlite3.connect('db/housekeep.db')
cursor = conn.cursor()

# 支出テーブルと、名前を紐付けて表示するSQL
if CHECK_MODE == "EXPENSE":
    cursor.execute("""
        SELECT 
            e.date, m.member_name, c.category_name, e.amount, e.memo
        FROM expenses e
        JOIN members m ON e.member_id = m.member_id
        JOIN expense_categories c ON e.category_id = c.category_id
    """)

    print("--- 登録されている支出データ ---")
    for row in cursor.fetchall():
        print(row)
elif CHECK_MODE == "INCOME":
    cursor.execute("""
        SELECT 
            i.date, m.member_name, c.category_name, i.amount, i.memo
        FROM incomes i
        JOIN members m ON i.member_id = m.member_id
        JOIN income_categories c ON i.category_id = c.category_id
    """)

    print("--- 登録されている収入データ ---")
    for row in cursor.fetchall():
        print(row)

conn.close()