# -*- coding: utf-8 -*-

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
        ('cv2',           'opencv-python'),
        ('numpy',         'numpy'),
        ('win32api',      'pywin32'),
        ('dxcam',         'dxcam'),
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


_check_dependencies()

import cv2
import numpy as np

# ====================================================
# 管理员提权
# ====================================================

def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


_FROZEN = getattr(sys, 'frozen', False) or "__compiled__" in globals()


def _elevate():
    if _is_admin():
        return
    if _FROZEN:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv[1:]) if sys.argv[1:] else ""
        work_dir = os.path.dirname(exe)
    else:
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

# DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ====================================================
# 可选后端：dxcam（截屏）
# ====================================================

import dxcam as _dxcam_mod

_USE_DXCAM = False
_dxcam_camera = None

# ====================================================
# 日志
# ====================================================

if _FROZEN:
    # Nuitka --onefile: 资源解压到临时目录，通过 __compiled__ 判断
    _meipass = getattr(sys, '_MEIPASS', None)
    if _meipass:
        RESOURCE_DIR = _meipass
    else:
        # Nuitka: 数据文件与 exe 同目录
        RESOURCE_DIR = os.path.dirname(sys.executable)
    RUNTIME_DIR = os.path.dirname(sys.executable)
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
    RUNTIME_DIR = RESOURCE_DIR
_LOG_DIR = os.path.join(RUNTIME_DIR, ".log")
os.makedirs(_LOG_DIR, exist_ok=True)

log = logging.getLogger("app")
log.setLevel(logging.INFO)
_fh = logging.FileHandler(
    os.path.join(_LOG_DIR, "app.log"), encoding="utf-8")
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
log.addHandler(_fh)

log.info("=" * 40)
log.info("启动，admin=%s", _is_admin())

# ====================================================
# 配置
# ====================================================
DETECTION_INTERVAL = (2.0, 4.0)      # 检测间隔范围（秒）
CLICK_OFFSET = 5                      # 点击随机偏移像素
HERO_SELECT_WAIT = (1.5, 2.5)        # 选精灵后等待时间
BUTTON_TPL_THRESHOLD = 0.7           # 按钮模板匹配阈值
BATTLE_TPL_THRESHOLD = 0.55          # "战报" 模板匹配阈值
DEBUG_SAVE = False                   # 调试模式，开启后保存截图到 debug/
MOUSE_MOVE_STEPS = 15                # 鼠标移动插值步数


def _init_dxcam():
    """初始化 DXGI Desktop Duplication 截屏"""
    global _USE_DXCAM, _dxcam_camera
    if _USE_DXCAM:
        return True
    try:
        _dxcam_camera = _dxcam_mod.create()
        _USE_DXCAM = True
        log.info("cap init ok")
    except Exception as e:
        log.warning("cap init fail: %s", e)
    return _USE_DXCAM


def _random_title():
    """生成无特征窗口标题，避免被 EnumWindows 关键词扫描命中"""
    words = ["Settings", "Preferences", "System", "Service",
             "Monitor", "Viewer", "Update", "Config"]
    return random.choice(words) + " " + "".join(random.choices(string.digits, k=4))


_WINDOW_TITLE = _random_title()


# ====================================================
# Win32 常量
# ====================================================

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_KEYUP = 0x0002
SRCCOPY = 0x00CC0020

VK_F6 = 0x75
VK_F7 = 0x76
VK_ESCAPE = 0x1B

# PostMessage 常量（绕过 SendInput 的 INJECTED 标记）
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

# ====================================================
# Win32 结构体
# ====================================================


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
    _anonymous_ = ("_u",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_u", _U),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


# ====================================================
# Win32 函数
# ====================================================

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_kernel32 = ctypes.windll.kernel32

_SendInput = _user32.SendInput
_SetCursorPos = _user32.SetCursorPos
_GetCursorPos = _user32.GetCursorPos

_GetAsyncKeyState = _user32.GetAsyncKeyState
_GetAsyncKeyState.restype = ctypes.c_short
_GetAsyncKeyState.argtypes = [ctypes.c_int]

_PostMessageW = _user32.PostMessageW
_PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint,
                          ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
_PostMessageW.restype = ctypes.wintypes.BOOL

_ScreenToClient = _user32.ScreenToClient

_screen_w = _user32.GetSystemMetrics(0)
_screen_h = _user32.GetSystemMetrics(1)

# ====================================================
# 游戏窗口句柄（PostMessage 目标）
# ====================================================

_game_hwnd = None


def _find_game_hwnd(region):
    """从框选区域中心点查找游戏窗口句柄"""
    global _game_hwnd
    x1, y1, x2, y2 = region
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    # WindowFromPoint 接收 POINT by value，在 x64 上打包为 int64
    packed = ((cy & 0xFFFFFFFF) << 32) | (cx & 0xFFFFFFFF)
    _user32.WindowFromPoint.restype = ctypes.wintypes.HWND
    _user32.WindowFromPoint.argtypes = [ctypes.c_int64]
    hwnd = _user32.WindowFromPoint(packed)
    if hwnd:
        _game_hwnd = hwnd
        log.info("target hwnd=%s", hwnd)
    return hwnd


def _screen_to_client(hwnd, x, y):
    """屏幕坐标 → 窗口客户区坐标"""
    pt = ctypes.wintypes.POINT(x, y)
    _ScreenToClient(hwnd, ctypes.byref(pt))
    return pt.x, pt.y

# ====================================================
# 鼠标输入
# ====================================================


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
    return int(x * 65536 / _screen_w), int(y * 65536 / _screen_h)


def win32_move(x, y):
    """移动鼠标（SetCursorPos 不经过 SendInput，无 INJECTED 标记）"""
    _SetCursorPos(x, y)


def win32_click(x, y):
    """点击：优先 PostMessage（无 INJECTED），回退 SendInput"""
    win32_move(x, y)
    time.sleep(random.uniform(0.01, 0.03))
    if _game_hwnd:
        cx, cy = _screen_to_client(_game_hwnd, x, y)
        lp = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
        _PostMessageW(_game_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(random.uniform(0.05, 0.12))
        _PostMessageW(_game_hwnd, WM_LBUTTONUP, 0, lp)
    else:
        down = _make_mouse_input(0, 0, MOUSEEVENTF_LEFTDOWN)
        up = _make_mouse_input(0, 0, MOUSEEVENTF_LEFTUP)
        _SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
        time.sleep(random.uniform(0.05, 0.12))
        _SendInput(1, ctypes.byref(up), ctypes.sizeof(up))


def get_cursor_pos():
    pt = ctypes.wintypes.POINT()
    _GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ====================================================
# 键盘输入
# ====================================================

_MapVirtualKeyW = _user32.MapVirtualKeyW


KEYEVENTF_SCANCODE = 0x0008


def win32_key_press(vk_code):
    """按键：优先 PostMessage（无 INJECTED），回退 SendInput 扫描码"""
    scan = _MapVirtualKeyW(vk_code, 0)

    if _game_hwnd:
        # lParam: repeat=1, scancode, extended=0, context=0, previous/transition
        lp_down = 1 | (scan << 16)
        lp_up = 1 | (scan << 16) | (1 << 30) | (1 << 31)
        _PostMessageW(_game_hwnd, WM_KEYDOWN, vk_code, lp_down)
        time.sleep(random.uniform(0.04, 0.10))
        _PostMessageW(_game_hwnd, WM_KEYUP, vk_code, lp_up)
    else:
        extra = ctypes.cast(
            _GetMessageExtraInfo(), ctypes.POINTER(ctypes.c_ulong))
        down = INPUT()
        down.type = INPUT_KEYBOARD
        down.ki = KEYBDINPUT()
        down.ki.wVk = 0
        down.ki.wScan = scan
        down.ki.dwFlags = KEYEVENTF_SCANCODE
        down.ki.time = 0
        down.ki.dwExtraInfo = extra
        up = INPUT()
        up.type = INPUT_KEYBOARD
        up.ki = KEYBDINPUT()
        up.ki.wVk = 0
        up.ki.wScan = scan
        up.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
        up.ki.time = 0
        up.ki.dwExtraInfo = extra
        _SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
        time.sleep(random.uniform(0.04, 0.10))
        _SendInput(1, ctypes.byref(up), ctypes.sizeof(up))


# ====================================================
# 人性化鼠标移动
# ====================================================


def _bezier_point(t, p0, p1, p2, p3):
    u = 1 - t
    return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3


def human_move(x1, y1, x2, y2):
    """贝塞尔曲线 + 抖动 + 不均匀速度"""
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 3:
        win32_move(x2, y2)
        return

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


def human_click(x, y, offset=CLICK_OFFSET):
    """人性化点击：移动 → 犹豫 → 微调 → 点击"""
    cx, cy = get_cursor_pos()

    # 先移到目标附近（带偏移）
    near_x = x + random.randint(-offset * 2, offset * 2)
    near_y = y + random.randint(-offset * 2, offset * 2)
    human_move(cx, cy, near_x, near_y)

    # 短暂犹豫
    time.sleep(random.uniform(0.08, 0.25))

    # 微调到精确位置（加小偏移模拟手抖）
    final_x = x + random.gauss(0, offset * 0.6)
    final_y = y + random.gauss(0, offset * 0.6)
    human_move(near_x, near_y, int(final_x), int(final_y))

    time.sleep(random.uniform(0.02, 0.08))
    win32_click(int(final_x), int(final_y))


# ====================================================
# GDI 截屏
# ====================================================


_dxcam_fail_count = 0          # 连续 dxcam 超时/失败计数
_DXCAM_MAX_FAILS = 3           # 连续失败 N 次后自动禁用 dxcam


def _capture_gdi(x1, y1, w, h):
    """GDI BitBlt 截屏（通用，不易被针对性拦截）"""
    hdc_src = _user32.GetDC(0)
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_src)
    hbmp = _gdi32.CreateCompatibleBitmap(hdc_src, w, h)
    old = _gdi32.SelectObject(hdc_mem, hbmp)

    _gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_src, x1, y1, SRCCOPY)

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    _gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

    _gdi32.SelectObject(hdc_mem, old)
    _gdi32.DeleteObject(hbmp)
    _gdi32.DeleteDC(hdc_mem)
    _user32.ReleaseDC(0, hdc_src)

    img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
    return img[:, :, :3].copy()


def _capture_dxcam(x1, y1, x2, y2):
    """DXGI Desktop Duplication 截屏（备选）"""
    result = [None]

    def _grab():
        try:
            for _ in range(3):
                f = _dxcam_camera.grab(region=(x1, y1, x2, y2))
                if f is not None:
                    result[0] = f
                    return
                time.sleep(0.02)
        except Exception:
            pass

    t = threading.Thread(target=_grab, daemon=True)
    t.start()
    t.join(timeout=2)

    if result[0] is not None:
        return cv2.cvtColor(result[0], cv2.COLOR_RGB2BGR)
    return None


def capture_region(x1, y1, x2, y2):
    """截取屏幕局部区域，返回 BGR numpy 数组。
    默认 GDI（常见合法调用，不易触发检测），随机穿插 DXGI 避免单一 API 特征。"""
    global _USE_DXCAM, _dxcam_fail_count
    w = x2 - x1
    h = y2 - y1
    if w <= 0 or h <= 0:
        return None

    # 20% 概率使用 DXGI（如果可用），降低 DXGI 接口的持续调用特征
    use_dx = _USE_DXCAM and _dxcam_camera is not None and random.random() < 0.20
    if use_dx:
        frame = _capture_dxcam(x1, y1, x2, y2)
        if frame is not None:
            _dxcam_fail_count = 0
            return frame
        _dxcam_fail_count += 1
        if _dxcam_fail_count >= _DXCAM_MAX_FAILS:
            log.warning("cap fallback after %d fails", _dxcam_fail_count)
            _USE_DXCAM = False

    return _capture_gdi(x1, y1, w, h)


# ====================================================
# 模板匹配
# ====================================================


def multi_scale_match(screen_gray, tpl_gray, threshold=0.7,
                      scale_range=(0.4, 2.5), num_scales=20):
    """多尺度模板匹配，返回 (loc, scale, confidence) 或 None"""
    th, tw = tpl_gray.shape[:2]
    sh, sw = screen_gray.shape[:2]
    best_val, best_loc, best_scale = 0, None, 1.0

    for scale in np.linspace(scale_range[0], scale_range[1], num_scales):
        nw, nh = int(tw * scale), int(th * scale)
        if nw > sw or nh > sh or nw < 8 or nh < 8:
            continue
        resized = cv2.resize(tpl_gray, (nw, nh))
        result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_val:
            best_val = max_val
            best_loc = max_loc
            best_scale = scale

    if best_val >= threshold:
        return best_loc, best_scale, best_val
    return None



# ====================================================
# 兼容中文路径的图片读写
# ====================================================


def _imread_unicode(path, flags=cv2.IMREAD_COLOR):
    """cv2.imread 不支持中文路径，改用 np.fromfile + imdecode"""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def _imwrite_unicode(path, img):
    """cv2.imwrite 不支持中文路径，改用 imencode + tofile"""
    ext = os.path.splitext(path)[1]
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)


# ====================================================
# 界面检测
# ====================================================


class PageDetector:
    """
    界面检测逻辑：
      1. 匹配 Button.jpg（左下区域）→ buttonPage
      2. 未匹配 Button.jpg，但右侧匹配战报图标 → selectHeroPage
      3. 都不匹配 → normal
    """

    def __init__(self):
        # ---- 加载 Button.jpg（buttonPage 检测） ----
        btn_path = os.path.join(RESOURCE_DIR, "Button.jpg")
        btn_img = _imread_unicode(btn_path)
        if btn_img is None:
            log.error("找不到模板文件: %s", btn_path)
            raise FileNotFoundError(f"找不到模板: {btn_path}")
        self.button_gray = cv2.cvtColor(btn_img, cv2.COLOR_BGR2GRAY)

        # ---- 加载 BattleReport.png（战报图标，selectHero 检测） ----
        battle_path = os.path.join(RESOURCE_DIR, "BattleReport.png")
        battle_img = _imread_unicode(battle_path)
        if battle_img is None:
            log.error("找不到模板文件: %s", battle_path)
            raise FileNotFoundError(f"找不到模板: {battle_path}")
        self.battle_tpl_gray = cv2.cvtColor(battle_img, cv2.COLOR_BGR2GRAY)

        print(f"[模板] Button:   {self.button_gray.shape}")
        print(f"[模板] 战报:     {self.battle_tpl_gray.shape}")
        log.info("模板加载完成: Button=%s, 战报=%s",
                 self.button_gray.shape, self.battle_tpl_gray.shape)

        self._debug_counter = 0
        if DEBUG_SAVE:
            self._debug_dir = os.path.join(RUNTIME_DIR, "debug")
            os.makedirs(self._debug_dir, exist_ok=True)

    def detect(self, region):
        x1, y1, x2, y2 = region
        screen = capture_region(x1, y1, x2, y2)
        if screen is None:
            return "normal", None

        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # ---- 1. 左下角有星星按钮 → buttonPage ----
        cut_y = h * 2 // 3
        cut_x = w // 2
        bottom_left = gray[cut_y:, :cut_x]
        match_btn = multi_scale_match(bottom_left, self.button_gray,
                                      threshold=BUTTON_TPL_THRESHOLD)
        if match_btn:
            loc, scale, conf = match_btn
            bh, bw = self.button_gray.shape[:2]
            sx = x1 + loc[0] + int(bw * scale / 2)
            sy = y1 + cut_y + loc[1] + int(bh * scale / 2)
            print(f"[buttonPage] 星星按钮 置信度={conf:.2f}")
            log.info("检测到 buttonPage: 星星按钮位置=(%d,%d) 置信度=%.2f scale=%.2f",
                     sx, sy, conf, scale)
            return "button_page", {"click": (sx, sy), "conf": conf}

        # ---- 2. 右侧有战报图标且左下无星星 → selectHeroPage ----
        right_area = gray[int(h * 0.6):, int(w * 0.7):]
        match_battle = multi_scale_match(right_area, self.battle_tpl_gray,
                                         threshold=BATTLE_TPL_THRESHOLD)
        if match_battle:
            _, _, conf2 = match_battle
            print(f"[selectHero] 战报匹配 置信度={conf2:.2f}")
            log.info("检测到 selectHero: 战报匹配置信度=%.2f", conf2)
            return "select_hero", {}

        # ---- 3. 其余情况 → 不做任何操作 ----
        # 诊断：输出战报最佳匹配值（即使低于阈值）
        diag = multi_scale_match(right_area, self.battle_tpl_gray, threshold=0.0)
        best_conf = diag[2] if diag else 0
        log.debug("检测结果: normal（无匹配）| 战报最佳置信度=%.3f 阈值=%.2f",
                  best_conf, BATTLE_TPL_THRESHOLD)

        # 每 10 次保存一帧供诊断
        if DEBUG_SAVE:
            self._debug_counter += 1
            if self._debug_counter % 10 == 1:
                _imwrite_unicode(
                    os.path.join(self._debug_dir, "screen_latest.png"), screen)
                _imwrite_unicode(
                    os.path.join(self._debug_dir, "right_area_latest.png"),
                    right_area)

        return "normal", None


# ====================================================
# 核心循环
# ====================================================


class AutoBattle:
    def __init__(self, region, detector):
        self.region = region          # (x1, y1, x2, y2)
        self.detector = detector
        self.running = True
        self.paused = False
        self._thread = None
        # ---- 行为仿真参数 ----
        self._start_time = time.time()
        # 会话节奏：每次启动随机决定是"快手"还是"慢手"玩家
        self._tempo = random.uniform(0.75, 1.35)
        # 下次定时休息的周期（分钟）
        self._next_break_min = random.uniform(12, 35)

    def _fatigue_factor(self):
        """疲劳系数：随时间推移反应变慢（1.0 → 1.3，约 2 小时封顶）"""
        elapsed = time.time() - self._start_time
        return 1.0 + 0.3 * min(1.0, elapsed / 7200)

    def _adjusted_delay(self, base_delay):
        """综合节奏 + 疲劳后的实际延迟"""
        return base_delay * self._tempo * self._fatigue_factor()

    def start(self):
        self.running = True
        self.paused = False
        _find_game_hwnd(self.region)
        _init_dxcam()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[启动] 运行中  |  F6 暂停/恢复  F7 重选  Esc 退出")
        log.info("已启动, 区域=%s, dxcam=%s, hwnd=%s",
                 self.region, _USE_DXCAM, _game_hwnd)

    def stop(self):
        self.running = False
        log.info("stopped")

    def toggle_pause(self):
        self.paused = not self.paused
        state = '暂停' if self.paused else '恢复'
        print(f"[{state}]")
        log.info("切换暂停状态: %s", state)

    def _loop(self):
        cycle = 0
        while self.running:
            if self.paused:
                time.sleep(0.5)
                continue

            cycle += 1

            # ---- 定时休息（模拟玩家去上厕所/喝水） ----
            elapsed_min = (time.time() - self._start_time) / 60
            if elapsed_min >= self._next_break_min:
                rest = random.uniform(30, 120)
                log.info("scheduled break %.0fs", rest)
                self._interruptible_sleep(rest)
                self._next_break_min = elapsed_min + random.uniform(12, 35)
                continue

            # ---- 随机分心（概率随疲劳递增） ----
            afk_prob = 0.015 * self._fatigue_factor()
            if cycle > 5 and random.random() < afk_prob:
                afk = random.uniform(10, 45)
                log.info("afk %.1fs", afk)
                self._interruptible_sleep(afk)
                continue

            # 带超时检测
            detect_result = [None]

            def _detect_main():
                try:
                    detect_result[0] = self.detector.detect(self.region)
                except Exception as e:
                    log.exception("detect err: %s", e)

            dt = threading.Thread(target=_detect_main, daemon=True)
            dt.start()
            dt.join(timeout=8)

            if detect_result[0] is None:
                log.warning("detect timeout")
                continue

            page, info = detect_result[0]

            # 犹豫概率随疲劳递增（2%-5%）
            hesitate_prob = 0.02 * self._fatigue_factor()
            if page != "normal" and random.random() < hesitate_prob:
                self._interruptible_sleep(
                    self._adjusted_delay(random.uniform(0.8, 2.0)))
                continue

            if page == "button_page":
                self._do_click_button(info)
            elif page == "select_hero":
                self._do_select_hero(info)
            else:
                self._do_idle()

            # 混合分布检测间隔 × 节奏 × 疲劳
            r = random.random()
            if r < 0.05:
                delay = random.uniform(5.0, 10.0)
            elif r < 0.15:
                delay = random.uniform(1.0, 1.5)
            else:
                delay = random.uniform(*DETECTION_INTERVAL)
            self._interruptible_sleep(self._adjusted_delay(delay))

    def _do_click_button(self, info):
        sx, sy = info["click"]
        conf = info["conf"]
        print(f"[buttonPage] ({sx}, {sy})  conf={conf:.2f}")
        log.info("btn (%d,%d) c=%.2f", sx, sy, conf)

        # ~5% 概率微失误：先点偏，再修正（模拟手滑）
        if random.random() < 0.05:
            miss_x = sx + random.randint(-25, 25)
            miss_y = sy + random.randint(-25, 25)
            human_click(miss_x, miss_y)
            time.sleep(random.uniform(0.3, 0.8))

        human_click(sx, sy)

    def _do_select_hero(self, info):
        """依次按 1+空格、2+空格 ... 6+空格 选择精灵"""
        # 数字键 1-6 的虚拟键码 = 0x31-0x36，空格 = 0x20
        VK_SPACE = 0x20

        for num in range(1, 7):
            if not self.running:
                return

            vk_num = 0x30 + num     # 0x31='1', 0x32='2', ...
            print(f"[selectHero] 按键: {num} + 空格")
            log.info("选精灵: 按键 %d + 空格", num)

            win32_key_press(vk_num)
            time.sleep(random.uniform(0.15, 0.35))
            win32_key_press(VK_SPACE)
            log.debug("选精灵: 按键 %d 已发送，等待界面响应", num)

            # 等待界面响应
            self._interruptible_sleep(random.uniform(*HERO_SELECT_WAIT))
            if not self.running:
                return

            # 带超时检测是否已离开选英雄页面
            page2 = self._detect_with_timeout()
            log.debug("选精灵: 按键 %d 后检测结果=%s", num, page2)

            if page2 is not None and page2 != "select_hero":
                print(f"[selectHero] → 已离开选英雄界面 ({page2})")
                log.info("选精灵完成: 按键 %d 后离开选英雄界面 (%s)", num, page2)
                return
            elif page2 is None:
                log.warning("选精灵: 按键 %d 后检测超时，继续尝试下一个", num)

        print("[selectHero] 1-6 全部尝试完毕")
        log.info("选精灵: 1-6 全部尝试完毕")

    def _detect_with_timeout(self, timeout=5):
        """带超时的 detect()，防止截屏阻塞卡死整个循环。超时返回 None。"""
        result = [None]

        def _run():
            try:
                result[0] = self.detector.detect(self.region)
            except Exception:
                pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if result[0] is not None:
            return result[0][0]     # 返回 page 名称
        return None

    def _do_idle(self):
        if random.random() < 0.15:
            cx, cy = get_cursor_pos()
            dx = random.randint(-30, 30)
            dy = random.randint(-30, 30)
            human_move(cx, cy, cx + dx, cy + dy)

    def _interruptible_sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end and self.running:
            time.sleep(0.05)


# ====================================================
# GUI 框选区域
# ====================================================


class RegionSelector:
    """全屏半透明覆盖层，用于框选游戏区域"""

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
            text="拖拽鼠标框选游戏窗口区域  |  Esc 退出",
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
        if x2 - x1 > 30 and y2 - y1 > 30:
            self.root.destroy()
            self.on_selected(x1, y1, x2, y2)


# ====================================================
# 按键轮询（替代低级键盘钩子，无系统钩子注册，不可被检测）
# ====================================================

_hotkey_callbacks = {}
_hotkey_running = False


def register_hotkey(vk_code, callback):
    _hotkey_callbacks[vk_code] = callback


def _poll_keys():
    """后台轮询线程：通过 GetAsyncKeyState 检测按键状态（随机间隔避免固定频率特征）"""
    prev_state = {}
    while _hotkey_running:
        for vk, cb in list(_hotkey_callbacks.items()):
            pressed = bool(_GetAsyncKeyState(vk) & 0x8000)
            if pressed and not prev_state.get(vk, False):
                threading.Thread(target=cb, daemon=True).start()
            prev_state[vk] = pressed
        time.sleep(random.uniform(0.010, 0.035))


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

    def __init__(self, root, detector):
        self.root = root
        self.detector = detector
        self.battle = None
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
            root, text=_WINDOW_TITLE,
            font=("Microsoft YaHei", 14, "bold"),
            bg=self.BG, fg=self.ACCENT
        ).grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")

        # ---- TIPS 区域 ----
        tips_frame = tk.Frame(root, bg=self.BG)
        tips_frame.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")
        for line in [
            "Resolution: 1176 x 664",
            "QQ: 275899142",
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
        if self.battle:
            self.battle.stop()
            self.battle = None

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
            log.info("[UI] 停止战斗")
            if self.battle:
                self.battle.stop()
                self.battle = None
            self.state = "idle"
        elif self.state == "idle" and self.region:
            # 开始
            log.info("[UI] 开始战斗, 区域=%s", self.region)
            self.battle = AutoBattle(self.region, self.detector)
            self.battle.start()
            self.state = "running"
        self._refresh_buttons()

    # ---------- 暂停 / 恢复 ----------

    def on_pause_resume(self):
        if self.state == "running" and self.battle:
            self.battle.toggle_pause()
            self.state = "paused"
            log.info("[UI] 已暂停")
        elif self.state == "paused" and self.battle:
            self.battle.toggle_pause()
            self.state = "running"
            log.info("[UI] 已恢复")
        self._refresh_buttons()

    # ---------- 退出 ----------

    def on_quit(self):
        log.info("[UI] 退出程序")
        if self.battle:
            self.battle.stop()
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
        if self.battle and not self.battle.running and self.state in ("running", "paused"):
            self.state = "idle"
            self.battle = None
            self._refresh_buttons()
        self.root.after(500, self._update_status)


# ====================================================
# 主入口
# ====================================================


def main():
    print("=" * 50)
    print("  Ready")
    print("=" * 50)
    detector = PageDetector()

    root = tk.Tk()
    panel = ControlPanel(root, detector)

    # 注册全局热键 —— 通过 root.after 保证线程安全
    register_hotkey(VK_F6, lambda: root.after(0, panel.on_pause_resume))
    register_hotkey(VK_F7, lambda: root.after(0, panel.on_select_region))
    register_hotkey(VK_ESCAPE, lambda: root.after(0, panel.on_quit))
    start_hotkey_polling()

    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("未捕获异常")
        traceback.print_exc()
