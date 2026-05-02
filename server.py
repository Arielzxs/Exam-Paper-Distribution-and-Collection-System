import os
import datetime
import shutil
import sqlite3
import threading
import pyzipper
import random
import string
import time
from flask import Flask, request, jsonify, send_from_directory
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter.scrolledtext import ScrolledText
from tkinter import messagebox, filedialog

from database import init_database, get_db_connection

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

def get_db():
    return get_db_connection()

def get_submit_save_path():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT submit_save_path FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    return r[0] if (r and r[0]) else None

def get_client_full_path():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT client_full_path FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    return r[0] if (r and r[0]) else ""

def update_student_status(mac, hostname, status):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE students
        SET status=?, last_heartbeat=?
        WHERE mac_address=? AND hostname=?
    ''', (status, now, mac, hostname))
    conn.commit()
    conn.close()

def heartbeat_checker():
    while True:
        time.sleep(10)
        now = datetime.datetime.now()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, mac_address, hostname, last_heartbeat FROM students WHERE status != '未连接'")
        for sid, mac, host, hb_time in c.fetchall():
            if not hb_time:
                continue
            try:
                dt = datetime.datetime.strptime(hb_time, "%Y-%m-%d %H:%M:%S")
                if (now - dt).total_seconds() > 30:
                    c.execute('UPDATE students SET status="未连接" WHERE id=?', (sid,))
            except:
                pass
        conn.commit()
        conn.close()

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json
    mac = data.get("mac_address")
    host = data.get("hostname")
    ip = data.get("ip_address")
    if not mac or not host:
        return jsonify({"code": -1})
    update_student_status(mac, host, "已连接")
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE students SET ip_address=? WHERE mac_address=? AND hostname=?', (ip, mac, host))
    conn.commit()
    conn.close()
    return jsonify({"code": 0})

@app.route('/api/check_bind', methods=['POST'])
def check_bind():
    data = request.json
    mac = data.get('mac_address')
    host = data.get('hostname')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id,name,student_no FROM students WHERE mac_address=? AND hostname=?', (mac, host))
    r = c.fetchone()
    conn.close()
    if r:
        update_student_status(mac, host, "已连接")
        return jsonify({'code': 0, 'name': r[1], 'student_no': r[2]})
    return jsonify({'code': -1})

@app.route('/api/login', methods=['POST'])
def login():
    d = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM students WHERE name=? AND student_no=? AND mac_address=? AND hostname=?',
              (d['name'], d['student_no'], d['mac_address'], d['hostname']))
    r = c.fetchone()
    if not r:
        conn.close()
        return jsonify({'code': -1})

    path_template = get_client_full_path()
    real_path = path_template.replace("${hostname}", d.get("hostname", ""))
    try:
        os.makedirs(real_path, exist_ok=True)
    except:
        pass

    conn.close()
    update_student_status(d['mac_address'], d['hostname'], "已登录")
    return jsonify({
        'code': 0,
        'student_id': r[0],
        'real_exam_path': real_path
    })

@app.route('/api/upload_submit', methods=['POST'])
def upload_submit():
    data = request.form
    file = request.files.get('file')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM students WHERE id=? AND mac_address=? AND hostname=?',
              (data['student_id'], data['mac_address'], data['hostname']))
    if not c.fetchone():
        return jsonify({'code': -2})

    submit_dir = get_submit_save_path()
    if not submit_dir or not os.path.isdir(submit_dir):
        return jsonify({'code': -3, 'msg': '未设置收卷目录'})

    save_path = os.path.join(submit_dir, f"{data['student_no']}.zip")
    file.save(save_path)
    c.execute('''
        INSERT INTO submissions (student_id, student_name, student_no, file_path, file_size)
        VALUES (?, ?, ?, ?, ?)
    ''', (data['student_id'], data['student_name'], data['student_no'], save_path, os.path.getsize(save_path)))
    conn.commit()
    conn.close()
    update_student_status(data['mac_address'], data['hostname'], "已交卷")
    return jsonify({'code': 0})

@app.route('/api/download_problem', methods=['GET'])
def download_problem():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT zip_path FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    if not r or not os.path.exists(r[0]):
        return jsonify({'code': -1}), 404
    return send_from_directory(os.path.dirname(r[0]), os.path.basename(r[0]), as_attachment=True)

@app.route('/api/get_password', methods=['GET'])
def get_password():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT password, exam_start_time FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    if not r:
        return jsonify({'code': -1})
    try:
        now = datetime.datetime.now()
        start = datetime.datetime.strptime(r[1], "%Y-%m-%d %H:%M:%S")
        if now >= start:
            return jsonify({'code': 0, 'password': r[0]})
    except:
        pass
    return jsonify({'code': -2})

@app.route('/api/get_exam_time', methods=['GET'])
def get_exam_time():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT exam_start_time, exam_end_time FROM exams ORDER BY id DESC LIMIT 1')
    r = c.fetchone()
    conn.close()
    return jsonify({'code': 0, 'start': r[0], 'end': r[1]} if r else {'code': -1})

@app.route('/api/get_clean', methods=['GET'])
def get_clean():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM clean_commands WHERE executed=0 LIMIT 1')
    r = c.fetchone()
    if r:
        c.execute('UPDATE clean_commands SET executed=1 WHERE id=?', (r[0],))
        conn.commit()
        conn.close()
        return jsonify({'code': 0})
    conn.close()
    return jsonify({'code': -1})

def run_server():
    app.run(host='0.0.0.0', port=5001, debug=False)

class ServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title('NOI 试题收发系统 - 教师控制台')
        self.root.geometry('950x820')
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

        ttk.Label(group_exam, text='客户端完整路径\n支持 ${hostname}').grid(row=2, column=0, pady=5, sticky=W)
        self.client_path = ttk.Entry(group_exam)
        self.client_path.insert(0, "C:\\Users\\${hostname}\\Desktop\\NOI考试")
        self.client_path.grid(row=2, column=1, sticky=EW, padx=5, pady=5)
        ttk.Button(group_exam, text='插入\n${hostname}', command=self.insert_hostname_var).grid(row=2, column=2, padx=5)

        ttk.Label(group_exam, text='试题数量').grid(row=3, column=0, pady=5, sticky=W)
        self.question_count = ttk.Entry(group_exam, width=8)
        self.question_count.grid(row=3, column=1, sticky=W, padx=5, pady=5)

        ttk.Label(group_exam, text='原题目录').grid(row=4, column=0, pady=5, sticky=W)
        self.zip_path_entry = ttk.Entry(group_exam)
        self.zip_path_entry.grid(row=4, column=1, sticky=EW, padx=5, pady=5)
        ttk.Button(group_exam, text='浏览', bootstyle=(SECONDARY, OUTLINE), command=self.browse_zip).grid(row=4, column=2, padx=5)

        ttk.Label(group_exam, text='收卷目录').grid(row=5, column=0, pady=5, sticky=W)
        self.submit_save_path = ttk.Entry(group_exam)
        self.submit_save_path.grid(row=5, column=1, sticky=EW, padx=5, pady=5)
        ttk.Button(group_exam, text='浏览', bootstyle=(SECONDARY, OUTLINE), command=self.select_submit_path).grid(row=5, column=2, padx=5)

        ttk.Label(group_exam, text='开始时间').grid(row=6, column=0, pady=5, sticky=W)
        self.etime_start = ttk.Entry(group_exam)
        self.etime_start.insert(0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.etime_start.grid(row=6, column=1, columnspan=2, sticky=EW, padx=5, pady=5)

        ttk.Label(group_exam, text='结束时间').grid(row=7, column=0, pady=5, sticky=W)
        self.etime_end = ttk.Entry(group_exam)
        self.etime_end.insert(0, (datetime.datetime.now() + datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
        self.etime_end.grid(row=7, column=1, columnspan=2, sticky=EW, padx=5, pady=5)

        ttk.Button(
            group_exam,
            text='🚀 发布考试 (自动加密打包)',
            bootstyle=PRIMARY,
            command=self.start_set_exam
        ).grid(row=8, column=0, columnspan=3, pady=15, sticky=EW)

        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=LEFT, fill=BOTH, expand=True)

        group_ctrl = ttk.Labelframe(right_panel, text=' ⚡ 考场控制面板 ', padding=15)
        group_ctrl.pack(fill=X, pady=(0, 15))

        btn_frame = ttk.Frame(group_ctrl)
        btn_frame.pack(fill=X)
        ttk.Button(btn_frame, text='📋 查看所有考生信息', bootstyle=SUCCESS, command=self.show_all_students).pack(side=LEFT, padx=5, expand=True, fill=X)
        ttk.Button(btn_frame, text='📂 查看所有提交记录', bootstyle=INFO, command=self.show_submits).pack(side=LEFT, padx=5, expand=True, fill=X)
        ttk.Button(btn_frame, text='🗑️ 一键下发清理指令 (慎用)', bootstyle=DANGER, command=self.issue_clean).pack(side=LEFT, padx=5, expand=True, fill=X)

        group_log = ttk.Labelframe(right_panel, text=' 📟 系统运行日志 ', padding=10)
        group_log.pack(fill=BOTH, expand=True)
        self.log = ScrolledText(group_log)
        self.log.pack(fill=BOTH, expand=True)

        self.log_print('✅ 服务端启动完成，运行端口：5001')

    def insert_hostname_var(self):
        self.client_path.insert(tk.END, "${hostname}")

    def log_print(self, msg):
        self.log.insert(END, f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}\n')
        self.log.see(END)

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
            self.log_print(f'👤 考生添加成功：{self.name.get()}')
            self.name.delete(0, END)
            self.sno.delete(0, END)
            self.mac.delete(0, END)
            self.host.delete(0, END)
        except Exception as e:
            self.log_print(f'❌ 添加失败：{e}')

    def start_set_exam(self):
        exam_name = self.ename.get().strip()
        source_path = self.zip_path_entry.get().strip()
        submit_path = self.submit_save_path.get().strip()
        pwd = self.pwd.get().strip()
        client_path = self.client_path.get().strip()
        etime_start = self.etime_start.get().strip()
        etime_end = self.etime_end.get().strip()

        if not client_path:
            return messagebox.showerror("错误", "客户端文件夹不能为空")
        if not source_path or not os.path.isdir(source_path):
            return messagebox.showerror("错误", "请选择试题目录")
        if not submit_path:
            return messagebox.showerror("错误", "收卷路径不能为空")

        try:
            n = int(self.question_count.get().strip())
        except ValueError:
            return messagebox.showerror("错误", "试题数量必须是数字")

        threading.Thread(target=self.set_exam_worker,
                         args=(exam_name, source_path, submit_path, pwd, client_path, etime_start, etime_end, n),
                         daemon=True).start()

    def set_exam_worker(self, exam_name, source_path, submit_path, pwd, client_path, etime_start, etime_end, n):
        temp_dir = None
        try:
            os.makedirs('exams', exist_ok=True)
            dest_filename = f"{exam_name}_{int(datetime.datetime.now().timestamp())}.zip"
            dest_path = os.path.join('exams', dest_filename)
            temp_dir = f"temp_{int(datetime.datetime.now().timestamp())}"
            os.makedirs(temp_dir, exist_ok=True)

            for item in os.listdir(source_path):
                s = os.path.join(source_path, item)
                d = os.path.join(temp_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy(s, d)

            # ===================== ✅ 关键修改：只创建空文件夹，不生成说明文件 =====================
            for i in range(1, n+1):
                folder = os.path.join(temp_dir, f"答题文件夹_{i:02d}")
                os.makedirs(folder, exist_ok=True)

            with pyzipper.AESZipFile(dest_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                zf.setpassword(pwd.encode())
                for root_, _, files in os.walk(temp_dir):
                    for file in files:
                        fp = os.path.join(root_, file)
                        zf.write(fp, os.path.relpath(fp, temp_dir))

            conn = get_db()
            c = conn.cursor()
            c.execute('''
                INSERT INTO exams
                (exam_name, zip_path, password, exam_start_time, exam_end_time, submit_save_path, client_full_path)
                VALUES (?,?,?,?,?,?,?)
            ''', (exam_name, dest_path, pwd, etime_start, etime_end, submit_path, client_path))
            conn.commit()
            conn.close()
            self.log_print('✅ 考试发布成功！')
            messagebox.showinfo("成功", "考试已发布")
        except Exception as e:
            self.log_print(f'❌ 发布失败：{e}')
        finally:
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir)

    def issue_clean(self):
        if messagebox.askyesno("警告", "确定清空考生目录？"):
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO clean_commands (command) VALUES (\'clean\')')
            conn.commit()
            conn.close()
            self.log_print('🧹 清理指令已下发')

    def show_submits(self):
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT student_no, student_name, upload_time FROM submissions ORDER BY upload_time DESC')
        data = c.fetchall()
        msg = '\n'.join([f'✅ {x[0]} {x[1]} {x[2]}' for x in data]) if data else '暂无提交'
        messagebox.showinfo('提交记录', msg)

    def show_all_students(self):
        win = ttk.Toplevel(self.root)
        win.title("考生列表")
        win.geometry("1000x500")
        win.place_window_center()

        frame = ttk.Frame(win)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)
        scroll_y = ttk.Scrollbar(frame, orient=VERTICAL)
        scroll_y.pack(side=RIGHT, fill=Y)

        columns = ("id", "name", "student_no", "mac", "hostname", "ip", "status", "heartbeat", "bind_time")
        tree = ttk.Treeview(frame, columns=columns, show="headings", yscrollcommand=scroll_y.set)
        scroll_y.config(command=tree.yview)

        tree.heading("id", text="ID")
        tree.heading("name", text="姓名")
        tree.heading("student_no", text="考号")
        tree.heading("mac", text="MAC")
        tree.heading("hostname", text="主机名")
        tree.heading("ip", text="IP")
        tree.heading("status", text="状态")
        tree.heading("heartbeat", text="最后心跳")
        tree.heading("bind_time", text="绑定时间")

        tree.column("id", width=50)
        tree.column("name", width=80)
        tree.column("student_no", width=100)
        tree.column("mac", width=160)
        tree.column("hostname", width=120)
        tree.column("ip", width=100)
        tree.column("status", width=100)
        tree.column("heartbeat", width=150)
        tree.column("bind_time", width=160)

        tree.pack(fill=BOTH, expand=True)

        def fmt(s):
            if s == "未连接": return "🔴 未连接"
            if s == "已连接": return "🟡 已连接"
            if s == "已登录": return "🟢 已登录"
            if s == "已交卷": return "🔵 已交卷"
            return s

        def load():
            for i in tree.get_children():
                tree.delete(i)
            conn = get_db()
            c = conn.cursor()
            c.execute('''
                SELECT id,name,student_no,mac_address,hostname,ip_address,status,last_heartbeat,bind_time
                FROM students ORDER BY id
            ''')
            rows = c.fetchall()
            conn.close()
            for r in rows:
                lst = list(r)
                lst[6] = fmt(lst[6])
                tree.insert("", "end", values=lst)

        load()
        def ref():
            if win.winfo_exists():
                load()
                win.after(5000, ref)
        ref()

if __name__ == '__main__':
    init_database()
    threading.Thread(target=heartbeat_checker, daemon=True).start()
    threading.Thread(target=run_server, daemon=True).start()
    app_window = ttk.Window(themename="flatly")
    ServerGUI(app_window)
    app_window.mainloop()