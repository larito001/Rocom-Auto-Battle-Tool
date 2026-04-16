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

battle_name = _rand_name()

# 随机版本号，模拟系统组件
_ver = f"10.0.{random.randint(19041, 26100)}.{random.randint(1, 999)}"

# 文件描述与进程名匹配的说明
_DESC_MAP = {
    "svchost": "Host Process for Windows Services",
    "conhost": "Console Window Host",
    "dllhost": "COM Surrogate",
    "sihost": "Shell Infrastructure Host",
    "ctfmon": "CTF Loader",
    "taskhostw": "Host Process for Windows Tasks",
    "smartscreen": "Windows Defender SmartScreen",
    "fontdrvhost": "Usermode Font Driver Host",
}
_prefix = battle_name.split("_")[0]
_desc = _DESC_MAP.get(_prefix, "Windows System Service")

# 安装 Nuitka 及 ordered-set（加速编译）
subprocess.run([sys.executable, "-m", "pip", "install", "nuitka", "ordered-set", "-q"])

# 编译（Nuitka → 原生 C，无 Python 运行时解包特征）
print(f"\n===== 编译 {battle_name}.exe (Nuitka) =====")
subprocess.run([
    sys.executable, "-m", "nuitka",
    "--onefile",
    "--windows-disable-console",
    "--windows-uac-admin",
    f"--output-filename={battle_name}.exe",
    f"--output-dir={BUILD}",
    f"--include-data-files={os.path.join(SRC, 'Button.jpg')}=Button.jpg",
    f"--include-data-files={os.path.join(SRC, 'BattleReport.png')}=BattleReport.png",
    "--remove-output",
    "--assume-yes-for-downloads",
    # 伪装 Windows 版本信息资源
    f"--windows-company-name=Microsoft Corporation",
    f"--windows-product-name=Microsoft Windows Operating System",
    f"--windows-file-version={_ver}",
    f"--windows-product-version={_ver}",
    f"--windows-file-description={_desc}",
    os.path.join(SRC, "auto_battle.py"),
])

print(f"\n===== 完成！=====")
print(f"  auto_battle -> Build/{battle_name}.exe")
input("按回车键退出...")
