import sqlite3
import csv
import datetime

DB_NAME = 'db/housekeep.db'

def export_to_csv():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    dt_now = datetime.datetime.now()

    # --- 1. 支出データの出力 ---
    cursor.execute("""
        SELECT 
            e.date AS '日付',
            m.member_name AS '入力者名',
            c.category_name AS '支出項目',
            e.amount AS '金額'
        FROM expenses e
        JOIN members m ON e.member_id = m.member_id
        JOIN expense_categories c ON e.category_id = c.category_id
        ORDER BY e.date DESC, e.expense_id DESC
    """)
    expenses = cursor.fetchall()
    expense_headers = [desc[0] for desc in cursor.description]

    # encoding='utf-8-sig' でExcelでの文字化けを防止
    with open(f'csv/expenses_{dt_now.year}_{dt_now.month}_{dt_now.day}.csv', 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(expense_headers)
        writer.writerows(expenses)

    # --- 2. 収入データの出力 ---
    cursor.execute("""
        SELECT 
            i.date AS '日付',
            m.member_name AS '入力者',
            c.category_name AS '収入項目',
            i.amount AS '金額'
        FROM incomes i
        JOIN members m ON i.member_id = m.member_id
        JOIN income_categories c ON i.category_id = c.category_id
        ORDER BY i.date DESC, i.income_id DESC
    """)
    incomes = cursor.fetchall()
    income_headers = [desc[0] for desc in cursor.description]

    # with open(f'csv/incomes_{dt_now.year}_{dt_now.month}_{dt_now.day}.csv', 'w', encoding='utf-8-sig', newline='') as f:
    #     writer = csv.writer(f)
    #     writer.writerow(income_headers)
    #     writer.writerows(incomes)

    print("csvファイルを出力しました。")
    conn.close()

if __name__ == '__main__':
    export_to_csv()