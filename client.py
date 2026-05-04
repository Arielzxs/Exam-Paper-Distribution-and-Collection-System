import hashlib, os, re, sys, time, uuid, random, zipfile, datetime, socket, platform
import json
import shutil

import pyzipper, requests, threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter.scrolledtext import ScrolledText
from tkinter import messagebox, filedialog

# ===================== 配置文件读取逻辑 =====================
CONFIG_FILE = 'config.json'
DEFAULT_SERVER_URL = 'http://127.0.0.1:5001'

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            SERVER_URL = cfg.get('server_url', DEFAULT_SERVER_URL)
    except Exception as e:
        print(f"读取配置文件失败，使用默认设置: {e}")
        SERVER_URL = DEFAULT_SERVER_URL
else:
    SERVER_URL = DEFAULT_SERVER_URL
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'server_url': SERVER_URL}, f, indent=4)
    except Exception as e:
        print(f"无法创建默认配置文件: {e}")
# ===================================================================

UDP_PORT = 5002

MAC, HOSTNAME = None, None
STUDENT_ID, STUDENT_NAME, STUDENT_NO = None, '', ''
EXAM_INFO = None
LOCAL_WORK_DIR = None
IS_EXAM_OVER = False
PAPER_FILE_PATH = None
AUTO_DOWNLOADED = False


def get_mac(): return ':'.join(re.findall('..', '%012x' % uuid.getnode()))


def get_hostname(): return socket.gethostname()


def init_system():
    global MAC, HOSTNAME
    MAC = get_mac()
    HOSTNAME = get_hostname()


def udp_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('', UDP_PORT))
    while True:
        try:
            data, addr = s.recvfrom(1024)
            if data == b"NOI_DISCOVER":
                msg = f"NOI_HOST|{MAC}|{HOSTNAME}".encode('utf-8')
                s.sendto(msg, (addr[0], 5003))
        except:
            pass


def calculate_md5(file_path):
    """计算文件MD5"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def get_dir_size(start_path):
    """计算目录总大小"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size


def is_folder_empty(folder_path):
    """判断文件夹是否为空（忽略.DS_Store等系统文件）"""
    if not os.path.exists(folder_path):
        return True
    for item in os.listdir(folder_path):
        if item.startswith('.'):
            continue
        return False
    return True


class ClientGUI:
    def __init__(self, root):
        self.root = root
        self.root.title('NOI 智能考试终端')
        self.root.geometry("1600x1200")
        self.root.place_window_center()

        header = ttk.Frame(root, padding=10)
        header.pack(fill=X)
        ttk.Label(header, text="🎓 NOI 智能考试终端", font=('Helvetica', 20, 'bold'), bootstyle=PRIMARY).pack(side=LEFT)

        self.time_label = ttk.Label(
            header,
            text="🕒 等待连接...",
            font=('Helvetica', 11),
            bootstyle=INFO
        )
        self.time_label.pack(side=RIGHT, pady=5)

        main_content = ttk.Frame(root, padding=15)
        main_content.pack(fill=BOTH, expand=True)

        left_container = ttk.Frame(main_content)
        left_container.pack(side=LEFT, fill=Y, padx=(0, 15))

        auth_card = ttk.Labelframe(left_container, text=" 🔒 身份验证 ", padding=15)
        auth_card.pack(fill=X, pady=(0, 15))

        ttk.Label(auth_card, text="考 生 姓 名").pack(anchor=W, pady=(0, 5))
        self.entry_name = ttk.Entry(auth_card, font=('Helvetica', 11))
        self.entry_name.pack(fill=X, pady=(0, 15))

        ttk.Label(auth_card, text="考 生 考 号").pack(anchor=W, pady=(0, 5))
        self.entry_no = ttk.Entry(auth_card, font=('Helvetica', 11))
        self.entry_no.pack(fill=X, pady=(0, 15))

        self.btn_login = ttk.Button(auth_card, text="验证并登录考场", bootstyle=PRIMARY, command=self.login)
        self.btn_login.pack(fill=X)

        env_card = ttk.Labelframe(left_container, text=" 💻 本机环境 ", padding=15)
        env_card.pack(fill=X, pady=(0, 15))
        ttk.Label(env_card, text=f"系统平台:\n{platform.system()} {platform.release()}", bootstyle=SECONDARY).pack(
            anchor=W, pady=2)
        ttk.Label(env_card, text=f"机器名称:\n{HOSTNAME}", bootstyle=SECONDARY).pack(anchor=W, pady=2)
        ttk.Label(env_card, text=f"物理地址:\n{MAC}", bootstyle=SECONDARY).pack(anchor=W, pady=2)

        action_card = ttk.Labelframe(left_container, text=" ⚙️ 考场操作 ", padding=15)
        action_card.pack(fill=X)

        self.btn_get_paper = ttk.Button(action_card, text="📥 获取试卷（备用）", bootstyle=(INFO, OUTLINE), state=DISABLED,
                                        command=self.get_paper)
        self.btn_get_paper.pack(fill=X, pady=5)

        self.btn_get_pwd = ttk.Button(action_card, text="🔑 获取解压密码", bootstyle=(WARNING, OUTLINE), state=DISABLED,
                                      command=self.get_password)
        self.btn_get_pwd.pack(fill=X, pady=5)

        self.btn_upload = ttk.Button(action_card, text="🚀 提交答卷", bootstyle=SUCCESS, state=DISABLED,
                                     command=self.prepare_submit)
        self.btn_upload.pack(fill=X, pady=5)

        log_card = ttk.Labelframe(main_content, text=" 📊 系统日志 ", padding=10)
        log_card.pack(side=RIGHT, fill=BOTH, expand=True)
        self.log = ScrolledText(log_card, wrap=WORD, font=('Consolas', 10))
        self.log.pack(fill=BOTH, expand=True)

        self.log_print('✅ 客户端已启动')
        self.log_print(f'💻 当前系统: {platform.system()}')
        self.log_print(f'🌐 连接地址: {SERVER_URL}')
        self.log_print(f'🖥️  本机MAC: {MAC}')
        self.log_print(f'🖥️  本机主机名: {HOSTNAME}')
        self.log_print('🔒 登录校验：姓名+考号+MAC+主机名 四重验证')

        threading.Thread(target=udp_listener, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self.sync_time_and_paper_loop, daemon=True).start()

    def log_print(self, msg):
        def _update():
            self.log.insert(END, f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}\n')
            self.log.see(END)

        self.root.after(0, _update)

    def flash_button(self, button):
        original_style = button.cget("style") or ""
        flash_style = "Flash.TButton"
        style = ttk.Style()
        style.configure(flash_style, background="#ffb347")

        def _toggle(count=0):
            if count >= 6:
                button.config(style=original_style)
                return
            button.config(style=flash_style if count % 2 == 0 else original_style)
            self.root.after(120, lambda: _toggle(count + 1))

        _toggle()

    def login(self):
        """强化版登录：校验 姓名+考号+MAC+主机名，禁止跨机登录"""
        global STUDENT_ID, STUDENT_NAME, STUDENT_NO, EXAM_INFO, LOCAL_WORK_DIR, AUTO_DOWNLOADED

        name = self.entry_name.get().strip()
        no = self.entry_no.get().strip()

        if not name or not no:
            messagebox.showwarning('提示', '请输入完整姓名和考号！')
            return

        self.log_print('🔄 正在登录... 校验：姓名+考号+MAC+主机名')
        self.flash_button(self.btn_login)

        try:
            r_info = requests.get(f'{SERVER_URL}/api/get_exam_info', timeout=5)
            info_res = r_info.json()

            if info_res['code'] == 0:
                EXAM_INFO = info_res
                if platform.system() == 'Windows':
                    LOCAL_WORK_DIR = EXAM_INFO.get('client_path_win', 'D:\\NOI_Exam')
                else:
                    LOCAL_WORK_DIR = EXAM_INFO.get('client_path_linux', '/home/NOI_Exam')

                self.log_print(f'📋 已获取考试配置: {EXAM_INFO["exam_name"]}')
                self.log_print(f'📂 本地工作目录: {LOCAL_WORK_DIR}')

                try:
                    os.makedirs(LOCAL_WORK_DIR, exist_ok=True)
                except Exception as e:
                    self.log_print(f'⚠️ 创建目录失败: {str(e)}')
            else:
                self.log_print(f'⚠️ 考试未发布: {info_res.get("msg", "")}')

            # 核心：发送MAC+主机名，服务端强制校验
            r = requests.post(f'{SERVER_URL}/api/login',
                              json={
                                  'name': name,
                                  'student_no': no,
                                  'mac_address': MAC,
                                  'hostname': HOSTNAME
                              }, timeout=5)
            res = r.json()

            if res['code'] == 0:
                STUDENT_ID, STUDENT_NAME, STUDENT_NO = res['student_id'], name, no
                AUTO_DOWNLOADED = False
                self.log_print(f'✅ 验证成功！欢迎考生 {name}')
                self.log_print(f'✅ 机器校验通过：当前MAC/主机名匹配绑定信息')
                self.log_print('📡 正在等待监考老师下发试卷...')
                messagebox.showinfo("验证成功", f"欢迎考生 {name}！\n机器校验通过，登录成功！")

                self.btn_login.config(state=DISABLED)
                self.btn_get_paper.config(state=NORMAL)
                self.btn_get_pwd.config(state=NORMAL)
                self.btn_upload.config(state=NORMAL)

                threading.Thread(target=self.send_heartbeat, daemon=True).start()

            # 服务端返回的跨机错误
            elif res['code'] == -2:
                self.log_print(f'❌ 登录失败：该考生已绑定其他机器，禁止在此登录！')
                messagebox.showerror('错误', '该考生已绑定其他电脑，无法在本机登录！')
            elif res['code'] == -3:
                self.log_print(f'❌ 登录失败：本机已绑定其他考生！')
                messagebox.showerror('错误', '本机已绑定其他考生，请使用对应账号登录！')
            else:
                msg = res.get('msg', '未找到该考生信息')
                self.log_print(f'❌ 登录失败：{msg}')
                messagebox.showerror('错误', msg)

        except Exception as e:
            self.log_print(f'❌ 连接失败：{str(e)}')
            self.log_print(f'💡 请检查 config.json 中的服务器地址是否正确')
            messagebox.showerror('错误', f'无法连接到监考服务器！\n地址: {SERVER_URL}\n\n请检查 config.json 配置文件。')

    def get_paper(self, is_auto=False):
        global PAPER_FILE_PATH, AUTO_DOWNLOADED

        if not EXAM_INFO or not EXAM_INFO.get('has_paper'):
            if not is_auto:
                messagebox.showwarning('提示', '试卷尚未发布！')
            return False

        if not LOCAL_WORK_DIR:
            if not is_auto:
                messagebox.showerror('错误', '工作目录未设置！')
            return False

        if is_auto:
            self.log_print('📤 检测到试卷已下发，开始自动下载...')
        else:
            self.log_print('⬇️ 正在手动下载试卷...')
            self.flash_button(self.btn_get_paper)

        try:
            r = requests.get(f'{SERVER_URL}/api/download_paper', stream=True, timeout=60)

            if r.status_code == 200:
                filename = r.headers.get('Content-Disposition')
                if filename:
                    filename = re.findall('filename="?(.+)"?', filename)[0]
                else:
                    filename = f"{STUDENT_NO}_paper.zip"

                PAPER_FILE_PATH = os.path.join(LOCAL_WORK_DIR, filename)

                with open(PAPER_FILE_PATH, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

                self.log_print(f'✅ 试卷下载成功！')
                self.log_print(f'📦 保存路径: {PAPER_FILE_PATH}')

                if is_auto:
                    AUTO_DOWNLOADED = True
                    self.root.after(0, lambda: messagebox.showinfo(
                        "试卷已自动下载",
                        f"试卷已成功下载至：\n{PAPER_FILE_PATH}\n\n请等待密码下发后手动解压。"
                    ))
                else:
                    messagebox.showinfo("下载完成", f"试卷已下载至：\n{PAPER_FILE_PATH}")

                return True
            else:
                try:
                    err_json = r.json()
                    msg = err_json.get('msg', '下载失败，请等待监考老师下发试卷')
                except:
                    msg = '下载失败'
                self.log_print(f'❌ {msg}')
                if not is_auto:
                    messagebox.showerror("错误", msg)
                return False

        except Exception as e:
            self.log_print(f'❌ 下载异常: {str(e)}')
            if not is_auto:
                messagebox.showerror("错误", f"下载异常：{str(e)}")
            return False

    def get_password(self):
        self.log_print('🔄 正在请求密码...')
        self.flash_button(self.btn_get_pwd)

        try:
            r = requests.get(f'{SERVER_URL}/api/get_password', timeout=5)
            res = r.json()

            if res['code'] == 0:
                pwd = res['password']
                self.log_print(f'✅ 成功获取解压密码！')
                self.show_password_dialog(pwd)
            else:
                msg = res.get('msg', '获取失败')
                self.log_print(f'⏳ {msg}')
                messagebox.showinfo('提示', msg)

        except Exception as e:
            self.log_print(f'❌ 请求失败: {str(e)}')
            messagebox.showerror("错误", f"请求失败：{str(e)}")

    def show_password_dialog(self, password):
        win = tk.Toplevel(self.root)
        win.title("解压密码已获取")
        win.geometry("450x250")
        win.transient(self.root)
        win.grab_set()

        win.update_idletasks()
        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        window_width = win.winfo_width()
        window_height = win.winfo_height()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        win.geometry(f"+{x}+{y}")

        ttk.Label(win, text="请使用以下密码手动解压试卷：", font=('微软雅黑', 12), padding=20).pack()

        pwd_frame = ttk.Frame(win, padding=10)
        pwd_frame.pack(fill=X, padx=30)

        pwd_entry = ttk.Entry(pwd_frame, font=('Consolas', 16, 'bold'), justify='center')
        pwd_entry.insert(0, password)
        pwd_entry.config(state='readonly')
        pwd_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))

        def copy_pwd():
            self.root.clipboard_clear()
            self.root.clipboard_append(password)
            copy_btn.config(text="✅ 已复制", bootstyle=SUCCESS)
            self.log_print("📋 密码已复制到剪贴板")

        copy_btn = ttk.Button(pwd_frame, text="📋 复制密码", bootstyle=PRIMARY, command=copy_pwd)
        copy_btn.pack(side=RIGHT)

        ttk.Label(win, text="请妥善保管，解压到工作目录后开始答题。", padding=20, bootstyle=SECONDARY).pack()

        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=10)

    # ===================== 交卷前检查与确认 =====================
    def prepare_submit(self):
        global IS_EXAM_OVER

        if IS_EXAM_OVER:
            return messagebox.showerror("禁止", "考试已结束，无法交卷！")

        if not LOCAL_WORK_DIR or not os.path.exists(LOCAL_WORK_DIR):
            return messagebox.showerror("错误", "工作目录不存在！")

        self.log_print("🔍 正在扫描答题目录...")
        self.flash_button(self.btn_upload)

        answered_count = 0
        total_count = 0
        answer_folders = []

        for item in os.listdir(LOCAL_WORK_DIR):
            item_path = os.path.join(LOCAL_WORK_DIR, item)
            if os.path.isdir(item_path) and item.startswith("答题文件夹_"):
                total_count += 1
                answer_folders.append(item)
                if not is_folder_empty(item_path):
                    answered_count += 1

        if total_count == 0:
            self.log_print("❌ 未找到答题文件夹！")
            return messagebox.showerror("错误", "未在工作目录中找到答题文件夹！\n请确保试卷已正确解压。")

        total_size_bytes = get_dir_size(LOCAL_WORK_DIR)
        total_size_mb = total_size_bytes / (1024 * 1024)

        temp_zip_path = os.path.join(LOCAL_WORK_DIR, f"temp_{STUDENT_NO}.zip")
        try:
            self.log_print("📦 正在生成校验包...")
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(LOCAL_WORK_DIR):
                    if os.path.basename(root) == 'temp' or temp_zip_path in root:
                        continue
                    for file in files:
                        if file == os.path.basename(temp_zip_path):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, LOCAL_WORK_DIR)
                        zf.write(file_path, arcname)

            md5_hash = calculate_md5(temp_zip_path)
        except Exception as e:
            self.log_print(f"❌ 生成校验包失败: {e}")
            return messagebox.showerror("错误", f"打包失败：{e}")
        finally:
            if os.path.exists(temp_zip_path):
                try:
                    os.remove(temp_zip_path)
                except:
                    pass

        self.show_submit_confirm(answered_count, total_count, total_size_mb, md5_hash)

    def show_submit_confirm(self, answered, total, size_mb, md5):
        win = tk.Toplevel(self.root)
        win.title("确认提交答卷")
        win.transient(self.root)
        win.grab_set()

        win.minsize(width=800, height=450)

        main_frame = ttk.Frame(win, padding=30)
        main_frame.pack(fill=BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="📋 答卷信息确认", font=("微软雅黑", 22, "bold"), bootstyle=PRIMARY)
        title_label.pack(pady=(0, 25))

        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=X, pady=10)
        info_frame.columnconfigure(1, weight=1)

        row_idx = 0

        ttk.Label(info_frame, text="答题进度：", font=("微软雅黑", 14)).grid(row=row_idx, column=0, sticky=W, pady=8)

        progress_text = f"{answered} / {total}"
        progress_color = "success" if answered == total else "warning"

        lbl_progress = ttk.Label(info_frame, text=progress_text, font=("微软雅黑", 16, "bold"),
                                 bootstyle=progress_color)
        lbl_progress.grid(row=row_idx, column=1, sticky=W, pady=8)

        if answered < total:
            lbl_warn = ttk.Label(info_frame, text="⚠️ 存在未作答题目", font=("微软雅黑", 12), bootstyle="danger")
            lbl_warn.grid(row=row_idx, column=2, sticky=W, padx=(15, 0), pady=8)
        row_idx += 1

        ttk.Label(info_frame, text="文件大小：", font=("微软雅黑", 14)).grid(row=row_idx, column=0, sticky=W, pady=8)
        ttk.Label(info_frame, text=f"{size_mb:.2f} MB", font=("微软雅黑", 14)).grid(row=row_idx, column=1, sticky=W,
                                                                                    pady=8, columnspan=2)
        row_idx += 1

        ttk.Label(info_frame, text="MD5校验：", font=("微软雅黑", 14)).grid(row=row_idx, column=0, sticky=W, pady=8)

        md5_var = tk.StringVar(value=md5)
        md5_entry = ttk.Entry(info_frame, textvariable=md5_var, state="readonly", font=("Consolas", 10), width=35)
        md5_entry.grid(row=row_idx, column=1, sticky=EW, pady=8, columnspan=2)
        row_idx += 1

        ttk.Separator(main_frame, orient=HORIZONTAL).pack(fill=X, pady=20)

        info_bottom = ttk.Frame(main_frame)
        info_bottom.pack(fill=X)

        ttk.Label(info_bottom, text=f"考生姓名：{STUDENT_NAME}", font=("微软雅黑", 14, "bold")).pack(side=LEFT)
        ttk.Label(info_bottom, text=f"考生考号：{STUDENT_NO}", font=("微软雅黑", 14, "bold")).pack(side=RIGHT)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=X, pady=(30, 0))

        self.submit_confirmed = False

        def on_confirm():
            self.submit_confirmed = True
            win.destroy()

        def on_cancel():
            self.submit_confirmed = False
            win.destroy()

        btn_cancel = ttk.Button(btn_frame, text="❌ 取消提交", bootstyle=(SECONDARY, OUTLINE), command=on_cancel)
        btn_cancel.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))

        btn_confirm = ttk.Button(btn_frame, text="✅ 确认提交", bootstyle=SUCCESS, command=on_confirm)
        btn_confirm.pack(side=RIGHT, fill=X, expand=True, padx=(10, 0))

        win.update_idletasks()
        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        window_width = win.winfo_width()
        window_height = win.winfo_height()

        max_height = int(screen_height * 0.9)
        if window_height > max_height:
            window_height = max_height
            win.geometry(f"{window_width}x{window_height}")

        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        win.geometry(f"+{x}+{y}")

        self.root.wait_window(win)

        if self.submit_confirmed:
            self.do_submit(md5_hash)

    def do_submit(self, md5_hash):
        self.log_print("🚀 正在打包并上传答卷...")

        final_zip_name = f"{STUDENT_NO}_{STUDENT_NAME}.zip"
        final_zip_path = os.path.join(LOCAL_WORK_DIR, final_zip_name)

        try:
            with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(LOCAL_WORK_DIR):
                    for file in files:
                        if file == final_zip_name:
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, LOCAL_WORK_DIR)
                        zf.write(file_path, arcname)

            self.log_print(f"📦 答卷打包完成: {final_zip_name}")

        except Exception as e:
            self.log_print(f"❌ 打包失败: {e}")
            return messagebox.showerror("错误", f"打包失败：{e}")

        try:
            with open(final_zip_path, 'rb') as f:
                files = {'file': (final_zip_name, f, 'application/zip')}
                data = {
                    'student_id': STUDENT_ID,
                    'student_name': STUDENT_NAME,
                    'student_no': STUDENT_NO,
                    'md5': md5_hash
                }

                r = requests.post(f'{SERVER_URL}/api/upload_submit',
                                  files=files, data=data, timeout=60)

                res = r.json()
                if res['code'] == 0:
                    self.log_print("🌟 提交成功！")
                    messagebox.showinfo("成功", "交卷完成！\n\n请不要关闭电脑，等待监考老师确认。")
                    self.btn_upload.config(state=DISABLED)
                else:
                    self.log_print(f"❌ 提交失败: {res.get('msg', '')}")
                    messagebox.showerror("错误", f"提交失败：{res.get('msg', '')}")

        except Exception as e:
            self.log_print(f"❌ 提交异常: {e}")
            messagebox.showerror("错误", f"提交异常：{e}")
        finally:
            pass

    def send_heartbeat(self):
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

    def heartbeat_loop(self):
        """自动识别绑定考生：严格校验MAC+主机名"""
        try:
            res = requests.post(f'{SERVER_URL}/api/check_bind',
                                json={'mac_address': MAC, 'hostname': HOSTNAME}, timeout=3).json()
            if res['code'] == 0:
                def fill():
                    self.entry_name.delete(0, END)
                    self.entry_name.insert(0, res['name'])
                    self.entry_no.delete(0, END)
                    self.entry_no.insert(0, res['student_no'])
                    self.log_print("📡 自动识别成功：本机绑定考生信息已加载")
                    self.log_print(f"✅ 考生：{res['name']} ({res['student_no']})")

                self.root.after(0, fill)
        except:
            pass

    def sync_time_and_paper_loop(self):
        global IS_EXAM_OVER, EXAM_INFO, AUTO_DOWNLOADED
        while True:
            try:
                res = requests.get(f'{SERVER_URL}/api/get_exam_time', timeout=2).json()
                if res["code"] == 0:
                    s_str, e_str = res["start"], res["end"]
                    now = datetime.datetime.now()
                    s_dt = datetime.datetime.strptime(s_str, "%Y-%m-%d %H:%M:%S")
                    e_dt = datetime.datetime.strptime(e_str, "%Y-%m-%d %H:%M:%S")

                    if now >= e_dt:
                        IS_EXAM_OVER = True
                        txt = f"⏰ 考试已结束\n{s_str} ~ {e_str}"
                        self.root.after(0, lambda: self.time_label.config(text=txt, bootstyle=DANGER))
                    elif now < s_dt:
                        txt = f"📅 等待开考\n{s_str} ~ {e_str}"
                        self.root.after(0, lambda: self.time_label.config(text=txt, bootstyle=INFO))
                    else:
                        delta = e_dt - now
                        h, m, s = delta.seconds // 3600, (delta.seconds % 3600) // 60, delta.seconds % 60
                        txt = f"⏱️ 剩余：{h:02d}:{m:02d}:{s:02d}"
                        self.root.after(0, lambda: self.time_label.config(text=txt, bootstyle=WARNING))

                if STUDENT_ID is not None and not AUTO_DOWNLOADED:
                    r_info = requests.get(f'{SERVER_URL}/api/get_exam_info', timeout=5)
                    info_res = r_info.json()

                    if info_res['code'] == 0 and info_res.get('paper_released', False):
                        self.get_paper(is_auto=True)

                if STUDENT_ID is not None:
                    try:
                        r_clean = requests.get(f'{SERVER_URL}/api/get_clean_status', timeout=2)
                        clean_res = r_clean.json()

                        if clean_res.get('need_clean', False):
                            self.root.after(0, lambda: self.execute_remote_clean())
                    except Exception as e:
                        pass

            except:
                pass
            time.sleep(3)

    def execute_remote_clean(self):
        self.log_print("🧹 收到监考端强制目录清空指令")

        if not LOCAL_WORK_DIR or not os.path.isdir(LOCAL_WORK_DIR):
            self.log_print("ℹ️ 工作目录不存在，无需清理")
            self.report_clean_done()
            return

        try:
            for item in os.listdir(LOCAL_WORK_DIR):
                item_path = os.path.join(LOCAL_WORK_DIR, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except Exception as e:
                    self.log_print(f"⚠️ 删除失败: {item}")

            self.log_print("✅ 已完全清空工作目录（文件+文件夹全部清除）")

            self.report_clean_done()

            global STUDENT_ID, AUTO_DOWNLOADED
            STUDENT_ID = None
            AUTO_DOWNLOADED = False
            self.btn_login.config(state=NORMAL)
            self.btn_upload.config(state=DISABLED)

        except Exception as e:
            self.log_print(f"❌ 目录清空异常: {str(e)}")

    def report_clean_done(self):
        try:
            requests.post(f'{SERVER_URL}/api/clean_done', timeout=2)
        except:
            pass


if __name__ == '__main__':
    init_system()
    root = ttk.Window(title="NOI 智能考试终端", themename="litera")
    app = ClientGUI(root)
    root.mainloop()