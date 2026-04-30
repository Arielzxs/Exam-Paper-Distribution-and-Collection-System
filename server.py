import os
import datetime
import shutil
import sqlite3
import threading
import pyzipper
import random
import string
from flask import Flask, request, jsonify, send_from_directory
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter.scrolledtext import ScrolledText # 修复：换回 Python 原生滚动框，避开 Mac 滚动条冲突
from tkinter import messagebox, filedialog

# ===================== Flask 服务与数据库 =====================
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
os.makedirs('exams', exist_ok=True)

def init_db():
    conn = sqlite3.connect('noi_system.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS students
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, student_no TEXT,
                  mac_address TEXT, hostname TEXT, ip_address TEXT,
                  bind_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS exams
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, exam_name TEXT, zip_path TEXT, password TEXT,
                  exam_start_time TIMESTAMP, exam_end_time TIMESTAMP, submit_save_path TEXT,
                  create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS submissions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, student_name TEXT, student_no TEXT,
                  file_path TEXT, file_size INTEGER, upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS clean_commands
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, command TEXT, issued_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  executed INTEGER DEFAULT 0)''')
    try: c.execute('ALTER TABLE exams ADD COLUMN exam_end_time TIMESTAMP')
    except: pass
    try: c.execute('ALTER TABLE exams ADD COLUMN submit_save_path TEXT')
    except: pass
    conn.commit()
    conn.close()

def get_db(): return sqlite3.connect('noi_system.db', check_same_thread=False)

def get_submit_save_path():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT submit_save_path FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    path = r[0] if (r and r[0]) else 'submissions'
    os.makedirs(path, exist_ok=True)
    return path

@app.route('/api/check_bind', methods=['POST'])
def check_bind():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT name,student_no FROM students WHERE mac_address=? AND hostname=?', (data.get('mac_address'), data.get('hostname')))
    r = c.fetchone()
    conn.close()
    return jsonify({'code': 0, 'name': r[0], 'student_no': r[1]}) if r else jsonify({'code': -1, 'msg': '未绑定'})

@app.route('/api/login', methods=['POST'])
def login():
    d = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM students WHERE name=? AND student_no=? AND mac_address=? AND hostname=?',
              (d['name'], d['student_no'], d['mac_address'], d['hostname']))
    r = c.fetchone()
    conn.close()
    return jsonify({'code': 0, 'msg': '登录成功', 'student_id': r[0]}) if r else jsonify({'code': -1, 'msg': '信息不匹配'})

@app.route('/api/download_problem', methods=['GET'])
def download_problem():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT zip_path FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    if not r or not os.path.exists(r[0]): return jsonify({'code': -1, 'msg': '无试题'}), 404
    return send_from_directory(os.path.dirname(r[0]), os.path.basename(r[0]), as_attachment=True)

@app.route('/api/get_password', methods=['GET'])
def get_password():
    now = datetime.datetime.now()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT password,exam_start_time FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    if not r: return jsonify({'code': -1, 'msg': '未设置考试'})
    try: st = datetime.datetime.strptime(r[1], '%Y-%m-%d %H:%M:%S')
    except: return jsonify({'code': -1, 'msg': '时间格式错误'})
    return jsonify({'code': 0, 'password': r[0]}) if now >= st else jsonify({'code': -2, 'msg': '未到时间'})

@app.route('/api/upload_submit', methods=['POST'])
def upload_submit():
    data = request.form
    file = request.files.get('file')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM students WHERE id=? AND mac_address=? AND hostname=?',
              (data['student_id'], data['mac_address'], data['hostname']))
    if not c.fetchone(): return jsonify({'code': -2, 'msg': '机器验证失败'})
    student_no = data['student_no']
    save_root = get_submit_save_path()
    full_path = os.path.join(save_root, f"{student_no}.zip")
    file.save(full_path)
    c.execute('INSERT INTO submissions (student_id,student_name,student_no,file_path,file_size,status) VALUES (?,?,?,?,?,\'success\')',
              (data['student_id'], data['student_name'], student_no, full_path, os.path.getsize(full_path)))
    conn.commit()
    conn.close()
    return jsonify({'code': 0, 'msg': '提交成功'})

@app.route('/api/get_clean', methods=['GET'])
def get_clean():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id,command FROM clean_commands WHERE executed=0 ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    if r:
        c.execute('UPDATE clean_commands SET executed=1 WHERE id=?', (r[0],))
        conn.commit()
    conn.close()
    return jsonify({'code': 0, 'command': r[1]}) if r else jsonify({'code': -1})

@app.route('/api/get_exam_time', methods=['GET'])
def get_exam_time():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT exam_start_time, exam_end_time FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    if not r: return jsonify({'code': -1, 'msg': '未配置考试'})
    return jsonify({'code': 0, 'exam_start_time': r[0] or '', 'exam_end_time': r[1] or '', 'msg': '成功'})

def run_server(): app.run(host='0.0.0.0', port=5001, debug=False)

# ===================== 现代化 GUI 界面 =====================
class ServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title('NOI 试题收发系统 - 教师控制台')
        self.root.geometry('950x750')
        self.root.place_window_center()

        header = ttk.Frame(root, padding=10)
        header.pack(fill=X)
        ttk.Label(header, text='NOI 服务器管理中心', font=('Helvetica', 18, 'bold'), bootstyle=PRIMARY).pack(side=LEFT)
        
        main_frame = ttk.Frame(root, padding=10)
        main_frame.pack(fill=BOTH, expand=YES)
        
        left_panel = ttk.Frame(main_frame)
        left_panel.pack(side=LEFT, fill=Y, expand=False, padx=(0, 10))

        group_student = ttk.Labelframe(left_panel, text=' 👨‍🎓 考生绑定 ', padding=15)
        group_student.pack(fill=X, pady=(0, 15))
        
        ttk.Label(group_student, text='姓名').grid(row=0, column=0, pady=5, sticky=W)
        self.name = ttk.Entry(group_student, width=15)
        self.name.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(group_student, text='考号').grid(row=0, column=2, pady=5, sticky=W)
        self.sno = ttk.Entry(group_student, width=15)
        self.sno.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(group_student, text='MAC').grid(row=1, column=0, pady=5, sticky=W)
        self.mac = ttk.Entry(group_student, width=15)
        self.mac.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(group_student, text='主机名').grid(row=1, column=2, pady=5, sticky=W)
        self.host = ttk.Entry(group_student, width=15)
        self.host.grid(row=1, column=3, padx=5, pady=5)

        ttk.Button(group_student, text='➕ 添加/绑定考生', bootstyle=SUCCESS, command=self.add_student).grid(row=2, column=0, columnspan=4, pady=10, sticky=EW)

        group_exam = ttk.Labelframe(left_panel, text=' 📝 考试配置 ', padding=15)
        group_exam.pack(fill=X, pady=(0, 15))

        ttk.Label(group_exam, text='考试名称').grid(row=0, column=0, pady=5, sticky=W)
        self.ename = ttk.Entry(group_exam)
        self.ename.grid(row=0, column=1, columnspan=2, sticky=EW, padx=5, pady=5)

        ttk.Label(group_exam, text='解压密码').grid(row=1, column=0, pady=5, sticky=W)
        self.pwd = ttk.Entry(group_exam, width=12)
        self.pwd.grid(row=1, column=1, sticky=W, padx=5, pady=5)
        ttk.Button(group_exam, text='随机', bootstyle=(INFO, OUTLINE), command=self.gen_rand_pwd).grid(row=1, column=2, padx=5)

        ttk.Label(group_exam, text='试题数量').grid(row=2, column=0, pady=5, sticky=W)
        self.question_count = ttk.Entry(group_exam, width=8)
        self.question_count.insert(0, "3")
        self.question_count.grid(row=2, column=1, sticky=W, padx=5, pady=5)

        ttk.Label(group_exam, text='原题目录').grid(row=3, column=0, pady=5, sticky=W)
        self.zip_path_entry = ttk.Entry(group_exam)
        self.zip_path_entry.grid(row=3, column=1, sticky=EW, padx=5, pady=5)
        ttk.Button(group_exam, text='浏览', bootstyle=(SECONDARY, OUTLINE), command=self.browse_zip).grid(row=3, column=2, padx=5)

        ttk.Label(group_exam, text='收卷目录').grid(row=4, column=0, pady=5, sticky=W)
        self.submit_save_path = ttk.Entry(group_exam)
        self.submit_save_path.insert(0, "submissions")
        self.submit_save_path.grid(row=4, column=1, sticky=EW, padx=5, pady=5)
        ttk.Button(group_exam, text='浏览', bootstyle=(SECONDARY, OUTLINE), command=self.select_submit_path).grid(row=4, column=2, padx=5)

        ttk.Label(group_exam, text='开始时间').grid(row=5, column=0, pady=5, sticky=W)
        self.etime_start = ttk.Entry(group_exam)
        self.etime_start.insert(0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.etime_start.grid(row=5, column=1, columnspan=2, sticky=EW, padx=5, pady=5)

        ttk.Label(group_exam, text='结束时间').grid(row=6, column=0, pady=5, sticky=W)
        self.etime_end = ttk.Entry(group_exam)
        self.etime_end.insert(0, (datetime.datetime.now() + datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
        self.etime_end.grid(row=6, column=1, columnspan=2, sticky=EW, padx=5, pady=5)

        ttk.Button(
            group_exam,
            text='🚀 发布考试 (自动加密打包)',
            bootstyle=PRIMARY,
            command=self.start_set_exam
        ).grid(row=7, column=0, columnspan=3, pady=15, sticky=EW)

        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=LEFT, fill=BOTH, expand=True)

        group_ctrl = ttk.Labelframe(right_panel, text=' ⚡ 考场控制面板 ', padding=15)
        group_ctrl.pack(fill=X, pady=(0, 15))
        
        btn_frame = ttk.Frame(group_ctrl)
        btn_frame.pack(fill=X)
        ttk.Button(btn_frame, text='📂 查看所有提交记录', bootstyle=INFO, command=self.show_submits).pack(side=LEFT, padx=10, expand=True, fill=X)
        ttk.Button(btn_frame, text='🗑️ 一键下发清理指令 (慎用)', bootstyle=DANGER, command=self.issue_clean).pack(side=LEFT, padx=10, expand=True, fill=X)

        group_log = ttk.Labelframe(right_panel, text=' 📟 系统运行日志 ', padding=10)
        group_log.pack(fill=BOTH, expand=True)
        # 修复：移除 autohide 参数，使用标准 Tkinter ScrolledText
        self.log = ScrolledText(group_log, wrap=WORD)
        self.log.pack(fill=BOTH, expand=True)

        self.log_print('✅ 服务端控制台已启动，等待考生连接... (运行于 5001 端口)')

    def log_print(self, msg):
        self.log.insert(END, f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}\n')
        self.log.see(END)

    def _ui_log(self, msg):
        self.root.after(0, lambda: self.log_print(msg))

    def _ui_info(self, title, msg):
        self.root.after(0, lambda: messagebox.showinfo(title, msg))

    def _ui_error(self, title, msg):
        self.root.after(0, lambda: messagebox.showerror(title, msg))

    def select_submit_path(self):
        path = filedialog.askdirectory(title='选择收卷目录')
        if path:
            self.submit_save_path.delete(0, END)
            self.submit_save_path.insert(0, path)

    def browse_zip(self):
        path = filedialog.askdirectory(title='选择原题文件夹')
        if path:
            self.zip_path_entry.delete(0, END)
            self.zip_path_entry.insert(0, path)

    def gen_rand_pwd(self):
        pwd = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
        self.pwd.delete(0, END)
        self.pwd.insert(0, pwd)
        self.log_print(f'🔑 生成随机密码：{pwd}')

    def add_student(self):
        if not self.name.get() or not self.sno.get():
            messagebox.showwarning("警告", "姓名和考号不能为空！")
            return
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO students (name,student_no,mac_address,hostname,ip_address) VALUES (?,?,?,?,?)',
                      (self.name.get(), self.sno.get(), self.mac.get(), self.host.get(), '127.0.0.1'))
            conn.commit()
            conn.close()
            self.log_print(f'👤 考生添加成功：{self.name.get()} ({self.sno.get()})')
            self.name.delete(0, END)
            self.sno.delete(0, END)
            self.mac.delete(0, END)
            self.host.delete(0, END)
        except Exception as e:
            self.log_print(f'❌ 添加考生失败：{e}')

    def start_set_exam(self):
        exam_name = self.ename.get().strip()
        source_path = self.zip_path_entry.get().strip()
        submit_path = self.submit_save_path.get().strip()
        pwd = self.pwd.get().strip()
        etime_start = self.etime_start.get().strip()
        etime_end = self.etime_end.get().strip()

        if not source_path or not os.path.isdir(source_path):
            return messagebox.showerror("错误", "请选择有效的试题文件夹")
        if not submit_path:
            return messagebox.showerror("错误", "收卷路径不能为空")

        try:
            n = int(self.question_count.get().strip())
        except ValueError:
            return messagebox.showerror("错误", "试题数量必须是数字")

        args = (exam_name, source_path, submit_path, pwd, etime_start, etime_end, n)
        threading.Thread(target=self.set_exam_worker, args=args, daemon=True).start()

    def set_exam_worker(self, exam_name, source_path, submit_path, pwd, etime_start, etime_end, n):
        temp_dir = None
        try:
            dest_filename = f"{exam_name}_{int(datetime.datetime.now().timestamp())}.zip"
            dest_path = os.path.join('exams', dest_filename)
            temp_dir = f"temp_{int(datetime.datetime.now().timestamp())}"
            os.makedirs(temp_dir, exist_ok=True)

            for item in os.listdir(source_path):
                s = os.path.join(source_path, item)
                d = os.path.join(temp_dir, item)
                if os.path.isdir(s): shutil.copytree(s, d, dirs_exist_ok=True)
                else: shutil.copy(s, d)

            for i in range(1, n+1):
                f = os.path.join(temp_dir, f"答题文件夹_{i}")
                os.makedirs(f, exist_ok=True)
                with open(os.path.join(f, "重要说明.txt"), "w", encoding="utf-8") as fp:
                    fp.write(f"第{i}题答题区，请将代码保存在此目录下。\n")

            with pyzipper.AESZipFile(dest_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                zf.setpassword(pwd.encode())
                for root_, _, files in os.walk(temp_dir):
                    for file in files:
                        fp = os.path.join(root_, file)
                        zf.write(fp, os.path.relpath(fp, temp_dir))

            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO exams (exam_name, zip_path, password, exam_start_time, exam_end_time, submit_save_path) VALUES (?,?,?,?,?,?)',
                (exam_name, dest_path, pwd, etime_start, etime_end, submit_path))
            conn.commit()
            conn.close()

            self._ui_log('🎉 考试发布成功！已生成加密包。')
            self._ui_info("成功", "考试发布完成！客户端将自动下载。")
        except Exception as e:
            self._ui_log(f'❌ 发布失败：{e}')
        finally:
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir)

    def issue_clean(self):
        if messagebox.askyesno("严重警告", "下发清理指令将清空所有在线考生桌面 NOI_Work 目录下的代码！\n确定要下发吗？"):
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO clean_commands (command) VALUES (\'clean\')')
            conn.commit()
            conn.close()
            self.log_print('🧹 远程强制清理指令已广播！')

    def show_submits(self):
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT student_no,student_name,upload_time FROM submissions ORDER BY upload_time DESC')
        data = c.fetchall()
        conn.close()
        msg = '\n'.join([f'✅ {x[0]} ({x[1]}) - 提交于: {x[2]}' for x in data]) if data else '暂无学生提交记录'
        messagebox.showinfo('📦 最新收卷记录', msg)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_server, daemon=True).start()
    app_window = ttk.Window(themename="flatly")
    ServerGUI(app_window)
    app_window.mainloop()