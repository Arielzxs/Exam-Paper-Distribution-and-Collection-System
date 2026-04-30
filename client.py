import hashlib, os, re, sys, time, uuid, random, zipfile, datetime, socket
import pyzipper, requests, threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter.scrolledtext import ScrolledText
from tkinter import messagebox

SERVER_URL = 'http://127.0.0.1:5001'
WORK_DIR = os.path.expanduser('~/Desktop/NOI_Work')
os.makedirs(WORK_DIR, exist_ok=True)

def get_mac(): return ':'.join(re.findall('..', '%012x' % uuid.getnode()))
def get_hostname(): return socket.gethostname()
def get_file_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""): hash_md5.update(chunk)
    return hash_md5.hexdigest()

MAC, HOSTNAME = get_mac(), get_hostname()
STUDENT_ID, STUDENT_NAME, STUDENT_NO = None, '', ''
EXAM_START_TIME, EXAM_END_TIME, ZIP_FILE_PATH, UNZIP_DONE = None, None, None, False

# ===================== 现代化 GUI =====================
root = ttk.Window(title="NOI 智能考试终端", themename="litera")
root.geometry("780x600")
root.place_window_center()

header = ttk.Frame(root, padding=10)
header.pack(fill=X)
ttk.Label(header, text="🎓 NOI 智能考试终端", font=('Helvetica', 20, 'bold'), bootstyle=PRIMARY).pack(side=LEFT)
time_label = ttk.Label(header, text="🕒 考试时间: 等待同步...", font=('Helvetica', 12), bootstyle=INFO)
time_label.pack(side=RIGHT, pady=5)

main_content = ttk.Frame(root, padding=15)
main_content.pack(fill=BOTH, expand=True)

left_panel = ttk.Frame(main_content)
left_panel.pack(side=LEFT, fill=Y, padx=(0, 15))

auth_card = ttk.Labelframe(left_panel, text=" 🔒 身份验证 ", padding=15)
auth_card.pack(fill=X, pady=(0, 15))

ttk.Label(auth_card, text="考 生 姓 名").pack(anchor=W, pady=(0, 5))
entry_name = ttk.Entry(auth_card, font=('Helvetica', 11))
entry_name.pack(fill=X, pady=(0, 15))

ttk.Label(auth_card, text="考 生 考 号").pack(anchor=W, pady=(0, 5))
entry_no = ttk.Entry(auth_card, font=('Helvetica', 11))
entry_no.pack(fill=X, pady=(0, 15))

btn_login = ttk.Button(auth_card, text="验证并登录考场", bootstyle=PRIMARY, width=20)
btn_login.pack(fill=X)

env_card = ttk.Labelframe(left_panel, text=" 💻 本机环境 ", padding=15)
env_card.pack(fill=X, pady=(0, 15))
ttk.Label(env_card, text=f"机器名称:\n{HOSTNAME}", bootstyle=SECONDARY).pack(anchor=W, pady=2)
ttk.Label(env_card, text=f"物理地址:\n{MAC}", bootstyle=SECONDARY).pack(anchor=W, pady=2)
ttk.Label(env_card, text=f"工作目录:\n桌面的 NOI_Work 文件夹", bootstyle=INFO).pack(anchor=W, pady=(10,0))

action_card = ttk.Labelframe(left_panel, text=" ⚙️ 考场操作 ", padding=15)
action_card.pack(fill=X)
btn_download = ttk.Button(action_card, text="⬇️ 强行拉取试题", bootstyle=(INFO, OUTLINE), state=DISABLED)
btn_download.pack(fill=X, pady=5)
btn_check_upload = ttk.Button(action_card, text="🚀 检查并提交答卷", bootstyle=SUCCESS, state=DISABLED)
btn_check_upload.pack(fill=X, pady=5)

log_card = ttk.Labelframe(main_content, text=" 📊 系统日志与进度 ", padding=10)
log_card.pack(side=RIGHT, fill=BOTH, expand=True)

log = ScrolledText(log_card, wrap=WORD, font=('Consolas', 10))
log.pack(fill=BOTH, expand=True)

# 🚀 核心修复 1：安全的跨线程日志打印
def log_print(s, style=None):
    def _update():
        msg = f"[{time.strftime('%H:%M:%S')}] {s}\n"
        log.insert(END, msg)
        log.see(END)
    root.after(0, _update)

def poll_exam_time():
    global EXAM_START_TIME, EXAM_END_TIME
    while True:
        time.sleep(5)
        try:
            r = requests.get(f'{SERVER_URL}/api/get_exam_time', timeout=3)
            res = r.json()
            if res['code'] == 0:
                EXAM_START_TIME, EXAM_END_TIME = res['exam_start_time'], res['exam_end_time']
                # 🚀 核心修复 2：安全的跨线程更新 Label
                root.after(0, lambda: time_label.config(text=f"🕒 {EXAM_START_TIME} 至 {EXAM_END_TIME}"))
        except: pass

def login():
    global STUDENT_ID, STUDENT_NAME, STUDENT_NO
    name, no = entry_name.get().strip(), entry_no.get().strip()
    if not name or not no: return messagebox.showwarning('提示', '请输入完整的姓名和考号！')
    try:
        r = requests.post(f'{SERVER_URL}/api/login', json={'name': name, 'student_no': no, 'mac_address': MAC, 'hostname': HOSTNAME}, timeout=5)
        res = r.json()
        if res['code'] == 0:
            STUDENT_ID, STUDENT_NAME, STUDENT_NO = res['student_id'], name, no
            log_print(f'✅ 验证成功！欢迎考生 {name}', 'success')
            btn_download.config(state=NORMAL); btn_check_upload.config(state=NORMAL); btn_login.config(state=DISABLED)
            entry_name.config(state=DISABLED); entry_no.config(state=DISABLED)
            threading.Thread(target=poll_exam_time, daemon=True).start()
        else: messagebox.showerror('错误', res['msg'])
    except: messagebox.showerror('错误', '无法连接到监考服务器！')
btn_login.config(command=login)

def download_problem():
    global ZIP_FILE_PATH
    try:
        log_print('⬇️ 开始从服务器拉取加密试题...')
        r = requests.get(f'{SERVER_URL}/api/download_problem', stream=True, timeout=15)
        ZIP_FILE_PATH = os.path.join(WORK_DIR, 'exam_enc.zip')
        with open(ZIP_FILE_PATH, 'w+b') as f:
            for chunk in r.iter_content(8192): f.write(chunk)
        log_print(f'📦 加密试题已就绪。等待开考自动解压...')
        threading.Thread(target=poll_unzip, daemon=True).start()
    except Exception as e: log_print(f'❌ 拉取失败: {e}')
btn_download.config(command=download_problem)

def poll_unzip():
    global UNZIP_DONE
    while not UNZIP_DONE:
        time.sleep(3)
        if not EXAM_START_TIME: continue
        try:
            if datetime.datetime.now() < datetime.datetime.strptime(EXAM_START_TIME, '%Y-%m-%d %H:%M:%S'): continue
            r = requests.get(f'{SERVER_URL}/api/get_password', timeout=5)
            if r.json()['code'] != 0: continue
            pwd = r.json()['password']
            log_print(f"🔑 获取到开考密钥，正在解压...")
            with pyzipper.AESZipFile(ZIP_FILE_PATH, 'r') as zf:
                zf.setpassword(pwd.encode('utf-8'))
                zf.extractall(WORK_DIR)
            log_print("🎉 试题解压完毕！请前往桌面 NOI_Work 开始答题。")
            try: os.remove(ZIP_FILE_PATH)
            except: pass
            UNZIP_DONE = True
            # 🚀 核心修复 3：安全的跨线程弹窗
            root.after(0, lambda: messagebox.showinfo("开考提示", "试题已送达桌面，考试正式开始！"))
        except: pass

def check_and_upload():
    if not os.path.exists(WORK_DIR): return messagebox.showerror("错误", "未找到答题目录！")
    log_print("🔍 正在扫描答卷代码...")
    total_size, file_details, problem_folders = 0, [], set()
    try:
        for root_dir, _, filenames in os.walk(WORK_DIR):
            for f in filenames:
                if f == "重要说明.txt": continue
                fp = os.path.join(root_dir, f)
                sz, md5 = os.path.getsize(fp), get_file_md5(fp)
                folder = os.path.basename(root_dir)
                total_size += sz
                file_details.append({"name": f, "folder": folder, "size": sz, "md5": md5})
                if "答题文件夹" in folder: problem_folders.add(folder)
        
        info = f"【答卷确认】\n考生: {STUDENT_NAME} ({STUDENT_NO})\n作答题目: {len(problem_folders)}题\n文件数量: {len(file_details)}个\n\n确认无误并提交？"
        if not messagebox.askyesno("交卷确认", info): return
        
        log_print("🚀 正在打包加密传输...")
        zip_path = os.path.join(WORK_DIR, f"{STUDENT_NO}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_, _, files_ in os.walk(WORK_DIR):
                for file_ in files_:
                    if file_ != f"{STUDENT_NO}.zip":
                        ff = os.path.join(root_, file_)
                        zf.write(ff, os.path.relpath(ff, WORK_DIR))
        
        requests.post(f'{SERVER_URL}/api/upload_submit', 
                      data={'student_id': STUDENT_ID, 'student_name': STUDENT_NAME, 'student_no': STUDENT_NO, 'mac_address': MAC, 'hostname': HOSTNAME}, 
                      files={'file': open(zip_path, 'rb')}, timeout=15)
        log_print("🌟 提交成功！数据已安全存入服务器。")
        messagebox.showinfo("成功", "交卷成功！你可以离开考场了。")
    except Exception as e: log_print(f"❌ 提交通道异常: {e}")
btn_check_upload.config(command=check_and_upload)

def poll_clean():
    while True:
        time.sleep(10)
        try:
            if requests.get(f'{SERVER_URL}/api/get_clean', timeout=3).json().get('command') == 'clean':
                for f in os.listdir(WORK_DIR):
                    try: os.remove(os.path.join(WORK_DIR, f))
                    except: pass
                log_print("🧹 收到监考端指令，工作区已安全清理。")
        except: pass
threading.Thread(target=poll_clean, daemon=True).start()

def check_bind_on_start():
    try:
        res = requests.post(f'{SERVER_URL}/api/check_bind', json={'mac_address': MAC, 'hostname': HOSTNAME}, timeout=3).json()
        if res['code'] == 0:
            # 🚀 核心修复 4：安全的跨线程填充输入框
            def _fill_entries():
                entry_name.insert(0, res['name'])
                entry_no.insert(0, res['student_no'])
                log_print("📡 已自动读取机器绑定信息。")
            root.after(0, _fill_entries)
    except: pass
threading.Thread(target=check_bind_on_start, daemon=True).start()

root.mainloop()