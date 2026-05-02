# database.py  数据库核心文件
import sqlite3
import os
import datetime

DB_NAME = "noi_system.db"


# ===================== 初始化数据库（自动建表/更新表结构） =====================
def init_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. 考生表（机器绑定 + 单一状态字段）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,           -- 姓名
        student_no TEXT NOT NULL,     -- 考号
        mac_address TEXT NOT NULL,    -- MAC地址
        hostname TEXT NOT NULL,       -- 主机名
        ip_address TEXT,              -- IP
        status TEXT DEFAULT '未连接',  -- 状态：未连接、已连接、已登录、已交卷
        last_heartbeat TIMESTAMP,      -- 最后心跳时间
        bind_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 兼容旧数据库：自动添加 status 字段
    try:
        cursor.execute('ALTER TABLE students ADD COLUMN status TEXT DEFAULT "未连接"')
        conn.commit()
        print("ℹ️ 已为 students 表新增 status 状态列")
    except sqlite3.OperationalError:
        pass

    # 兼容旧数据库：自动添加 last_heartbeat 字段
    try:
        cursor.execute('ALTER TABLE students ADD COLUMN last_heartbeat TIMESTAMP')
        conn.commit()
        print("ℹ️ 已为 students 表新增 last_heartbeat 列")
    except sqlite3.OperationalError:
        pass

    # 2. 考试配置表（保留 exam_end_time 列：考试结束时间）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_name TEXT NOT NULL,
        zip_path TEXT NOT NULL,       -- 试题压缩包路径
        password TEXT NOT NULL,       -- 解压密码
        exam_start_time TIMESTAMP,    -- 考试开始时间
        exam_end_time TIMESTAMP,      -- 考试结束时间
        submit_save_path TEXT,        -- 收卷保存目录
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 兼容旧数据库：如果已有 exams 表但没有 exam_end_time 列，自动新增
    try:
        cursor.execute('ALTER TABLE exams ADD COLUMN exam_end_time TIMESTAMP')
        conn.commit()
        print("ℹ️ 已为 exams 表新增 exam_end_time 列")
    except sqlite3.OperationalError:
        pass

    # 兼容旧数据库：添加 submit_save_path 收卷目录字段
    try:
        cursor.execute('ALTER TABLE exams ADD COLUMN submit_save_path TEXT')
        conn.commit()
        print("ℹ️ 已为 exams 表新增 submit_save_path 列")
    except sqlite3.OperationalError:
        pass

    # 3. 提交记录表（答案上传）
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

    # 4. 远程清理指令表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS clean_commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        command TEXT DEFAULT 'clean',
        issued_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        executed INTEGER DEFAULT 0     -- 0=未执行 1=已执行
    )
    ''')

    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成，所有表已创建/更新")


# ===================== 获取数据库连接 =====================
def get_db_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


# ===================== 测试数据（同步新版结构） =====================
def insert_test_data():
    conn = get_db_connection()
    c = conn.cursor()

    # 插入测试考生
    c.execute('''
    INSERT INTO students (name, student_no, mac_address, hostname, ip_address)
    VALUES (?, ?, ?, ?, ?)
    ''', ("测试考生", "N2026999", "00:11:22:33:44:55", "TEST-PC", "127.0.0.1"))

    # 插入测试考试
    start_time = datetime.datetime.now()
    end_time = start_time + datetime.timedelta(hours=2)
    start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

    c.execute('''
    INSERT INTO exams (exam_name, zip_path, password, exam_start_time, exam_end_time, submit_save_path)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', ("NOI测试考试", "exams/problem.zip", "123456", start_str, end_str, "submissions"))

    conn.commit()
    conn.close()
    print("✅ 测试数据插入完成（含状态、心跳、收卷目录）")


# ===================== 查看所有表结构 =====================
def show_tables():
    conn = get_db_connection()
    c = conn.cursor()
    # 查看所有表
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    print("📊 当前数据库表：")
    for t in tables:
        print("-", t[0])
        # 打印每个表的列结构
        c.execute(f"PRAGMA table_info({t[0]})")
        columns = c.fetchall()
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
    conn.close()


# ===================== 直接运行此文件即可创建数据库 =====================
if __name__ == "__main__":
    init_database()
    show_tables()
    insert_test_data()  # 可选：插入测试数据