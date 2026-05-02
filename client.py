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
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

MAC, HOSTNAME = get_mac(), get_hostname()
STUDENT_ID, STUDENT_NAME, STUDENT_NO = None, '', ''
EXAM_START_TIME, EXAM_END_TIME = None, None
ZIP_FILE_PATH, UNZIP_DONE = None, False
IS_EXAM_OVER = False

# ===================== GUI =====================
root = ttk.Window(title="NOI 智能考试终端", themename="litera")
root.geometry("780x600")
root.place_window_center()

header = ttk.Frame(root)
header.pack(fill=X, padx=10, pady=10)
ttk.Label(header, text="🎓 NOI 智能考试终端", font=('Helvetica', 20, 'bold'), bootstyle=PRIMARY).pack(side=LEFT)

# 【考试时间显示】
time_label = ttk.Label(
    header,
    text="🕒 等待同步考试时间...",
    font=('Helvetica', 11),
    bootstyle=INFO
)
time_label.pack(side=RIGHT, pady=5)

main_content = ttk.Frame(root)
main_content.pack(fill=BOTH, expand=True, padx=15, pady=15)

# ===== 左侧滚动区域 =====
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

# 身份验证
auth_card = ttk.LabelFrame(left_panel, text=" 🔒 身份验证 ")
auth_card.pack(fill=X, pady=(0, 15))
ttk.Label(auth_card, text="考 生 姓 名").pack(anchor=W, pady=(0, 5))
entry_name = ttk.Entry(auth_card, font=('Helvetica', 11))
entry_name.pack(fill=X, pady=(0, 15))
ttk.Label(auth_card, text="考 生 考 号").pack(anchor=W, pady=(0, 5))
entry_no = ttk.Entry(auth_card, font=('Helvetica', 11))
entry_no.pack(fill=X, pady=(0, 15))
btn_login = ttk.Button(auth_card, text="验证并登录考场", bootstyle=PRIMARY, width=20)
btn_login.pack(fill=X)

# 本机环境
env_card = ttk.LabelFrame(left_panel, text=" 💻 本机环境 ")
env_card.pack(fill=X, pady=(0, 15))
ttk.Label(env_card, text=f"机器名称:\n{HOSTNAME}", bootstyle=SECONDARY).pack(anchor=W, pady=2)
ttk.Label(env_card, text=f"物理地址:\n{MAC}", bootstyle=SECONDARY).pack(anchor=W, pady=2)
ttk.Label(env_card, text=f"工作目录:\n桌面的 NOI_Work 文件夹", bootstyle=INFO).pack(anchor=W, pady=(10, 0))

# 考场操作
action_card = ttk.LabelFrame(left_panel, text=" ⚙️ 考场操作 ")
action_card.pack(fill=X)
btn_download = ttk.Button(action_card, text="⬇️ 强行拉取试题", bootstyle=(INFO, OUTLINE), state=DISABLED)
btn_download.pack(fill=X, pady=5)
btn_check_upload = ttk.Button(action_card, text="🚀 检查并提交答卷", bootstyle=SUCCESS, state=DISABLED)
btn_check_upload.pack(fill=X, pady=5)

# 日志
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

# ===================== 心跳包 =====================
def send_heartbeat():
    while True:
        time.sleep(5)
        try:
            requests.post(f'{SERVER_URL}/api/heartbeat',
                json={
                    "mac_address": MAC,
                    "hostname": HOSTNAME,
                    "ip_address": socket.gethostbyname(socket.gethostname())
                }, timeout=3)
        except:
            pass

# ===================== 【核心】实时同步剩余时间 =====================
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

            # 已结束
            if now >= e_dt:
                IS_EXAM_OVER = True
                txt = f"⏰ 考试已结束\n{s_str} ~ {e_str}"
                root.after(0, lambda: time_label.config(text=txt, bootstyle=DANGER))
                root.after(0, lambda: btn_check_upload.config(state=DISABLED))

            # 未开考
            elif now < s_dt:
                txt = f"📅 考试时段：{s_str} ~ {e_str}\n⏳ 等待开考"
                root.after(0, lambda: time_label.config(text=txt, bootstyle=INFO))

            # 考试中 → 显示剩余时间
            else:
                delta = e_dt - now
                h = delta.seconds // 3600
                m = (delta.seconds % 3600) // 60
                s = delta.seconds % 60
                remain = f"{h:02d}:{m:02d}:{s:02d}"
                txt = f"📅 {s_str} ~ {e_str}\n⏱️ 剩余：{remain}"
                root.after(0, lambda: time_label.config(text=txt, bootstyle=WARNING))
        except:
            pass
        time.sleep(1)

# ===================== 登录 =====================
def login():
    global STUDENT_ID, STUDENT_NAME, STUDENT_NO
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
            STUDENT_ID = res['student_id']
            STUDENT_NAME = name
            STUDENT_NO = no
            log_print(f'✅ 验证成功！欢迎考生 {name}')
            btn_download.config(state=NORMAL)
            btn_check_upload.config(state=NORMAL)
            btn_login.config(state=DISABLED)
            entry_name.config(state=DISABLED)
            entry_no.config(state=DISABLED)

            threading.Thread(target=send_heartbeat, daemon=True).start()
            threading.Thread(target=sync_exam_time, daemon=True).start()
        else:
            messagebox.showerror('错误', '未找到该考生信息')
    except:
        messagebox.showerror('错误', '无法连接到监考服务器！')

btn_login.config(command=login)

# ===================== 下载试题 =====================
def download_problem():
    global ZIP_FILE_PATH
    try:
        log_print('⬇️ 开始拉取加密试题...')
        r = requests.get(f'{SERVER_URL}/api/download_problem', stream=True, timeout=20)
        ZIP_FILE_PATH = os.path.join(WORK_DIR, 'exam_enc.zip')
        with open(ZIP_FILE_PATH, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        log_print('📦 试题已就绪，等待开考自动解压')
        threading.Thread(target=poll_unzip, daemon=True).start()
    except Exception as e:
        log_print(f'❌ 拉取失败: {e}')

btn_download.config(command=download_problem)

# ===================== 自动解压 =====================
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
            log_print("🔑 已获取开考密钥，正在解压...")
            with pyzipper.AESZipFile(ZIP_FILE_PATH, 'r') as zf:
                zf.setpassword(pwd.encode('utf-8'))
                zf.extractall(WORK_DIR)
            log_print("🎉 试题已解压到桌面 NOI_Work")
            try:
                os.remove(ZIP_FILE_PATH)
            except:
                pass
            UNZIP_DONE = True
            root.after(0, lambda: messagebox.showinfo("开考", "考试开始！"))
        except:
            pass

# ===================== 提交答卷 =====================
def check_and_upload():
    global IS_EXAM_OVER
    if IS_EXAM_OVER:
        messagebox.showerror("禁止","考试已结束，无法交卷！")
        return
    if not os.path.exists(WORK_DIR):
        return messagebox.showerror("错误", "未找到答题目录")
    log_print("🔍 正在扫描答卷...")
    try:
        zip_path = os.path.join(WORK_DIR, f"{STUDENT_NO}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, _, files in os.walk(WORK_DIR):
                for f in files:
                    if f == os.path.basename(zip_path):
                        continue
                    full = os.path.join(root_dir, f)
                    zf.write(full, os.path.relpath(full, WORK_DIR))

        requests.post(f'{SERVER_URL}/api/upload_submit',
            data={
                'student_id': STUDENT_ID,
                'student_name': STUDENT_NAME,
                'student_no': STUDENT_NO,
                'mac_address': MAC,
                'hostname': HOSTNAME
            },
            files={'file': open(zip_path, 'rb')}, timeout=20)

        log_print("🌟 提交成功！")
        messagebox.showinfo("成功", "交卷完成！")
    except Exception as e:
        log_print(f"❌ 提交失败: {e}")

btn_check_upload.config(command=check_and_upload)

# ===================== 远程清理 =====================
def poll_clean():
    while True:
        time.sleep(10)
        try:
            if requests.get(f'{SERVER_URL}/api/get_clean', timeout=3).json().get('code') == 0:
                for fn in os.listdir(WORK_DIR):
                    try:
                        os.remove(os.path.join(WORK_DIR, fn))
                    except:
                        pass
                log_print("🧹 工作区已清空")
        except:
            pass

threading.Thread(target=poll_clean, daemon=True).start()

# ===================== 开机绑定 =====================
def check_bind_on_start():
    try:
        res = requests.post(f'{SERVER_URL}/api/check_bind',
            json={'mac_address': MAC, 'hostname': HOSTNAME}, timeout=3).json()
        if res['code'] == 0:
            def fill():
                entry_name.insert(0, res['name'])
                entry_no.insert(0, res['student_no'])
                log_print("📡 已自动识别设备")
            root.after(0, fill)
    except:
        pass

threading.Thread(target=check_bind_on_start, daemon=True).start()
root.mainloop()