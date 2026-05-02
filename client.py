import hashlib
import os
import re
import sys
import time
import uuid
import random
import zipfile
import datetime
import socket
import pyzipper
import requests
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter.scrolledtext import ScrolledText
from tkinter import messagebox, filedialog

SERVER_URL = 'http://127.0.0.1:5001'

def get_mac():
    mac = ':'.join(re.findall('..', '%012x' % uuid.getnode()))
    return mac

def get_hostname():
    return socket.gethostname()

MAC = get_mac()
HOSTNAME = get_hostname()

USER_NAME = ''
USER_NO = ''
STUDENT_ID = None
REAL_EXAM_PATH = ''

EXAM_START_TIME = None
EXAM_END_TIME = None
ZIP_FILE_PATH = None
UNZIP_DONE = False
IS_EXAM_OVER = False

root = ttk.Window(title="NOI 智能考试终端", themename="litera")
root.geometry("800x600")
root.place_window_center()

header = ttk.Frame(root)
header.pack(fill=X, padx=10, pady=10)
title_label = ttk.Label(header, text="🎓 NOI 智能考试终端", font=('Helvetica', 20, 'bold'), bootstyle=PRIMARY)
title_label.pack(side=LEFT)

time_label = ttk.Label(
    header,
    text="🕒 等待同步考试时间...",
    font=('Helvetica', 11),
    bootstyle=INFO
)
time_label.pack(side=RIGHT, pady=5)

main_content = ttk.Frame(root)
main_content.pack(fill=BOTH, expand=True, padx=15, pady=15)

left_container = ttk.Frame(main_content)
left_container.pack(side=LEFT, fill=Y, padx=(0, 15))

canvas = tk.Canvas(left_container, highlightthickness=0)
scrollbar = tk.Scrollbar(left_container, orient=VERTICAL, command=canvas.yview)
scrollable_frame = ttk.Frame(canvas)

scrollable_frame.bind(
    "<Configure>",
    lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
)

canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
canvas.configure(yscrollcommand=scrollbar.set)

canvas.pack(side=LEFT, fill=Y, expand=True)
scrollbar.pack(side=RIGHT, fill=Y)

def _on_mousewheel(event):
    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

canvas.bind_all("<MouseWheel>", _on_mousewheel)
left_panel = scrollable_frame

auth_card = ttk.LabelFrame(left_panel, text=" 🔒 身份验证 ")
auth_card.pack(fill=X, pady=(0, 15))

name_label = ttk.Label(auth_card, text="考 生 姓 名")
name_label.pack(anchor=W, pady=(0, 5))
entry_name = ttk.Entry(auth_card, font=('Helvetica', 11))
entry_name.pack(fill=X, pady=(0, 15))

no_label = ttk.Label(auth_card, text="考 生 考 号")
no_label.pack(anchor=W, pady=(0, 5))
entry_no = ttk.Entry(auth_card, font=('Helvetica', 11))
entry_no.pack(fill=X, pady=(0, 15))

btn_login = ttk.Button(auth_card, text="验证并登录考场", bootstyle=PRIMARY, width=20)
btn_login.pack(fill=X)

env_card = ttk.LabelFrame(left_panel, text=" 💻 本机环境 ")
env_card.pack(fill=X, pady=(0, 15))
info_label = ttk.Label(env_card, text=f"机器名称:\n{HOSTNAME}\n物理地址:\n{MAC}\n工作目录:\n等待登录", bootstyle=SECONDARY)
info_label.pack(anchor=W, pady=2)

action_card = ttk.LabelFrame(left_panel, text=" ⚙️ 考场操作 ")
action_card.pack(fill=X)

btn_download = ttk.Button(action_card, text="⬇️ 下载试题", bootstyle=(INFO, OUTLINE), state=DISABLED)
btn_download.pack(fill=X, pady=5)

btn_check_upload = ttk.Button(action_card, text="🚀 检查并提交答卷", bootstyle=SUCCESS, state=DISABLED)
btn_check_upload.pack(fill=X, pady=5)

log_card = ttk.LabelFrame(main_content, text=" 📊 系统日志与进度 ")
log_card.pack(side=RIGHT, fill=BOTH, expand=True)
log = ScrolledText(log_card, wrap=WORD, font=('Consolas', 10))
log.pack(fill=BOTH, expand=True)

def log_print(s):
    def _update():
        msg = f"[{time.strftime('%H:%M:%S')}] {s}\n"
        log.insert(END, msg)
        log.see(END)
    root.after(0, _update)

def send_heartbeat():
    while True:
        try:
            requests.post(f'{SERVER_URL}/api/heartbeat',
                json={
                    "mac_address": MAC,
                    "hostname": HOSTNAME,
                    "ip_address": socket.gethostbyname(socket.gethostname())
                }, timeout=3)
        except:
            pass
        time.sleep(5)

def sync_exam_time():
    global EXAM_START_TIME, EXAM_END_TIME, IS_EXAM_OVER
    while True:
        try:
            res = requests.get(f'{SERVER_URL}/api/get_exam_time', timeout=2).json()
            if res["code"] != 0:
                time.sleep(1)
                continue

            s_str = res["start"]
            e_str = res["end"]
            EXAM_START_TIME = s_str
            EXAM_END_TIME = e_str

            now = datetime.datetime.now()
            s_dt = datetime.datetime.strptime(s_str, "%Y-%m-%d %H:%M:%S")
            e_dt = datetime.datetime.strptime(e_str, "%Y-%m-%d %H:%M:%S")

            if now >= e_dt:
                IS_EXAM_OVER = True
                txt = f"⏰ 考试已结束"
                root.after(0, lambda: time_label.config(text=txt, bootstyle=DANGER))
                root.after(0, lambda: btn_check_upload.config(state=DISABLED))
            elif now < s_dt:
                txt = f"⏳ 等待开考"
                root.after(0, lambda: time_label.config(text=txt, bootstyle=INFO))
            else:
                delta = e_dt - now
                h = delta.seconds // 3600
                m = (delta.seconds % 3600) // 60
                s = delta.seconds % 60
                remain = f"{h:02d}:{m:02d}:{s:02d}"
                txt = f"⏱️ 剩余：{remain}"
                root.after(0, lambda: time_label.config(text=txt, bootstyle=WARNING))
        except:
            pass
        time.sleep(1)

def login():
    global USER_NAME, USER_NO, STUDENT_ID, REAL_EXAM_PATH
    name = entry_name.get().strip()
    no = entry_no.get().strip()
    if not name or not no:
        return messagebox.showwarning('提示', '请输入完整姓名和考号！')
    try:
        r = requests.post(f'{SERVER_URL}/api/login',
            json={
                'name': name,
                'student_no': no,
                'mac_address': MAC,
                'hostname': HOSTNAME
            }, timeout=5)
        res = r.json()
        if res['code'] == 0:
            USER_NAME = name
            USER_NO = no
            STUDENT_ID = res['student_id']
            REAL_EXAM_PATH = res.get('real_exam_path', '').strip()

            if REAL_EXAM_PATH:
                os.makedirs(REAL_EXAM_PATH, exist_ok=True)
                info_label.config(text=f"机器名称:\n{HOSTNAME}\n物理地址:\n{MAC}\n工作目录:\n{REAL_EXAM_PATH}")
                log_print(f'📂 考试目录：{REAL_EXAM_PATH}')
            else:
                info_label.config(text=f"机器名称:\n{HOSTNAME}\n物理地址:\n{MAC}\n工作目录:\n待选择")
                log_print("📂 考试目录：待选择")

            log_print(f'✅ 登录成功')
            btn_download.config(state=NORMAL)
            btn_check_upload.config(state=NORMAL)
            btn_login.config(state=DISABLED)
            entry_name.config(state=DISABLED)
            entry_no.config(state=DISABLED)

            threading.Thread(target=send_heartbeat, daemon=True).start()
            threading.Thread(target=sync_exam_time, daemon=True).start()
        else:
            messagebox.showerror('错误', '未找到考生信息')
    except Exception as e:
        messagebox.showerror('错误', f'连接失败：{e}')

btn_login.config(command=login)

def download_problem():
    global ZIP_FILE_PATH, REAL_EXAM_PATH
    try:
        select_dir = filedialog.askdirectory(title='选择试题保存目录')
        if not select_dir:
            log_print("🚫 未选择试题保存目录")
            return

        REAL_EXAM_PATH = select_dir
        os.makedirs(REAL_EXAM_PATH, exist_ok=True)
        info_label.config(text=f"机器名称:\n{HOSTNAME}\n物理地址:\n{MAC}\n工作目录:\n{REAL_EXAM_PATH}")
        log_print(f'📂 试题保存目录：{REAL_EXAM_PATH}')

        log_print('⬇️ 正在下载试题...')
        r = requests.get(f'{SERVER_URL}/api/download_problem', stream=True, timeout=20)
        ZIP_FILE_PATH = os.path.join(REAL_EXAM_PATH, 'exam_enc.zip')
        with open(ZIP_FILE_PATH, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        log_print('📦 试题已下载，等待开考自动解压')
        threading.Thread(target=poll_unzip, daemon=True).start()
    except Exception as e:
        log_print(f'❌ 下载失败：{e}')

btn_download.config(command=download_problem)

def poll_unzip():
    global UNZIP_DONE
    while not UNZIP_DONE:
        time.sleep(2)
        if not EXAM_START_TIME:
            continue
        try:
            now = datetime.datetime.now()
            start = datetime.datetime.strptime(EXAM_START_TIME, '%Y-%m-%d %H:%M:%S')
            if now < start:
                continue
            r = requests.get(f'{SERVER_URL}/api/get_password', timeout=5)
            if r.json()['code'] != 0:
                continue
            pwd = r.json()['password']
            log_print("🔑 开始自动解压...")
            with pyzipper.AESZipFile(ZIP_FILE_PATH, 'r') as zf:
                zf.setpassword(pwd.encode('utf-8'))
                zf.extractall(REAL_EXAM_PATH)
            os.remove(ZIP_FILE_PATH)
            UNZIP_DONE = True
            log_print("🎉 试题解压完成！")
            root.after(0, lambda: messagebox.showinfo("开考", "考试正式开始！"))
        except:
            pass

def calculate_md5(file_path):
    md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            md5.update(chunk)
    return md5.hexdigest()

def get_total_questions(exam_path):
    count = 0
    for name in os.listdir(exam_path):
        folder = os.path.join(exam_path, name)
        if os.path.isdir(folder) and "答题文件夹" in name:
            count += 1
    return count

def count_finished_questions(exam_path):
    count = 0
    for name in os.listdir(exam_path):
        folder = os.path.join(exam_path, name)
        if os.path.isdir(folder) and "答题文件夹" in name:
            if len(os.listdir(folder)) > 0:
                count += 1
    return count

def check_and_upload():
    global IS_EXAM_OVER
    if IS_EXAM_OVER:
        return messagebox.showerror("禁止","考试已结束")
    if not os.path.exists(REAL_EXAM_PATH):
        return messagebox.showerror("错误","考试目录不存在")

    submit_dir = filedialog.askdirectory(title="选择要提交的答题文件夹")
    if not submit_dir:
        log_print("🚫 未选择提交文件夹")
        return

    zip_path = os.path.join(REAL_EXAM_PATH, f"{USER_NO}.zip")

    try:
        log_print("📦 正在打包答卷...")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, _, files in os.walk(submit_dir):
                for f in files:
                    full = os.path.join(root_dir, f)
                    zf.write(full, os.path.relpath(full, submit_dir))

        finished = count_finished_questions(submit_dir)
        total = get_total_questions(submit_dir)
        size = os.path.getsize(zip_path)
        md5 = calculate_md5(zip_path)
        size_mb = size / 1024 / 1024

        log_print(f"✅ 已完成题目：{finished}/{total} 题 | 大小：{size_mb:.2f}MB | MD5：{md5}")

        confirm = messagebox.askyesno("交卷确认",
            f"考生：{USER_NAME}({USER_NO})\n"
            f"已完成题目：{finished}/{total} 题\n"
            f"文件大小：{size_mb:.2f}MB\n"
            f"MD5：{md5}\n\n"
            "确认提交后无法修改，确定交卷？")

        if not confirm:
            log_print("🚫 取消提交")
            os.remove(zip_path)
            return

        log_print("🚀 正在上传...")
        requests.post(f'{SERVER_URL}/api/upload_submit',
            data={
                'student_id': STUDENT_ID,
                'student_name': USER_NAME,
                'student_no': USER_NO,
                'mac_address': MAC,
                'hostname': HOSTNAME
            },
            files={'file': open(zip_path, 'rb')}, timeout=30)

        log_print("🌟 提交成功！")
        messagebox.showinfo("成功", "交卷完成！")
    except Exception as e:
        log_print(f"❌ 提交失败：{e}")

btn_check_upload.config(command=check_and_upload)

def poll_clean():
    while True:
        try:
            res = requests.get(f'{SERVER_URL}/api/get_clean', timeout=3)
            if res.status_code == 200 and res.json().get("code") == 0:
                if REAL_EXAM_PATH and os.path.isdir(REAL_EXAM_PATH):
                    for root, dirs, files in os.walk(REAL_EXAM_PATH, topdown=False):
                        for f in files:
                            try:
                                os.remove(os.path.join(root, f))
                            except:
                                pass
                        for d in dirs:
                            try:
                                os.rmdir(os.path.join(root, d))
                            except:
                                pass
                    log_print("🧹 远程清理完成")
        except:
            pass
        time.sleep(10)

threading.Thread(target=poll_clean, daemon=True).start()

def check_bind_on_start():
    try:
        res = requests.post(f'{SERVER_URL}/api/check_bind',
            json={'mac_address': MAC, 'hostname': HOSTNAME}, timeout=3).json()
        if res['code'] == 0:
            root.after(0, lambda: entry_name.insert(0, res['name']))
            root.after(0, lambda: entry_no.insert(0, res['student_no']))
            log_print("📡 已识别设备")
    except:
        pass

threading.Thread(target=check_bind_on_start, daemon=True).start()
root.mainloop()