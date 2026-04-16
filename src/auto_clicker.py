"""
自动点击器 - 在框选区域内模拟人类点击 (UE5 兼容版)
用法：
  1. 运行脚本（会自动请求管理员权限）
  2. 用鼠标拖拽框选点击区域
  3. 框选完成后自动开始点击（每 1.1~1.5 秒随机间隔）
  4. 按 F6 暂停/恢复，按 F7 重新框选，按 Esc 退出
"""

import ctypes
import ctypes.wintypes
import logging
import math
import os
import random
import string
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox


# ====================================================
# 依赖检查（在提权前执行，缺少则弹窗并禁止启动）
# ====================================================

def _check_dependencies():
    """检测所有必需第三方依赖，未安装则弹窗列出并退出"""
    missing = []
    checks = [
        ('interception',  'interception-python'),
        ('win32api',      'pywin32'),
    ]
    for mod, pip_name in checks:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)

    if missing:
        root = tk.Tk()
        root.withdraw()
        msg = "以下依赖未安装，程序无法启动：\n\n"
        for pkg in missing:
            msg += f"  ● {pkg}\n"
        msg += f"\n请在命令行运行以下命令安装：\n\npip install {' '.join(missing)}"
        messagebox.showerror("依赖缺失", msg)
        root.destroy()
        sys.exit(1)

    # Interception 驱动检查（非阻塞，仅警告）
    import ctypes as _ct
    _h = _ct.windll.kernel32.CreateFileA(
        br'\\.\interception00', 0x80000000, 0, 0, 3, 0, 0)
    if _h == -1 or _h == 0xFFFFFFFF:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Interception 驱动未安装",
            "Interception 驱动未安装或未生效（需重启电脑）。\n\n"
            "当前将回退到 SendInput（带注入标志，可被检测）。\n\n"
            "安装方法：\n"
            "1. 运行 install-interception.exe /install\n"
            "2. 重启电脑")
        root.destroy()
    else:
        _ct.windll.kernel32.CloseHandle(_h)


_check_dependencies()

# ====================================================
# 自动提权为管理员（解决 UIPI 阻止 SendInput）
# ====================================================

def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


_FROZEN = getattr(sys, 'frozen', False)


def _elevate():
    """如果不是管理员就用 UAC 重新启动自己"""
    if _is_admin():
        return
    if _FROZEN:
        # PyInstaller exe: 直接以管理员重启自身
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv[1:]) if sys.argv[1:] else ""
        work_dir = os.path.dirname(exe)
    else:
        # 脚本模式: 用 pythonw 启动避免控制台
        d = os.path.dirname(sys.executable)
        pw = os.path.join(d, "pythonw.exe")
        exe = pw if os.path.isfile(pw) else sys.executable
        script = os.path.abspath(sys.argv[0])
        work_dir = os.path.dirname(script)
        params = f'"{script}"'
        if sys.argv[1:]:
            params += " " + " ".join(f'"{a}"' for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", exe, params, work_dir, 1)
    sys.exit(0)


_elevate()

# pythonw 下 stdout/stderr 为 None，重定向到 devnull 避免 print 报错
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# 防止 Windows 缩放导致坐标偏移
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ====================================================
# 可选后端：Interception 驱动（输入）
# ====================================================

import interception as _icp

_USE_INTERCEPTION = False

# ====================================================
# 日志
# ====================================================

if _FROZEN:
    RUNTIME_DIR = os.path.dirname(sys.executable)
else:
    RUNTIME_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(RUNTIME_DIR, ".log")
os.makedirs(_LOG_DIR, exist_ok=True)

log = logging.getLogger("auto_clicker")
log.setLevel(logging.DEBUG)
_fh = logging.FileHandler(
    os.path.join(_LOG_DIR, "auto_clicker.log"), encoding="utf-8")
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
log.addHandler(_fh)

log.info("=" * 40)
log.info("脚本启动，管理员权限=%s", _is_admin())
log.info("依赖检查通过，后端就绪: interception")

# ---------- 配置 ----------
MIN_INTERVAL = 1.1   # 最小点击间隔（秒）
MAX_INTERVAL = 1.5   # 最大点击间隔（秒）
MOUSE_MOVE_STEPS = 15  # 鼠标移动插值步数（越大越平滑）
# ---------------------------


def _init_interception():
    """延迟初始化 Interception 驱动（在用户首次操作鼠标后调用）"""
    global _USE_INTERCEPTION
    if _USE_INTERCEPTION:
        return True
    try:
        _icp.auto_capture_devices(keyboard=False, mouse=True)
        _USE_INTERCEPTION = True
        log.info("Interception 驱动初始化成功 — 输入无 INJECTED 标志")
        print("[后端] Interception 驱动已激活")
    except Exception as e:
        log.warning("Interception 初始化失败: %s，回退到 SendInput", e)
        print(f"[后端] Interception 不可用，使用 SendInput")
    return _USE_INTERCEPTION


def _random_title():
    """生成无特征窗口标题"""
    words = ["Settings", "Preferences", "System", "Service",
             "Monitor", "Viewer", "Update", "Config"]
    return random.choice(words) + " " + "".join(random.choices(string.digits, k=4))


_WINDOW_TITLE = _random_title()


# ====================================================
# 用 Win32 API (SendInput) 直接发送输入事件
# ====================================================

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

VK_F6 = 0x75
VK_F7 = 0x76
VK_ESCAPE = 0x1B


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_u",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_u", _U),
    ]


_user32 = ctypes.windll.user32
_SendInput = _user32.SendInput
_SetCursorPos = _user32.SetCursorPos
_GetCursorPos = _user32.GetCursorPos

_GetAsyncKeyState = _user32.GetAsyncKeyState
_GetAsyncKeyState.restype = ctypes.c_short
_GetAsyncKeyState.argtypes = [ctypes.c_int]

_screen_w = _user32.GetSystemMetrics(0)
_screen_h = _user32.GetSystemMetrics(1)


_GetMessageExtraInfo = _user32.GetMessageExtraInfo
_GetMessageExtraInfo.restype = ctypes.wintypes.LPARAM


def _make_mouse_input(dx, dy, flags):
    mi = MOUSEINPUT()
    mi.dx = dx
    mi.dy = dy
    mi.dwFlags = flags
    mi.mouseData = 0
    mi.time = 0
    mi.dwExtraInfo = ctypes.cast(
        _GetMessageExtraInfo(), ctypes.POINTER(ctypes.c_ulong))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = mi
    return inp


def _to_abs(x, y):
    """屏幕像素坐标 -> SendInput 绝对坐标 (0~65535)"""
    ax = int(x * 65536 / _screen_w)
    ay = int(y * 65536 / _screen_h)
    return ax, ay


def win32_move(x, y):
    if _USE_INTERCEPTION:
        _icp.move_to(x, y)
        return
    ax, ay = _to_abs(x, y)
    inp = _make_mouse_input(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def win32_click(x, y):
    if _USE_INTERCEPTION:
        _icp.move_to(x, y)
        time.sleep(random.uniform(0.01, 0.03))
        _icp.mouse_down('left')
        time.sleep(random.uniform(0.05, 0.12))
        _icp.mouse_up('left')
        return
    # 先移动到目标位置
    win32_move(x, y)
    time.sleep(random.uniform(0.01, 0.03))
    # 再单独发送按下/松开（不捆绑 MOVE|ABSOLUTE 标志）
    down = _make_mouse_input(0, 0, MOUSEEVENTF_LEFTDOWN)
    up = _make_mouse_input(0, 0, MOUSEEVENTF_LEFTUP)
    _SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
    time.sleep(random.uniform(0.05, 0.12))
    _SendInput(1, ctypes.byref(up), ctypes.sizeof(up))


# ====================================================
# 仿人类鼠标移动：贝塞尔曲线 + 随机抖动
# ====================================================

def _bezier_point(t, p0, p1, p2, p3):
    """三阶贝塞尔插值"""
    u = 1 - t
    return (u**3 * p0 + 3 * u**2 * t * p1
            + 3 * u * t**2 * p2 + t**3 * p3)


def human_move(x1, y1, x2, y2):
    """
    从 (x1,y1) 沿贝塞尔曲线移动到 (x2,y2)，
    带轻微抖动和不均匀速度，模拟真实手部运动。
    """
    dist = math.hypot(x2 - x1, y2 - y1)
    spread = max(30, dist * 0.3)
    cx1 = x1 + random.uniform(-spread, spread) * 0.5
    cy1 = y1 + random.uniform(-spread, spread) * 0.5
    cx2 = x2 + random.uniform(-spread, spread) * 0.3
    cy2 = y2 + random.uniform(-spread, spread) * 0.3

    steps = max(MOUSE_MOVE_STEPS, int(dist / 15))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)  # smoothstep

        bx = _bezier_point(t, x1, cx1, cx2, x2)
        by = _bezier_point(t, y1, cy1, cy2, y2)

        jitter = max(0, (1 - t) * 2.5)
        bx += random.gauss(0, jitter)
        by += random.gauss(0, jitter)

        win32_move(int(bx), int(by))
        time.sleep(random.uniform(0.004, 0.012))


def get_cursor_pos():
    pt = ctypes.wintypes.POINT()
    _GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ====================================================
# 点击目标偏向区域中心（高斯分布）
# ====================================================

def random_point_in_region(x1, y1, x2, y2):
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    sx, sy = (x2 - x1) / 4, (y2 - y1) / 4
    for _ in range(20):
        px = random.gauss(cx, sx)
        py = random.gauss(cy, sy)
        if x1 <= px <= x2 and y1 <= py <= y2:
            return int(px), int(py)
    return random.randint(x1, x2), random.randint(y1, y2)


# ====================================================
# 间隔时间模拟
# ====================================================

def human_delay():
    r = random.random()
    if r < 0.05:
        return random.uniform(MAX_INTERVAL, MAX_INTERVAL + 0.8)
    elif r < 0.10:
        return random.uniform(0.3, 0.6)
    else:
        return random.uniform(MIN_INTERVAL, MAX_INTERVAL)


# ====================================================
# GUI 框选
# ====================================================

class RegionSelector:
    """全屏半透明覆盖层，用于框选区域"""

    def __init__(self, parent, on_selected):
        self.on_selected = on_selected
        self.start_x = self.start_y = 0
        self.rect_id = None

        self.root = tk.Toplevel(parent)
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(bg="gray")
        self.root.title(_WINDOW_TITLE)

        self.canvas = tk.Canvas(self.root, cursor="cross", bg="gray",
                                highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.label = self.canvas.create_text(
            self.root.winfo_screenwidth() // 2, 60,
            text="拖拽鼠标框选点击区域  |  Esc 退出",
            font=("Microsoft YaHei", 20, "bold"), fill="white")

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def run(self):
        self.root.grab_set()
        self.root.wait_window()

    def _on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="red", width=2)

    def _on_drag(self, event):
        self.canvas.coords(self.rect_id,
                           self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event):
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        if x2 - x1 > 10 and y2 - y1 > 10:
            self.root.destroy()
            self.on_selected(x1, y1, x2, y2)


# ====================================================
# 核心点击逻辑
# ====================================================

class Clicker:
    def __init__(self):
        self.region = None
        self.running = False
        self.paused = False
        self.thread = None

    def set_region(self, x1, y1, x2, y2):
        self.region = (x1, y1, x2, y2)
        print(f"[区域] ({x1}, {y1}) -> ({x2}, {y2})  "
              f"大小 {x2 - x1}x{y2 - y1}")
        log.info("设置区域: (%d,%d)->(%d,%d) 大小 %dx%d",
                 x1, y1, x2, y2, x2 - x1, y2 - y1)

    def start(self):
        if self.region is None:
            return
        self.running = True
        self.paused = False
        _init_interception()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[开始] 自动点击已启动  |  F6 暂停/恢复  F7 重选  Esc 退出")
        log.info("自动点击已启动, 区域=%s, interception=%s",
                 self.region, _USE_INTERCEPTION)

    def stop(self):
        self.running = False
        log.info("自动点击已停止")

    def toggle_pause(self):
        self.paused = not self.paused
        state = "暂停" if self.paused else "恢复"
        print(f"[{state}]")
        log.info("切换暂停状态: %s", state)

    def _loop(self):
        x1, y1, x2, y2 = self.region
        log.debug("点击循环开始, 区域=(%d,%d,%d,%d)", x1, y1, x2, y2)
        cycle = 0
        while self.running:
            if not self.paused:
                cycle += 1

                # 模拟玩家偶尔分心（~2%）
                if cycle > 5 and random.random() < 0.02:
                    afk = random.uniform(10, 40)
                    log.info("模拟分心，暂停 %.1f 秒", afk)
                    end = time.time() + afk
                    while time.time() < end and self.running:
                        time.sleep(0.05)
                    continue

                tx, ty = random_point_in_region(x1, y1, x2, y2)
                cx, cy = get_cursor_pos()
                human_move(cx, cy, tx, ty)
                time.sleep(random.uniform(0.02, 0.08))
                win32_click(tx, ty)
                log.debug("点击 (%d, %d)", tx, ty)

            delay = human_delay()
            end = time.time() + delay
            while time.time() < end and self.running:
                time.sleep(0.05)
        log.debug("点击循环结束")


# ====================================================
# 按键轮询（替代低级键盘钩子，无系统钩子注册，不可被检测）
# ====================================================

_hotkey_callbacks = {}
_hotkey_running = False


def register_hotkey(vk_code, callback):
    _hotkey_callbacks[vk_code] = callback


def _poll_keys():
    """后台轮询线程：通过 GetAsyncKeyState 检测按键状态"""
    prev_state = {}
    while _hotkey_running:
        for vk, cb in list(_hotkey_callbacks.items()):
            pressed = bool(_GetAsyncKeyState(vk) & 0x8000)
            if pressed and not prev_state.get(vk, False):
                threading.Thread(target=cb, daemon=True).start()
            prev_state[vk] = pressed
        time.sleep(0.015)  # ~66Hz 轮询频率


def start_hotkey_polling():
    global _hotkey_running
    _hotkey_running = True
    t = threading.Thread(target=_poll_keys, daemon=True)
    t.start()
    log.info("按键轮询已启动")


# ====================================================
# 控制面板 UI
# ====================================================


class ControlPanel:
    BG = "#2b2b2b"
    FG = "#e0e0e0"
    ACCENT = "#4a9eff"
    GREEN = "#43b581"
    RED = "#f04747"
    WARN = "#ff4444"
    MUTED = "#888888"
    BTN_BG = "#3c3c3c"
    BTN_ACTIVE = "#505050"

    def __init__(self, root):
        self.root = root
        self.clicker = None
        self.region = None
        self.state = "idle"       # idle | running | paused | selecting

        root.title(_WINDOW_TITLE)
        root.geometry("320x390")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.configure(bg=self.BG)
        root.protocol("WM_DELETE_WINDOW", self.on_quit)

        pad = dict(padx=14, pady=4, sticky="ew")
        btn_cfg = dict(
            font=("Microsoft YaHei", 11), relief="flat", cursor="hand2",
            bg=self.BTN_BG, fg=self.FG, activebackground=self.BTN_ACTIVE,
            activeforeground=self.FG, bd=0, height=1)

        # ---- 标题 ----
        tk.Label(
            root, text="Auto Clicker",
            font=("Microsoft YaHei", 14, "bold"),
            bg=self.BG, fg=self.ACCENT
        ).grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")

        # ---- TIPS 区域 (红色醒目) ----
        tips_frame = tk.Frame(root, bg=self.BG)
        tips_frame.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")
        for line in [
            "TIPS: 请使用游戏分辨率 1176 x 664",
            "企鹅: 275899142",
            "非商业售卖，仅供学习娱乐",
            "最终解释权归开发者 Larito 所有",
        ]:
            tk.Label(tips_frame, text=line,
                     font=("Microsoft YaHei", 8, "bold"),
                     bg=self.BG, fg=self.WARN, anchor="w"
                     ).pack(fill="x")

        # ---- 选择区域 ----
        self.btn_select = tk.Button(
            root, text="选择区域  [F7]", command=self.on_select_region,
            **btn_cfg)
        self.btn_select.grid(row=2, column=0, **pad)

        self.lbl_region = tk.Label(
            root, text="未选择区域", font=("Microsoft YaHei", 9),
            bg=self.BG, fg=self.MUTED)
        self.lbl_region.grid(row=3, column=0, padx=14, pady=0, sticky="w")

        # ---- 开始 / 停止 ----
        self.btn_start = tk.Button(
            root, text="开始", command=self.on_start_stop,
            state=tk.DISABLED, **btn_cfg)
        self.btn_start.grid(row=4, column=0, **pad)

        # ---- 暂停 / 恢复 ----
        self.btn_pause = tk.Button(
            root, text="暂停  [F6]", command=self.on_pause_resume,
            state=tk.DISABLED, **btn_cfg)
        self.btn_pause.grid(row=5, column=0, **pad)

        # ---- 状态标签 ----
        self.lbl_status = tk.Label(
            root, text="-- 空闲 --",
            font=("Microsoft YaHei", 10, "bold"),
            bg=self.BG, fg=self.MUTED)
        self.lbl_status.grid(row=6, column=0, padx=14, pady=8, sticky="ew")

        # ---- 退出 ----
        self.btn_quit = tk.Button(
            root, text="退出  [Esc]", command=self.on_quit,
            font=("Microsoft YaHei", 10), relief="flat", cursor="hand2",
            bg=self.BTN_BG, fg=self.RED, activebackground=self.BTN_ACTIVE,
            activeforeground=self.RED, bd=0)
        self.btn_quit.grid(row=7, column=0, **pad)

        root.columnconfigure(0, weight=1)

        # 定时刷新状态
        self._update_status()

    # ---------- 选择区域 ----------

    def on_select_region(self):
        if self.state == "selecting":
            return
        log.info("[UI] 开始框选区域")
        # 停止当前运行
        if self.clicker:
            self.clicker.stop()
            self.clicker = None

        self.state = "selecting"
        self.root.withdraw()

        def on_selected(x1, y1, x2, y2):
            self.region = (x1, y1, x2, y2)
            print(f"[区域] ({x1}, {y1}) -> ({x2}, {y2})  "
                  f"大小 {x2 - x1}x{y2 - y1}")
            log.info("[UI] 区域选定: (%d,%d)->(%d,%d) %dx%d",
                     x1, y1, x2, y2, x2 - x1, y2 - y1)

        selector = RegionSelector(self.root, on_selected)
        selector.run()

        self.root.deiconify()
        if self.region is None:
            log.info("[UI] 框选取消（未选择区域）")
        self.state = "idle"
        self._refresh_buttons()

    # ---------- 开始 / 停止 ----------

    def on_start_stop(self):
        if self.state in ("running", "paused"):
            # 停止
            log.info("[UI] 停止点击")
            if self.clicker:
                self.clicker.stop()
                self.clicker = None
            self.state = "idle"
        elif self.state == "idle" and self.region:
            # 开始
            log.info("[UI] 开始点击, 区域=%s", self.region)
            self.clicker = Clicker()
            self.clicker.set_region(*self.region)
            self.clicker.start()
            self.state = "running"
        self._refresh_buttons()

    # ---------- 暂停 / 恢复 ----------

    def on_pause_resume(self):
        if self.state == "running" and self.clicker:
            self.clicker.toggle_pause()
            self.state = "paused"
            log.info("[UI] 已暂停")
        elif self.state == "paused" and self.clicker:
            self.clicker.toggle_pause()
            self.state = "running"
            log.info("[UI] 已恢复")
        self._refresh_buttons()

    # ---------- 退出 ----------

    def on_quit(self):
        log.info("[UI] 退出程序")
        if self.clicker:
            self.clicker.stop()
        os._exit(0)

    # ---------- UI 刷新 ----------

    def _refresh_buttons(self):
        has_region = self.region is not None

        # 区域标签
        if has_region:
            x1, y1, x2, y2 = self.region
            self.lbl_region.config(
                text=f"区域: ({x1},{y1})->({x2},{y2})  {x2-x1}x{y2-y1}",
                fg=self.FG)
        else:
            self.lbl_region.config(text="未选择区域", fg=self.MUTED)

        # 开始/停止按钮
        if self.state in ("running", "paused"):
            self.btn_start.config(text="停止", state=tk.NORMAL,
                                  bg="#5c3c3c", fg=self.RED)
        else:
            self.btn_start.config(text="开始", bg=self.BTN_BG, fg=self.FG,
                                  state=tk.NORMAL if has_region else tk.DISABLED)

        # 暂停/恢复按钮
        if self.state == "running":
            self.btn_pause.config(text="暂停  [F6]", state=tk.NORMAL)
        elif self.state == "paused":
            self.btn_pause.config(text="恢复  [F6]", state=tk.NORMAL)
        else:
            self.btn_pause.config(text="暂停  [F6]", state=tk.DISABLED)

        # 选区按钮
        self.btn_select.config(
            state=tk.DISABLED if self.state == "selecting" else tk.NORMAL)

        # 状态文本 + 颜色
        status_map = {
            "idle":      ("-- 空闲 --",   self.MUTED),
            "selecting": ("-- 框选中 --", self.ACCENT),
            "running":   ("-- 运行中 --", self.GREEN),
            "paused":    ("-- 已暂停 --", "#faa61a"),
        }
        text, color = status_map.get(self.state, ("", self.MUTED))
        self.lbl_status.config(text=text, fg=color)

    def _update_status(self):
        # 检测引擎是否已自行停止
        if self.clicker and not self.clicker.running and self.state in ("running", "paused"):
            self.state = "idle"
            self.clicker = None
            self._refresh_buttons()
        self.root.after(500, self._update_status)


# ====================================================
# 主入口
# ====================================================


def main():
    root = tk.Tk()
    panel = ControlPanel(root)

    # 注册全局热键 —— 通过 root.after 保证线程安全
    register_hotkey(VK_F6, lambda: root.after(0, panel.on_pause_resume))
    register_hotkey(VK_F7, lambda: root.after(0, panel.on_select_region))
    register_hotkey(VK_ESCAPE, lambda: root.after(0, panel.on_quit))
    start_hotkey_polling()

    print("=" * 50)
    print("  自动点击器 (UE5 兼容版)")
    print("  已以管理员权限运行")
    print("=" * 50)

    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("未捕获异常: %s", e)
        traceback.print_exc()
