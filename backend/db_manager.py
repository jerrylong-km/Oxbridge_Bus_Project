import os
import sqlite3

# 数据库与本脚本同在 backend/ 目录，使用绝对路径以免受启动目录影响
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'school_management.db')

def init_or_update_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. 檢查並創建 users 表（用於存放登入憑證與角色）
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone():
        print("檢測到 users 表不存在，正在創建...")
        cursor.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                role TEXT NOT NULL,          -- 'superadmin' 或 'school_admin'
                school_id INTEGER,           -- 若是校車管理員，關聯其所屬學校
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("users 表創建成功！")

    # 2. 檢查並創建 schools 表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schools'")
    table_exists = cursor.fetchone()

    if not table_exists:
        print("檢測到 schools 表不存在，正在創建新表...")
        cursor.execute('''
            CREATE TABLE schools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                admin_name TEXT,
                approval_status TEXT DEFAULT 'pending',
                approved_at DATETIME,
                rejection_reason TEXT
            )
        ''')
        print("表 schools 創建成功！")
    else:
        print("檢測到 schools 表已存在，正在檢查字段...")
        cursor.execute("PRAGMA table_info(schools)")
        columns = [row[1] for row in cursor.fetchall()]
        
        new_columns = {
            'approval_status': "TEXT DEFAULT 'pending'",
            'approved_at': "DATETIME",
            'rejection_reason': "TEXT"
        }

        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE schools ADD COLUMN {col_name} {col_type}")
                print(f"成功添加字段: {col_name}")

    conn.commit()
    conn.close()
    print("數據庫架構維護完成。")

if __name__ == "__main__":
    init_or_update_db()