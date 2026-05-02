import sqlite3
import os
import datetime

DB_NAME = "noi_system.db"

def init_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 考生表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        student_no TEXT NOT NULL,
        mac_address TEXT NOT NULL,
        hostname TEXT NOT NULL,
        ip_address TEXT,
        status TEXT DEFAULT '未连接',
        last_heartbeat TIMESTAMP,
        bind_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    try:
        cursor.execute('ALTER TABLE students ADD COLUMN status TEXT DEFAULT "未连接"')
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute('ALTER TABLE students ADD COLUMN last_heartbeat TIMESTAMP')
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # 考试表（只新增 client_full_path 字段）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_name TEXT NOT NULL,
        zip_path TEXT NOT NULL,
        password TEXT NOT NULL,
        exam_start_time TIMESTAMP,
        exam_end_time TIMESTAMP,
        submit_save_path TEXT,
        client_full_path TEXT,     -- 客户端完整路径（支持${hostname}）
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    try:
        cursor.execute('ALTER TABLE exams ADD COLUMN exam_end_time TIMESTAMP')
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute('ALTER TABLE exams ADD COLUMN submit_save_path TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute('ALTER TABLE exams ADD COLUMN client_full_path TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # 提交记录表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        student_name TEXT,
        student_no TEXT,
        file_path TEXT,
        file_size INTEGER,
        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'success'
    )
    ''')

    # 清理指令表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS clean_commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        command TEXT DEFAULT 'clean',
        issued_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        executed INTEGER DEFAULT 0
    )
    ''')

    conn.commit()
    conn.close()

def get_db_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def insert_test_data():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
    INSERT INTO students (name, student_no, mac_address, hostname, ip_address)
    VALUES (?, ?, ?, ?, ?)
    ''', ("测试考生", "N2026999", "00:11:22:33:44:55", "TEST-PC", "127.0.0.1"))

    start_time = datetime.datetime.now()
    end_time = start_time + datetime.timedelta(hours=2)
    start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

    c.execute('''
    INSERT INTO exams (exam_name, zip_path, password, exam_start_time, exam_end_time, submit_save_path, client_full_path)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', ("NOI测试考试", "exams/problem.zip", "123456", start_str, end_str, "submissions", "C:\\Users\\${hostname}\\Desktop\\NOI试卷"))

    conn.commit()
    conn.close()

def show_tables():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    for t in tables:
        print("-", t[0])
        c.execute(f"PRAGMA table_info({t[0]})")
        cols = c.fetchall()
        for col in cols:
            print(f"  - {col[1]}")
    conn.close()

if __name__ == "__main__":
    init_database()
    show_tables()
    insert_test_data()