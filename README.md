# 洛克王国：世界 - 自动战斗工具

针对《洛克王国：世界》的自动战斗辅助工具，通过屏幕截图 + 模板匹配识别游戏界面状态，自动完成战斗操作。

> **声明：** 非商业售卖，仅供学习娱乐。最终解释权归开发者 Larito 所有。

## 功能

### Auto Battle（自动战斗）

通过 OpenCV 模板匹配识别当前游戏界面，自动执行对应操作：

| 界面状态 | 识别方式 | 自动操作 |
|---------|---------|---------|
| 技能选择页（buttonPage） | 左下角匹配星形按钮模板 | 点击星形按钮（使用默认技能） |
| 精灵选择页（selectHero） | 左侧匹配 ⊙ 图标模板 | 依次按 1~6 + 空格，逐个尝试出战精灵 |
| 其他界面 | 无匹配 | 等待，偶尔随机移动鼠标 |

### Auto Clicker（自动点击器）

在框选区域内以 1.1~1.5 秒的随机间隔自动点击，点击位置偏向区域中心（高斯分布）。适用于需要反复点击的场景（如重复挑战）。

### 共同特性

- **人性化模拟** — 贝塞尔曲线鼠标移动轨迹 + 随机抖动 + 不均匀速度，模拟真实手部操作
- **全局热键** — 基于 GetAsyncKeyState 轮询，无系统钩子注册，游戏窗口聚焦时也能响应
- **GUI 控制面板** — 深色主题的 Tkinter 界面，支持区域框选、开始/停止/暂停
- **自动提权** — 启动时自动请求管理员权限（绕过 UIPI）
- **窗口/进程伪装** — 随机窗口标题 + 打包时随机 EXE 文件名，避免被枚举检测

### 反检测架构

工具内置多层反检测机制，自动选择最优后端：

| 检测向量 | 防御措施 | 后端 |
|---------|---------|------|
| 输入注入标志（LLMHF_INJECTED） | Interception 驱动层注入，无注入标志 | `interception-python`（需装驱动） |
| 低级键盘钩子扫描 | 使用 GetAsyncKeyState 轮询替代钩子 | 内置（无需额外依赖） |
| GDI 截屏拦截 | DXGI Desktop Duplication，GPU 层面截屏 | `dxcam`（自动回退 GDI） |
| 窗口标题枚举 | 每次启动随机生成无特征标题 | 内置 |
| 进程名扫描 | 打包时随机生成类系统进程名 | `build.py` |
| 服务端 AI 行为分析 | 混合延迟分布 + 随机分心暂停 + 偶尔犹豫跳过 | 内置 |

所有反检测后端采用**优雅降级**策略：Interception 未安装时自动回退 SendInput，dxcam 不可用时自动回退 GDI BitBlt。

## 快捷键

| 按键 | 功能 |
|------|------|
| F6 | 暂停 / 恢复 |
| F7 | 重新框选游戏区域 |
| Esc | 退出程序 |

## 使用方法

### 环境要求

- Windows 10/11
- Python 3.8+
- 游戏分辨率设置为 **1176 x 664**

### 依赖安装

启动时会自动检测依赖，缺少任何一项都会弹窗提示并阻止启动。

```bash
pip install opencv-python numpy interception-python pywin32 dxcam
```

### Interception 驱动安装（推荐）

Interception 驱动可以让模拟输入完全等同于真实硬件输入，消除 `LLMHF_INJECTED` 标志。

1. 从 [Interception releases](https://github.com/oblitum/Interception/releases) 下载 `Interception.zip`
2. 解压后以管理员身份运行：
   ```bash
   "command line installer/install-interception.exe" /install
   ```
3. **重启电脑**（驱动需要重启才能生效）

未安装驱动时工具仍可正常运行，会自动回退到 SendInput。

### 直接运行

```bash
# 自动战斗
python src/auto_battle.py

# 自动点击器
python src/auto_clicker.py
```

### 打包为 EXE

双击 `build.bat` 或运行：

```bash
python build.py
```

打包后的 EXE 位于 `Build/` 目录下，文件名为随机生成的类系统进程名（如 `svchost_abcd.exe`），可独立运行。

## 操作步骤

1. 运行工具（会自动弹出 UAC 管理员权限请求）
2. 在控制面板点击「选择区域」或按 F7，拖拽框选游戏窗口
3. 点击「开始」，工具自动初始化后端并开始运行
4. 按 F6 随时暂停/恢复，按 Esc 退出

启动后控制台会输出当前激活的后端：

```
[后端] Interception 驱动已激活
[后端] DXGI 截屏已激活
[启动] 自动战斗运行中  |  F6 暂停/恢复  F7 重选  Esc 退出
```

## 项目结构

```
├── src/
│   ├── auto_battle.py      # 自动战斗主程序（界面识别 + 自动操作）
│   ├── auto_clicker.py     # 自动点击器（区域内随机点击）
│   ├── Button.jpg          # 模板图片 - 星形按钮
│   ├── selectPage.jpg      # 模板图片 - 精灵选择界面（用于裁剪 ⊙ 图标）
│   ├── SelectHero.jpg      # 参考截图 - 精灵列表
│   └── buttonPage.jpg      # 参考截图 - 技能选择界面
├── Build/                  # 打包输出目录（EXE 文件名随机）
├── build.py                # PyInstaller 打包脚本（自动随机化 EXE 名称）
├── build.bat               # 一键打包批处理
└── .gitignore
```

## 联系方式

QQ: 275899142
