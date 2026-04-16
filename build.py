"""双击运行此脚本，打包生成 exe（输出到 Build 文件夹）"""
import subprocess
import sys
import os
import random
import string

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
BUILD = os.path.join(ROOT, "Build")

os.chdir(ROOT)

# 生成随机 EXE 名称，避免进程名被关键词扫描
def _rand_name():
    prefixes = ["svchost", "conhost", "dllhost", "sihost",
                "ctfmon", "taskhostw", "smartscreen", "fontdrvhost"]
    return random.choice(prefixes) + "_" + "".join(random.choices(string.ascii_lowercase, k=4))

clicker_name = _rand_name()
battle_name = _rand_name()

# 安装 PyInstaller
subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller", "-q"])

# 打包 auto_clicker
print(f"\n===== 打包 {clicker_name}.exe (auto_clicker) =====")
subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--onefile", "--windowed",
    "--name", clicker_name,
    "--uac-admin",
    "--distpath", BUILD,
    "--workpath", os.path.join(BUILD, "temp"),
    "--specpath", os.path.join(BUILD, "temp"),
    os.path.join(SRC, "auto_clicker.py"),
])

# 打包 auto_battle
print(f"\n===== 打包 {battle_name}.exe (auto_battle) =====")
subprocess.run([
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--onefile", "--windowed",
    "--name", battle_name,
    "--uac-admin",
    "--distpath", BUILD,
    "--workpath", os.path.join(BUILD, "temp"),
    "--specpath", os.path.join(BUILD, "temp"),
    "--add-data", os.path.join(SRC, "Button.jpg") + ";.",
    "--add-data", os.path.join(SRC, "selectPage.jpg") + ";.",
    os.path.join(SRC, "auto_battle.py"),
])

print(f"\n===== 完成！=====")
print(f"  auto_clicker -> Build/{clicker_name}.exe")
print(f"  auto_battle  -> Build/{battle_name}.exe")
input("按回车键退出...")
