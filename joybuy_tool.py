import tkinter as tk
from tkinter import scrolledtext, ttk
import re
import threading
import time
import platform
import subprocess
import pyautogui
import pyperclip
import os
import sys
import pandas as pd
import webbrowser
import shutil

# Best-effort import for window management; may not work on some Linux environments (Wayland)
try:
    import pygetwindow as gw  # type: ignore
except Exception:
    gw = None  # Fallback when window APIs are unavailable


# 基础配置
pyautogui.FAILSAFE = True
BASE_URL = "http://operation.joybuy.com/product/productEdit?productId={}&refresh=1756991165572"
FRONTEND_PRODUCT_URL = "https://www.joybuy.de/dp/{}"  # 前端商品页面URL模板
CHROME_TITLE_KEYWORD = "Google Chrome"
WINDOW_ACTIVATE_DELAY = 1.0
KEYBOARD_OP_DELAY = 0.3
MAX_LOAD_WAIT = 30
LOAD_RETRY_COUNT = 3
LOAD_CHECK_INTERVAL = 1
TAB_SWITCH_DELAY = 1.0
ADDRESS_BAR_CLICK_DELAY = 0.2


def get_resource_path(relative_path: str) -> str:
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# 数据文件路径
REPEAT_SPU_FILE = get_resource_path("重复SPU_结果.xlsx")
SKU_SPU_MAPPING_FILE = get_resource_path("SKU_SPU.xlsx")
ICON_PATH = get_resource_path("id_T_HwOLT_1757043427406.ico")


# 全局数据存储
repeat_spu_set: set[str] = set()  # 重复SPU集合
sku_spu_map: dict[str, str] = {}  # SKU→SPU映射


def open_example_url(url: str) -> None:
    webbrowser.open_new(url)


def _windows_chrome_path() -> str | None:
    candidate_paths = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ]
    for candidate in candidate_paths:
        if os.path.exists(candidate):
            return candidate
    return None


def resolve_chrome_command() -> list[str] | None:
    """Return a command list to start Chrome/Chromium with --new-window, cross-platform.

    - Windows: returns full chrome.exe path with --new-window
    - macOS: uses `open -a Google Chrome --new --args --new-window`
    - Linux: try common binaries (google-chrome, google-chrome-stable, chromium, chromium-browser, brave-browser, microsoft-edge, microsoft-edge-stable)
    """
    system = platform.system()
    if system == "Windows":
        chrome_path = _windows_chrome_path()
        if not chrome_path:
            return None
        return [chrome_path, "--new-window"]
    if system == "Darwin":
        return ["open", "-a", "Google Chrome", "--new", "--args", "--new-window"]

    # Linux and others: find available browser
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
    ]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return [path, "--new-window"]
    return None


def load_essential_data() -> bool:
    """启动时加载重复SPU集合和SKU-SPU映射表"""
    global repeat_spu_set, sku_spu_map
    load_success = True

    try:
        df_repeat = pd.read_excel(REPEAT_SPU_FILE)
        if not df_repeat.empty:
            repeat_spu_list = df_repeat.iloc[1:, 0].astype(str).tolist()
            repeat_spu_set = set([spu for spu in repeat_spu_list if spu.isdigit()])
    except Exception:
        status_label.config(text=f"❌ 重复SPU文件错误：读取{REPEAT_SPU_FILE}失败", foreground="#e74c3c")
        load_success = False

    try:
        df_mapping = pd.read_excel(SKU_SPU_MAPPING_FILE)
        if not df_mapping.empty:
            for _, row in df_mapping.iterrows():
                sku = str(row.iloc[0]).strip()
                spu = str(row.iloc[1]).strip()
                if sku.isdigit() and spu.isdigit():
                    sku_spu_map[sku] = spu
    except Exception:
        status_label.config(text=f"❌ SKU-SPU文件错误：读取{SKU_SPU_MAPPING_FILE}失败", foreground="#e74c3c")
        load_success = False

    if load_success:
        status_label.config(
            text=f"✅ 数据就绪：{len(repeat_spu_set)}个支配型SPU | {len(sku_spu_map)}条SKU映射",
            foreground="#666666",
        )
    else:
        status_label.config(text="❌ 部分数据加载失败，请检查文件路径", foreground="#e74c3c")
    return load_success


def parse_sku_input(input_text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """解析用户输入的SKU列表，返回有效SKU-SPU对（最多50个）和无效行"""
    lines = [line.strip() for line in input_text.split('\n') if line.strip()]
    valid_sku_spu: list[tuple[str, str]] = []
    invalid_lines: list[str] = []

    for line_num, line in enumerate(lines, 1):
        parts = [p.strip() for p in line.split('\t') if p.strip()]
        sku = parts[0] if parts else line

        if not sku.isdigit():
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」非数字")
            continue

        if sku not in sku_spu_map:
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」无匹配SPU")
            continue

        if any(existing_sku == sku for existing_sku, _ in valid_sku_spu):
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」重复（已保留首次出现）")
            continue

        valid_sku_spu.append((sku, sku_spu_map[sku]))

        if len(valid_sku_spu) >= 50:
            break

    status_label.config(text=f"✅ 已解析 {len(valid_sku_spu)} 个有效SKU（最多50个）")
    return valid_sku_spu, invalid_lines


def split_skus_by_repeat_status(valid_skus: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    repeat_skus: list[tuple[str, str]] = []
    normal_skus: list[tuple[str, str]] = []
    for sku, spu in valid_skus:
        if spu in repeat_spu_set:
            repeat_skus.append((sku, spu))
        else:
            normal_skus.append((sku, spu))
    return repeat_skus, normal_skus


def start_normal_spu_window(normal_skus: list[tuple[str, str]]) -> bool:
    """用subprocess启动Chrome新窗口，批量打开非重复SPU的URL（仅启动，不等待加载）"""
    if not normal_skus:
        return False

    url_list = [BASE_URL.format(spu) for _, spu in normal_skus]
    chrome_cmd = resolve_chrome_command()
    if not chrome_cmd:
        status_label.config(text="❌ 未找到可用的Chrome/Chromium，请检查安装路径")
        return False

    chrome_cmd = [*chrome_cmd, *url_list]

    try:
        if platform.system() == "Windows":
            subprocess.Popen(
                chrome_cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            subprocess.Popen(chrome_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        status_label.config(text=f"❌ 启动失败：无法启动Chrome，{str(e)}")
        return False


def activate_new_chrome_window(url_list: list[str], window_title_suffix: str):
    """启动Chrome新窗口并激活（用于重复SPU，需后续检索）"""
    system = platform.system()
    existing_window_handles: set[int] = set()

    if gw is not None and system in ("Windows", "Darwin"):
        try:
            for window in (gw.getWindowsWithTitle(CHROME_TITLE_KEYWORD) if gw else []):
                try:
                    existing_window_handles.add(window._hWnd)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            existing_window_handles = set()

    chrome_cmd = resolve_chrome_command()
    if not chrome_cmd:
        status_label.config(text="❌ 未找到可用的Chrome/Chromium，请检查安装路径")
        return None

    cmd = [*chrome_cmd, *url_list]

    try:
        if platform.system() == "Windows":
            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(cmd)
        time.sleep(6)
    except Exception as e:
        status_label.config(text=f"❌ 启动失败：无法启动新Chrome，{str(e)}")
        return None

    if gw is None or system not in ("Windows", "Darwin"):
        # 在Linux或无窗口API时，跳过显式激活，直接返回占位对象
        return True

    new_window = None
    for _ in range(15):
        try:
            current_windows = gw.getWindowsWithTitle(CHROME_TITLE_KEYWORD) if gw else []
        except Exception:
            current_windows = []
        for window in current_windows:
            try:
                if getattr(window, "_hWnd", None) not in existing_window_handles and window.title.strip():
                    new_window = window
                    try:
                        window.title = f"{window.title} - 【{window_title_suffix}】"
                    except Exception:
                        pass
                    break
            except Exception:
                continue
        if new_window:
            break
        time.sleep(1)

    if not new_window:
        status_label.config(text="❌ 窗口识别失败：新Chrome窗口已启动，但无法定位")
        return None

    try:
        new_window.activate()
        new_window.maximize()
    except Exception:
        pass
    time.sleep(WINDOW_ACTIVATE_DELAY)
    return new_window


def get_current_tab_info():
    """获取当前标签页的SPU、URL和标题（用于重复SPU加载校验）"""
    try:
        pyautogui.hotkey('ctrl', 'l')
        pyautogui.hotkey('ctrl', 'c')
        url = pyperclip.paste().strip()

        if not url.startswith(("http://", "https://")):
            raise Exception(f"无效URL：{url[:20]}...")

        spu_match = re.search(r'productId=(\d+)', url)
        if not spu_match:
            raise Exception(f"URL中未找到SPU：{url[:50]}...")

        title_text = ""
        try:
            if gw is not None:
                active = gw.getActiveWindow()
                title_text = active.title if active else ""
        except Exception:
            title_text = ""

        return {"spu": spu_match.group(1), "url": url, "title": title_text}
    except Exception as e:
        status_label.config(text=f"⚠️ 标签页信息提取失败：{str(e)}")
    return None


def search_sku_in_tab(sku: str) -> bool:
    try:
        pyautogui.hotkey('ctrl', 'f')
        pyautogui.press('backspace', presses=20)
        pyautogui.typewrite(sku)
        pyautogui.press('enter')
        pyautogui.press('esc')
        return True
    except Exception:
        status_label.config(text=f"❌ SKU检索失败：SKU「{sku}」出错")
        return False


def parse_frontend_sku_input(input_text: str) -> tuple[list[str], list[str]]:
    """解析用户输入的前端SKU列表，返回有效SKU（最多50个）和无效行"""
    lines = [line.strip() for line in input_text.split('\n') if line.strip()]
    valid_skus: list[str] = []
    invalid_lines: list[str] = []

    for line_num, line in enumerate(lines, 1):
        sku = line.strip()
        if not sku.isdigit():
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」非数字")
            continue
        if sku in valid_skus:
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」重复（已保留首次出现）")
            continue
        valid_skus.append(sku)
        if len(valid_skus) >= 50:
            break

    return valid_skus, invalid_lines


def start_frontend_spu_window(frontend_skus: list[str]) -> bool:
    """用subprocess启动Chrome新窗口，批量打开前端商品URL（仅启动，不等待加载）"""
    if not frontend_skus:
        return False

    url_list = [FRONTEND_PRODUCT_URL.format(sku) for sku in frontend_skus]
    chrome_cmd = resolve_chrome_command()
    if not chrome_cmd:
        status_label.config(text="❌ 未找到可用的Chrome/Chromium，请检查安装路径")
        return False

    chrome_cmd = [*chrome_cmd, *url_list]

    try:
        if platform.system() == "Windows":
            subprocess.Popen(
                chrome_cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            subprocess.Popen(chrome_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        status_label.config(text=f"✅ 前端商品窗口已启动（{len(url_list)}个标签页）")
        return True
    except Exception as e:
        status_label.config(text=f"❌ 启动失败：无法启动Chrome，{str(e)}")
        return False


def process_repeat_skus(repeat_skus: list[tuple[str, str]]) -> tuple[int, int, int]:
    if not repeat_skus:
        return 0, 0, 0

    total_count = len(repeat_skus)
    search_success_count = 0
    fail_count = 0

    url_list = [BASE_URL.format(spu) for _, spu in repeat_skus]
    status_label.config(text=f"🔍 启动支配型SPU窗口（{total_count}个标签页，需检索）...")
    root.update()

    chrome_window = activate_new_chrome_window(url_list, "支配型SPU（需检索）")
    if not chrome_window:
        status_label.config(text=f"❌ 窗口启动失败，{total_count}个SKU处理失败")
        return 0, 0, total_count

    try:
        pyautogui.hotkey('ctrl', '1')
    except Exception:
        pass

    base_wait = 1.75 * total_count + 1.5
    if total_count >= 6:
        base_wait -= 1.5
    wait_seconds = max(int(base_wait), 3)

    status_label.config(text=f"⏳ 等待所有标签页加载（共{total_count}个，预计{wait_seconds}秒）...")
    root.update()
    time.sleep(wait_seconds)

    for tab_idx in range(total_count):
        current_step = tab_idx + 1
        sku, spu = repeat_skus[tab_idx]
        status_label.config(text=f"🔍 处理支配型SPU：第{current_step}/{total_count}个（SKU：{sku}，SPU：{spu}）")
        root.update()

        if search_sku_in_tab(sku):
            search_success_count += 1
        else:
            fail_count += 1

        if tab_idx < total_count - 1:
            try:
                pyautogui.hotkey('ctrl', 'tab')
            except Exception:
                pass

    load_success_count = total_count
    status_label.config(text=f"✅ 支配型SPU批次处理完成：加载{load_success_count}个，检索{search_success_count}个，失败{fail_count}个")
    return load_success_count, search_success_count, fail_count


def handle_only_repeat_skus() -> None:
    input_text = batch_sku_text.get("1.0", tk.END).strip()
    if not input_text:
        status_label.config(text="❌ 错误：请先在批量输入框中输入SKU列表（每行一个）")
        return

    valid_sku_spu, invalid_lines = parse_sku_input(input_text)
    repeat_skus, _ = split_skus_by_repeat_status(valid_sku_spu)
    repeat_count = len(repeat_skus)

    if repeat_count == 0:
        status_label.config(text="ℹ️ 提示：未检测到支配型SPU的SKU（所有SKU的SPU均不在重复列表中）")
        return

    BATCH_SIZE = 10
    batches = [repeat_skus[i:i + BATCH_SIZE] for i in range(0, repeat_count, BATCH_SIZE)]
    total_batches = len(batches)

    status_label.config(text=f"🔄 开始分批处理支配型SPU：共{repeat_count}个，分{total_batches}批，每批最多{BATCH_SIZE}个")

    def repeat_thread():
        try:
            for batch_idx, batch in enumerate(batches, 1):
                status_label.config(text=f"🔍 处理支配型SPU（第{batch_idx}/{total_batches}批，共{len(batch)}个）")
                root.update()
                process_repeat_skus(batch)
                time.sleep(2)
            status_label.config(text="✅ 支配型SPU所有批次处理完成")
        except Exception as e:
            status_label.config(text=f"❌ 处理异常：{str(e)}")
        finally:
            status_label.config(text="✅ 就绪：请输入SKU列表并选择操作")

    threading.Thread(target=repeat_thread, daemon=True).start()


def handle_only_normal_skus() -> None:
    input_text = batch_sku_text.get("1.0", tk.END).strip()
    if not input_text:
        status_label.config(text="❌ 错误：请先在批量输入框中输入SKU列表（每行一个）")
        return

    valid_sku_spu, invalid_lines = parse_sku_input(input_text)
    _, normal_skus = split_skus_by_repeat_status(valid_sku_spu)
    normal_count = len(normal_skus)

    if normal_count == 0:
        status_label.config(text="ℹ️ 提示：未检测到非支配型SPU的SKU（所有SKU的SPU均在重复列表中）")
        return

    if start_normal_spu_window(normal_skus):
        status_label.config(text=f"✅ 非支配型SPU窗口已启动（{normal_count}个标签页）")


def handle_batch_frontend_product() -> None:
    input_text = batch_frontend_sku_text.get("1.0", tk.END).strip()
    if not input_text:
        status_label.config(text="❌ 错误：请先在批量前端SKU输入框中输入SKU列表")
        return

    valid_skus, invalid_lines = parse_frontend_sku_input(input_text)
    valid_count = len(valid_skus)

    if invalid_lines:
        invalid_msg = "⚠️ 无效行已跳过：" + " | ".join(invalid_lines[:3])
        if len(invalid_lines) > 3:
            invalid_msg += f"（共{len(invalid_lines)}个无效行）"
        status_label.config(text=invalid_msg)
        time.sleep(2)

    if valid_count == 0:
        status_label.config(text="ℹ️ 提示：未检测到有效前端SKU（需输入数字SKU）")
        return

    start_frontend_spu_window(valid_skus)


# ---------------------- GUI界面 ----------------------
root = tk.Tk()

# Guard icon loading: .ico works on Windows; other platforms may fail
try:
    if platform.system() == "Windows" and os.path.exists(ICON_PATH):
        root.iconbitmap(ICON_PATH)
except Exception:
    pass

root.title("德国站商详批量打开和joybuy前端页面批量审阅工具")
root.geometry("780x600")
root.resizable(True, True)
root.configure(bg="#ffffff")

root.grid_rowconfigure(0, weight=1)
root.grid_rowconfigure(1, weight=3)
root.grid_rowconfigure(2, weight=1)
root.grid_rowconfigure(3, weight=1)
root.grid_columnconfigure(0, weight=1)

style = ttk.Style()
style.configure("TLabel", font=("微软雅黑", 10), foreground="#333333", background="#f5f5f5")
style.configure("TButton", font=("微软雅黑", 10, "bold"), padding=8, background="#f5f5f5")
style.configure("TFrame", background="#f5f5f5")

style.configure("Normal.TButton", foreground="#333333", background="#f5f5f5")
style.configure("Repeat.TButton", foreground="#ffffff", background="#e1251b")
style.configure("Frontend.TButton", foreground="#ffffff", background="#27ae60")
style.map("Normal.TButton", background=[("active", "#e8e8e8")])
style.map("Repeat.TButton", background=[("active", "#c8102e")])
style.map("Frontend.TButton", background=[("active", "#219653")])

top_frame = ttk.Frame(root)
top_frame.grid(row=0, column=0, sticky="nsew", pady=(10, 5), padx=10)

dominant_desc_label = ttk.Label(
    top_frame,
    text="📌 支配型SPU：1个SPU支配多个SKU（需高亮需处理的SKU定位edit按钮）",
    font=("微软雅黑", 9, "bold"),
    foreground="#EAC100",
    background="#f5f5f5",
    wraplength=720,
)
dominant_desc_label.pack(anchor="w", pady=(0, 2))

dominant_link_label = ttk.Label(
    top_frame,
    text="点击示例网站：iPad mini 2024 256GB Wi-Fi and Cel.",
    font=("微软雅黑", 9, "bold"),
    foreground="#000000",
    background="#f5f5f5",
    cursor="hand2",
    wraplength=720,
)
dominant_link_label.pack(anchor="w", pady=(0, 2))
dominant_link_label.bind(
    "<Button-1>",
    lambda event: open_example_url(
        "http://operation.joybuy.com/product/productEdit?productId=416844&refresh=1757041107817"
    ),
)

normal_desc_label = ttk.Label(
    top_frame,
    text="📌 非支配型SPU：1个SPU单独对应1个SKU，打开页面即可",
    font=("微软雅黑", 9, "bold"),
    foreground="#EAC100",
    background="#f5f5f5",
    wraplength=720,
)
normal_desc_label.pack(anchor="w", pady=(0, 2))

normal_link_label = ttk.Label(
    top_frame,
    text="点击示例网站：Logitech G29 Gaming Driving Force racing wheel",
    font=("微软雅黑", 9, "bold"),
    foreground="#000000",
    background="#f5f5f5",
    cursor="hand2",
    wraplength=720,
)
normal_link_label.pack(anchor="w", pady=(0, 2))
normal_link_label.bind(
    "<Button-1>",
    lambda event: open_example_url(
        "http://operation.joybuy.com/product/productEdit?productId=416944&refresh=1757041152064"
    ),
)

func_label = ttk.Label(
    top_frame,
    text="🔧 功能：1.分批打开支配型SPU编辑页面 2.批量打开非支配型SPU的编辑窗口  3.批量打开前端商品页面",
    foreground="#222222",
    font=("微软雅黑", 9),
    background="#f5f5f5",
)
func_label.pack(anchor="w", pady=(0, 2))

warn_label = ttk.Label(
    top_frame,
    text="⚠️ 注意：优先处理支配型SPU，且处理支配型SPU勿动鼠标和键盘，再处理非支配型SPU",
    foreground="#e1251b",
    font=("微软雅黑", 9, "bold"),
    background="#f5f5f5",
)
warn_label.pack(anchor="w", pady=(0, 2))

format_label = ttk.Label(
    top_frame,
    text="📝 输入格式：批量输入，每行1个数字SKU（最多50个，支持表格数据粘贴）",
    foreground="#222222",
    font=("微软雅黑", 9),
    background="#f5f5f5",
)
format_label.pack(anchor="w", pady=(0, 2))

input_container_frame = ttk.Frame(root)
input_container_frame.grid(row=1, column=0, sticky="nsew", pady=(5, 5), padx=10)
input_container_frame.grid_rowconfigure(0, weight=3)
input_container_frame.grid_rowconfigure(1, weight=1)
input_container_frame.grid_columnconfigure(0, weight=3)
input_container_frame.grid_columnconfigure(1, weight=1)

sku_input_frame = ttk.Frame(input_container_frame)
sku_input_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))

batch_input_prompt = ttk.Label(sku_input_frame, text="商详查询-SKU列表（每行一个，最多50个，支持批量粘贴）：")
batch_input_prompt.pack(anchor="w", pady=(0, 3))

batch_sku_text = scrolledtext.ScrolledText(
    sku_input_frame,
    width=45,
    height=5,
    font=("微软雅黑", 10),
    wrap=tk.WORD,
    bd=2,
    relief=tk.GROOVE,
)
batch_sku_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

batch_frontend_prompt = ttk.Label(sku_input_frame, text="前端检索-SKU列表（每行一个，最多50个，支持批量粘贴）：")
batch_frontend_prompt.pack(anchor="w", pady=(5, 3))

batch_frontend_sku_text = scrolledtext.ScrolledText(
    sku_input_frame,
    width=45,
    height=4,
    font=("微软雅黑", 10),
    wrap=tk.WORD,
    bd=2,
    relief=tk.GROOVE,
)
batch_frontend_sku_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

instruction_frame = ttk.Frame(input_container_frame)
instruction_frame.grid(row=0, column=1, sticky="nsew")

instruction_label = ttk.Label(
    instruction_frame,
    text=(
        "操作过程：\n"
        "1.批量复制粘贴SKU-ID到对应输入框（最多50个）\n"
        "2.先用按钮2批量打开支配型SPU编辑页面并高亮SKU\n"
        "3.再用按钮1打开非支配型SPU编辑页面\n"
        "4.点击edit编辑商详后保存\n"
        "4.在下方输入框键入SKU后进入前台审阅\n\n"
        "Chrome快捷键\n"
        "end 到页面最下方\n"
        "tab 到页面最上方\n"
        "ctrl+tab 下一页\n"
        "ctrl+shift+tab 上一页\n"
        "ctrl+w 关页面"
    ),
    font=("微软雅黑", 9),
    foreground="#222222",
    wraplength=300,
)
instruction_label.pack(anchor="w", pady=5, fill=tk.Y)

btn_frame = ttk.Frame(root)
btn_frame.grid(row=2, column=0, sticky="nsew", pady=(5, 5), padx=10)
btn_frame.grid_columnconfigure(0, weight=1)

only_repeat_btn = ttk.Button(
    btn_frame,
    text="1. 分批打开支配型SPU编辑界面（每批≤10个，分批处理完）",
    command=handle_only_repeat_skus,
    style="Normal.TButton",
)
only_repeat_btn.pack(pady=2, fill=tk.X)

only_normal_btn = ttk.Button(
    btn_frame,
    text="2. 批量打开非支配型SPU编辑界面（一次性全部）",
    command=handle_only_normal_skus,
    style="Normal.TButton",
)
only_normal_btn.pack(pady=2, fill=tk.X)

frontend_btn = ttk.Button(
    btn_frame,
    text="3. 打开Joybuy前端商品页面（批量检索）",
    command=handle_batch_frontend_product,
    style="Normal.TButton",
)
frontend_btn.pack(pady=2, fill=tk.X)

status_label = ttk.Label(
    root,
    text="✅ 就绪：请输入SKU列表并选择操作按钮",
    foreground="#e1251b",
    font=("微软雅黑", 10, "bold"),
    background="#ffffff",
)
status_label.grid(row=3, column=0, sticky="s", pady=5)

root.after(100, load_essential_data)

root.mainloop()

