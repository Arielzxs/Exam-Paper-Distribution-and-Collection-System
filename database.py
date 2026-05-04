# database.py
import sqlite3
import os


def init_database():
    """初始化数据库，创建所有必要的表"""
    db_path = 'exam_system.db'

    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # 考生表
        c.execute('''
            CREATE TABLE students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                student_no TEXT NOT NULL UNIQUE,
                status TEXT DEFAULT '未连接',
                last_heartbeat TEXT,
                bind_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 主机表
        c.execute('''
            CREATE TABLE hosts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac_address TEXT NOT NULL UNIQUE,
                hostname TEXT NOT NULL,
                ip_address TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 绑定关系表
        c.execute('''
            CREATE TABLE bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL UNIQUE,
                host_id INTEGER NOT NULL UNIQUE,
                bind_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
            )
        ''')

        # 考试表（新增 question_count 字段）
        c.execute('''
            CREATE TABLE exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_name TEXT NOT NULL,
                zip_path TEXT NOT NULL,
                password TEXT NOT NULL,
                exam_start_time TEXT NOT NULL,
                exam_end_time TEXT NOT NULL,
                question_count INTEGER DEFAULT 0, -- 新增：试题数量
                submit_save_path_win TEXT,
                submit_save_path_linux TEXT,
                client_path_win TEXT,
                client_path_linux TEXT,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 提交记录表
        c.execute('''
            CREATE TABLE submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                student_name TEXT NOT NULL,
                student_no TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')

        # 清理指令表
        c.execute('''
            CREATE TABLE clean_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                executed INTEGER DEFAULT 0,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ 数据库初始化完成")
    else:
        # 如果数据库已存在，检查并添加缺失的字段
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # 检查exams表是否有新字段
        c.execute("PRAGMA table_info(exams)")
        columns = [col[1] for col in c.fetchall()]

        # 添加缺失的字段
        if 'submit_save_path_win' not in columns:
            c.execute("ALTER TABLE exams ADD COLUMN submit_save_path_win TEXT")
            print("✅ 已添加字段: submit_save_path_win")

        if 'submit_save_path_linux' not in columns:
            c.execute("ALTER TABLE exams ADD COLUMN submit_save_path_linux TEXT")
            print("✅ 已添加字段: submit_save_path_linux")

        if 'client_path_win' not in columns:
            c.execute("ALTER TABLE exams ADD COLUMN client_path_win TEXT")
            print("✅ 已添加字段: client_path_win")

        if 'client_path_linux' not in columns:
            c.execute("ALTER TABLE exams ADD COLUMN client_path_linux TEXT")
            print("✅ 已添加字段: client_path_linux")

        # 新增：添加 question_count 字段
        if 'question_count' not in columns:
            c.execute("ALTER TABLE exams ADD COLUMN question_count INTEGER DEFAULT 0")
            print("✅ 已添加字段: question_count")

        conn.commit()
        conn.close()


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect('exam_system.db')
    conn.row_factory = sqlite3.Row
    return conn