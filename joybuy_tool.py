import tkinter as tk
from tkinter import scrolledtext, ttk
import re
import threading
import time
import pygetwindow as gw
import pyautogui
import platform
import subprocess
import pyperclip
import os
import pandas as pd
import webbrowser
import sys
import os

# 基础配置
pyautogui.FAILSAFE = True
BASE_URL = "http://operation.joybuy.com/product/productEdit?productId={}&refresh=1756991165572"
FRONTEND_PRODUCT_URL = "https://www.joybuy.de/dp/{}"  # 前端商品页面URL模板
CHROME_TITLE_KEYWORD = "Google Chrome"
WINDOW_ACTIVATE_DELAY = 1.0
KEYBOARD_OP_DELAY = 0.3
MAX_LOAD_WAIT = 30  # 重复SPU页面加载超时（非重复页面不等待）
LOAD_RETRY_COUNT = 3  # 重复SPU页面加载重试次数
LOAD_CHECK_INTERVAL = 1  # 重复SPU页面加载检查间隔
TAB_SWITCH_DELAY = 1.0
ADDRESS_BAR_CLICK_DELAY = 0.2

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        # 打包后使用临时目录路径
        base_path = sys._MEIPASS
    else:
        # 开发时使用当前脚本所在目录
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# 数据文件路径
REPEAT_SPU_FILE = get_resource_path("重复SPU_结果.xlsx")
SKU_SPU_MAPPING_FILE = get_resource_path("SKU_SPU.xlsx")
# 图标路径（如果需要在窗口标题栏显示图标）
ICON_PATH = get_resource_path("id_T_HwOLT_1757043427406.ico")


# 全局数据存储
repeat_spu_set = set()  # 重复SPU集合
sku_spu_map = {}  # SKU→SPU映射

# AI润色提示词
AI_PROMPT = """这是一个商品的商详，是机器翻译的结果，在不改变原来框架结构和行文内容的基础上，我需要你从两个维度检查，语言维度和商详维度，最后润色到如同德语母语者说的。

（1）语言层面：从德语母语者视角出发，审视是否有语法错误，是否有不准确不地道的搭配，是否有不合适的词汇，是否有中文乱码英文乱码，是否有错误的拼写等其他语言上不恰当需要润色的地方；

（2）商详维度，根据你的经验，不同类目的商详文字特点，3C Beauty等等类目标品的商详内容。帮我检查这段德语商详写得怎么样，有没有润色的地方，要求内容表达和框架结构上上不要修改，只润色语言。

不用输出思考和分析过程，只写给出润色后的德语结果，只有副标题加粗，副标题前不要有123序列号。"""

# 词典数据
DICTIONARY_DATA = """产品描述,Product description,1.Produktbeschreibung, Produktbeschreibung, Kurzbeschreibung, , 2.空格, 3.空格, 4.空格, 5.空格, 6.空格, 7.空格, 8.空格, 9.空格, 10.空格, 11.空格, 12.空格, 13.空格, 14.空格, 15.空格"""


def open_example_url(url):
    """点击标签时调用，打开对应示例URL"""
    webbrowser.open_new(url)  # 打开新浏览器窗口，避免覆盖现有页面


def load_essential_data():
    """启动时加载重复SPU集合和SKU-SPU映射表"""
    global repeat_spu_set, sku_spu_map
    load_success = True

    # 1. 加载重复SPU集合（A列第2行开始，仅保留数字SPU）
    try:
        df_repeat = pd.read_excel(REPEAT_SPU_FILE)
        if not df_repeat.empty:
            repeat_spu_list = df_repeat.iloc[1:, 0].astype(str).tolist()
            repeat_spu_set = set([spu for spu in repeat_spu_list if spu.isdigit()])
    except Exception as e:
        status_label.config(text=f"❌ 重复SPU文件错误：读取{REPEAT_SPU_FILE}失败", foreground="#e74c3c")
        load_success = False

    # 2. 加载SKU-SPU映射表（首列SKU，次列SPU，仅保留数字映射）
    try:
        df_mapping = pd.read_excel(SKU_SPU_MAPPING_FILE)
        if not df_mapping.empty:
            for _, row in df_mapping.iterrows():
                sku = str(row.iloc[0]).strip()
                spu = str(row.iloc[1]).strip()
                if sku.isdigit() and spu.isdigit():
                    sku_spu_map[sku] = spu
    except Exception as e:
        status_label.config(text=f"❌ SKU-SPU文件错误：读取{SKU_SPU_MAPPING_FILE}失败", foreground="#e74c3c")
        load_success = False

    # 更新加载状态提示（保留界面标签显示）
    if load_success:
        status_label.config(
            text=f"✅ 数据就绪：{len(repeat_spu_set)}个支配型SPU | {len(sku_spu_map)}条SKU映射",
            foreground="#666666"
        )
    else:
        status_label.config(
            text="❌ 部分数据加载失败，请检查文件路径",
            foreground="#e74c3c"
        )
    return load_success


def parse_sku_input(input_text):
    """解析用户输入的SKU列表，返回有效SKU-SPU对（最多50个）和无效行"""
    lines = [line.strip() for line in input_text.split('\n') if line.strip()]
    valid_sku_spu = []  # 有效（SKU, SPU）对
    invalid_lines = []  # 无效行记录

    for line_num, line in enumerate(lines, 1):
        # 支持纯SKU（每行一个）或Tab分隔格式（兼容旧格式）
        parts = [p.strip() for p in line.split('\t') if p.strip()]
        sku = parts[0] if parts else line

        # 校验1：SKU是否为数字
        if not sku.isdigit():
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」非数字")
            continue

        # 校验2：SKU是否有对应SPU
        if sku not in sku_spu_map:
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」无匹配SPU")
            continue

        # 校验3：避免重复SKU
        if any(existing_sku == sku for existing_sku, _ in valid_sku_spu):
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」重复（已保留首次出现）")
            continue

        valid_sku_spu.append((sku, sku_spu_map[sku]))

        # 最多保留50个有效SKU
        if len(valid_sku_spu) >= 50:
            break

    # 状态标签提示有效数量
    status_label.config(text=f"✅ 已解析 {len(valid_sku_spu)} 个有效SKU（最多50个）")
    return valid_sku_spu, invalid_lines


def split_skus_by_repeat_status(valid_skus):
    """将有效SKU-SPU对按SPU是否重复分类"""
    repeat_skus = []  # 需检索：SPU在重复集合中
    normal_skus = []  # 无需检索：SPU不在重复集合中
    for sku, spu in valid_skus:
        if spu in repeat_spu_set:
            repeat_skus.append((sku, spu))
        else:
            normal_skus.append((sku, spu))
    return repeat_skus, normal_skus


# ---------------------- 非重复SPU专用启动函数（subprocess直接打开，不等待加载） ----------------------
def start_normal_spu_window(normal_skus):
    """用subprocess启动Chrome新窗口，批量打开非重复SPU的URL（仅启动，不等待加载）"""
    if not normal_skus:
        return False

    # 生成非重复SPU的URL列表
    url_list = [BASE_URL.format(spu) for _, spu in normal_skus]
    chrome_cmd = []

    # 跨系统配置Chrome启动命令
    if platform.system() == "Windows":
        # Windows Chrome路径（优先64位，再32位）
        chrome_paths = [
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"
        ]
        chrome_path = next((p for p in chrome_paths if os.path.exists(p)), None)
        if not chrome_path:
            status_label.config(text="❌ Chrome未找到，请检查安装路径")
            return False
        chrome_cmd = [chrome_path, "--new-window"]  # --new-window：强制新窗口
    elif platform.system() == "Darwin":  # macOS
        chrome_cmd = ["open", "-a", "Google Chrome", "--new", "--args", "--new-window"]
    else:  # Linux
        chrome_cmd = ["google-chrome", "--new-window"]

    # 添加所有URL（每个URL对应一个标签页）
    chrome_cmd.extend(url_list)

    # 启动Chrome（隐藏命令行黑框）
    try:
        if platform.system() == "Windows":
            subprocess.Popen(
                chrome_cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,  # 隐藏Windows命令行窗口
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        else:
            subprocess.Popen(chrome_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        status_label.config(text=f"❌ 启动失败：无法启动Chrome，{str(e)}")
        return False


# ---------------------- 独立按钮1 - 仅打开非重复SPU窗口 ----------------------
def handle_only_normal_skus():
    """独立按钮回调：仅处理非重复SPU（subprocess打开窗口，不检索）"""
    input_text = batch_sku_text.get("1.0", tk.END).strip()
    if not input_text:
        status_label.config(text="❌ 错误：请先在批量输入框中输入SKU列表（每行一个）")
        return

    # 解析输入并分类（最多50个有效SKU）
    valid_sku_spu, invalid_lines = parse_sku_input(input_text)
    _, normal_skus = split_skus_by_repeat_status(valid_sku_spu)
    normal_count = len(normal_skus)

    # 无有效非重复SKU时提示
    if normal_count == 0:
        status_label.config(text="ℹ️ 提示：未检测到非支配型SPU的SKU（所有SKU的SPU均在重复列表中）")
        return

    # 启动非重复SPU窗口
    if start_normal_spu_window(normal_skus):
        status_label.config(text=f"✅ 非支配型SPU窗口已启动（{normal_count}个标签页）")


# ---------------------- 重复SPU处理逻辑（分批处理+无弹窗） ----------------------
def activate_new_chrome_window(url_list, window_title_suffix):
    """启动Chrome新窗口并激活（用于重复SPU，需后续检索）"""
    existing_window_handles = set()
    # 记录已存在的Chrome窗口句柄，避免误识别
    for window in gw.getWindowsWithTitle(CHROME_TITLE_KEYWORD) + gw.getWindowsWithTitle("谷歌浏览器"):
        existing_window_handles.add(window._hWnd)

    chrome_cmd = []
    if platform.system() == "Windows":
        chrome_paths = [
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"
        ]
        chrome_path = next((p for p in chrome_paths if os.path.exists(p)), None)
        if not chrome_path:
            status_label.config(text="❌ Chrome未找到，请检查安装路径")
            return None
        chrome_cmd = [chrome_path, "--new-window"]
    elif platform.system() == "Darwin":
        chrome_cmd = ["open", "-a", "Google Chrome", "--new", "--args", "--new-window"]
    else:
        chrome_cmd = ["google-chrome", "--new-window"]

    chrome_cmd.extend(url_list)

    try:
        subprocess.Popen(chrome_cmd,
                         creationflags=subprocess.CREATE_NEW_CONSOLE if platform.system() == "Windows" else 0)
        time.sleep(6)  # 等待浏览器进程启动（非页面加载）
    except Exception as e:
        status_label.config(text=f"❌ 启动失败：无法启动新Chrome，{str(e)}")
        return None

    # 定位新窗口并激活
    new_window = None
    for _ in range(15):  # 最多尝试15次定位
        current_windows = gw.getWindowsWithTitle(CHROME_TITLE_KEYWORD) + gw.getWindowsWithTitle("谷歌浏览器")
        for window in current_windows:
            if window._hWnd not in existing_window_handles and window.title.strip():
                new_window = window
                # 标记窗口标题，便于区分
                try:
                    window.title = f"{window.title} - 【支配型SPU（需检索）】"
                except:
                    pass
                break
        if new_window:
            break
        time.sleep(1)

    if not new_window:
        status_label.config(text="❌ 窗口识别失败：新Chrome窗口已启动，但无法定位")
        return None

    new_window.activate()
    new_window.maximize()
    time.sleep(WINDOW_ACTIVATE_DELAY)
    return new_window


def get_current_tab_info():
    """获取当前标签页的SPU、URL和标题（用于重复SPU加载校验）"""
    max_retries = 1
    retry_delay = 1.0
    for attempt in range(max_retries):
        try:
            # 仅使用热键操作，更稳定
            pyautogui.hotkey('ctrl', 'l')  # 全选地址栏
            pyautogui.hotkey('ctrl', 'c')  # 复制URL
            url = pyperclip.paste().strip()

            if not url.startswith(("http://", "https://")):
                raise Exception(f"无效URL：{url[:20]}...")

            # 提取SPU
            spu_match = re.search(r'productId=(\d+)', url)
            if not spu_match:
                raise Exception(f"URL中未找到SPU：{url[:50]}...")

            return {
                "spu": spu_match.group(1),
                "url": url,
                "title": gw.getActiveWindow().title
            }
        except Exception as e:
            error_msg = f"标签页信息提取失败：{str(e)}"
            status_label.config(text=f"⚠️ {error_msg}")
    return None


def search_sku_in_tab(sku):
    """在当前标签页执行SKU检索（仅重复SPU需要）"""
    try:
        pyautogui.hotkey('ctrl', 'f')
        pyautogui.press('backspace', presses=20)  # 清空搜索框
        pyautogui.typewrite(sku)
        pyautogui.press('enter')
        pyautogui.press('esc')  # 关闭搜索框
        return True
    except Exception as e:
        status_label.config(text=f"❌ SKU检索失败：SKU「{sku}」出错")
        return False

#新增批量前端 SKU 解析函数
def parse_frontend_sku_input(input_text):
    """解析用户输入的前端SKU列表，返回有效SKU（最多50个）和无效行"""
    lines = [line.strip() for line in input_text.split('\n') if line.strip()]
    valid_skus = []  # 有效前端SKU
    invalid_lines = []  # 无效行记录

    for line_num, line in enumerate(lines, 1):
        sku = line.strip()

        # 校验1：SKU是否为数字
        if not sku.isdigit():
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」非数字")
            continue

        # 校验2：避免重复SKU
        if sku in valid_skus:
            invalid_lines.append(f"第{line_num}行：SKU「{sku}」重复（已保留首次出现）")
            continue

        valid_skus.append(sku)

        # 最多保留50个有效SKU
        if len(valid_skus) >= 50:
            break

    return valid_skus, invalid_lines

#新增批量启动前端页面函数
def start_frontend_spu_window(frontend_skus):
    """用subprocess启动Chrome新窗口，批量打开前端商品URL（仅启动，不等待加载）"""
    if not frontend_skus:
        return False

    # 生成前端商品URL列表
    url_list = [FRONTEND_PRODUCT_URL.format(sku) for sku in frontend_skus]
    chrome_cmd = []

    # 跨系统配置Chrome启动命令
    if platform.system() == "Windows":
        chrome_paths = [
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"
        ]
        chrome_path = next((p for p in chrome_paths if os.path.exists(p)), None)
        if not chrome_path:
            status_label.config(text="❌ Chrome未找到，请检查安装路径")
            return False
        chrome_cmd = [chrome_path, "--new-window"]
    elif platform.system() == "Darwin":
        chrome_cmd = ["open", "-a", "Google Chrome", "--new", "--args", "--new-window"]
    else:
        chrome_cmd = ["google-chrome", "--new-window"]

    chrome_cmd.extend(url_list)

    # 启动Chrome（隐藏命令行黑框）
    try:
        if platform.system() == "Windows":
            subprocess.Popen(
                chrome_cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        else:
            subprocess.Popen(chrome_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        status_label.config(text=f"✅ 前端商品窗口已启动（{len(url_list)}个标签页）")
        return True
    except Exception as e:
        status_label.config(text=f"❌ 启动失败：无法启动Chrome，{str(e)}")
        return False

def process_repeat_skus(repeat_skus):
    """处理重复SPU的核心逻辑（分档优化等待时间）"""
    if not repeat_skus:
        return 0, 0, 0  # 加载成功数、检索成功数、失败数

    total_count = len(repeat_skus)
    search_success_count = 0
    fail_count = 0

    # 生成重复SPU的URL列表
    url_list = [BASE_URL.format(spu) for _, spu in repeat_skus]
    status_label.config(text=f"🔍 启动支配型SPU窗口（{total_count}个标签页，需检索）...")
    root.update()

    # 启动Chrome窗口
    chrome_window = activate_new_chrome_window(url_list, "支配型SPU（需检索）")
    if not chrome_window:
        status_label.config(text=f"❌ 窗口启动失败，{total_count}个SKU处理失败")
        return 0, 0, total_count  # 窗口启动失败，全部记为失败

    # 定位到第一个标签页（已移除冗余sleep）
    pyautogui.hotkey('ctrl', '1')

    # 核心优化：分档计算等待时间
    # 1. 基础公式：1.75 * 数量 + 1.5（保留你调整的基础值）
    # 2. 当数量≥6时，额外减少1.5秒（符合你的要求）
    base_wait = 1.75 * total_count + 1.5
    if total_count >= 6:
        base_wait -= 1.5  # 6及以上数量减少1.5秒
    wait_seconds = int(base_wait)

    # 确保等待时间不小于最低值（避免极端情况）
    wait_seconds = max(wait_seconds, 3)

    status_label.config(
        text=f"⏳ 等待所有标签页加载（共{total_count}个，预计{wait_seconds}秒）..."
    )
    root.update()
    time.sleep(wait_seconds)  # 整体等待，不再逐页检测

    # 逐个处理检索+标签切换（保留无延迟切换）
    for tab_idx in range(total_count):
        current_step = tab_idx + 1
        sku, spu = repeat_skus[tab_idx]
        status_label.config(
            text=f"🔍 处理支配型SPU：第{current_step}/{total_count}个（SKU：{sku}，SPU：{spu}）"
        )
        root.update()

        # 执行SKU检索
        if search_sku_in_tab(sku):
            search_success_count += 1
        else:
            fail_count += 1

        # 切换到下一个标签页（无额外延迟，按你的优化保留）
        if tab_idx < total_count - 1:
            pyautogui.hotkey('ctrl', 'tab')

    load_success_count = total_count  # 默认全部加载成功
    status_label.config(
        text=f"✅ 支配型SPU批次处理完成：加载{load_success_count}个，检索{search_success_count}个，失败{fail_count}个")
    return load_success_count, search_success_count, fail_count


# ---------------------- 独立按钮2 - 仅处理重复SPU检索（分批处理） ----------------------
def handle_only_repeat_skus():
    """独立按钮回调：仅处理重复SPU（分批加载+检索，用线程避免UI阻塞）"""
    input_text = batch_sku_text.get("1.0", tk.END).strip()
    if not input_text:
        status_label.config(text="❌ 错误：请先在批量输入框中输入SKU列表（每行一个）")
        return

    # 解析输入并分类
    valid_sku_spu, invalid_lines = parse_sku_input(input_text)
    repeat_skus, _ = split_skus_by_repeat_status(valid_sku_spu)
    repeat_count = len(repeat_skus)

    # 无有效重复SKU时提示
    if repeat_count == 0:
        status_label.config(text="ℹ️ 提示：未检测到支配型SPU的SKU（所有SKU的SPU均不在重复列表中）")
        return

    # 分批处理：每批最多10个
    BATCH_SIZE = 10
    batches = [repeat_skus[i:i + BATCH_SIZE] for i in range(0, repeat_count, BATCH_SIZE)]
    total_batches = len(batches)

    status_label.config(text=f"🔄 开始分批处理支配型SPU：共{repeat_count}个，分{total_batches}批，每批最多{BATCH_SIZE}个")

    # 用线程执行，避免UI卡住
    def repeat_thread():
        try:
            for batch_idx, batch in enumerate(batches, 1):
                status_label.config(text=f"🔍 处理支配型SPU（第{batch_idx}/{total_batches}批，共{len(batch)}个）")
                root.update()
                process_repeat_skus(batch)
                time.sleep(2)  # 每批间间隔，避免资源挤占

            status_label.config(text="✅ 支配型SPU所有批次处理完成")
        except Exception as e:
            status_label.config(text=f"❌ 处理异常：{str(e)}")
        finally:
            status_label.config(text="✅ 就绪：请输入SKU列表并选择操作")

    threading.Thread(target=repeat_thread, daemon=True).start()


# ---------------------- 独立按钮3 - 打开前端商品页面（无弹窗） ----------------------
def handle_batch_frontend_product():
    """批量打开前端商品页面的回调函数"""
    input_text = batch_frontend_sku_text.get("1.0", tk.END).strip()
    if not input_text:
        status_label.config(text="❌ 错误：请先在批量前端SKU输入框中输入SKU列表")
        return

    # 解析输入
    valid_skus, invalid_lines = parse_frontend_sku_input(input_text)
    valid_count = len(valid_skus)

    # 提示无效行（无弹窗，状态栏显示）
    if invalid_lines:
        invalid_msg = "⚠️ 无效行已跳过：" + " | ".join(invalid_lines[:3])
        if len(invalid_lines) > 3:
            invalid_msg += f"（共{len(invalid_lines)}个无效行）"
        status_label.config(text=invalid_msg)
        time.sleep(2)  # 短暂停留让用户看到提示

    # 无有效SKU时提示
    if valid_count == 0:
        status_label.config(text="ℹ️ 提示：未检测到有效前端SKU（需输入数字SKU）")
        return

    # 启动批量前端页面
    start_frontend_spu_window(valid_skus)


# ---------------------- 新增功能：商详润色和词典功能 ----------------------
def handle_ai_polish():
    """AI润色功能：将商详内容与AI提示词连接后复制到剪贴板"""
    product_desc = product_desc_text.get("1.0", tk.END).strip()
    if not product_desc:
        status_label.config(text="❌ 错误：请先在商详输入框中输入内容")
        return
    
    # 组合商详内容和AI提示词
    combined_text = f"{product_desc}\n\n{AI_PROMPT}"
    
    # 复制到剪贴板
    pyperclip.copy(combined_text)
    status_label.config(text="✅ 商详内容已与AI提示词组合并复制到剪贴板")


def handle_dictionary_copy():
    """词典功能：复制词典内容到剪贴板"""
    pyperclip.copy(DICTIONARY_DATA)
    status_label.config(text="✅ 词典内容已复制到剪贴板")


def handle_clear_product_desc():
    """清空商详输入框内容"""
    product_desc_text.delete("1.0", tk.END)
    status_label.config(text="✅ 商详输入框已清空")


# ---------------------- GUI界面 ----------------------
root = tk.Tk()
root.iconbitmap(ICON_PATH)  # 若有图标可取消注释
root.title("德国站商详批量打开和joybuy前端页面批量审阅工具")
root.geometry("900x800")  # 增加高度以容纳新功能
root.resizable(True, True)
root.configure(bg="#ffffff")

# 全局Grid布局，垂直分5行
root.grid_rowconfigure(0, weight=1)
root.grid_rowconfigure(1, weight=4)  # 增加输入区域权重
root.grid_rowconfigure(2, weight=1)  # 按钮区权重确保可见
root.grid_rowconfigure(3, weight=1)  # 新增商详功能区
root.grid_rowconfigure(4, weight=1)  # 状态区
root.grid_columnconfigure(0, weight=1)  # 列全宽填充

# 样式配置：京东红+黑白灰配色体系
style = ttk.Style()
style.configure("TLabel", font=("微软雅黑", 10), foreground="#333333", background="#f5f5f5")
style.configure("TButton", font=("微软雅黑", 10, "bold"), padding=8, background="#f5f5f5")
style.configure("TFrame", background="#f5f5f5")

# 按钮样式：京东红为核心强调色
style.configure("Normal.TButton", foreground="#333333", background="#f5f5f5")  # 非重复SPU按钮
style.configure("Repeat.TButton", foreground="#ffffff", background="#e1251b")  # 重复SPU按钮（京东红）
style.configure("Frontend.TButton", foreground="#ffffff", background="#27ae60")  # 前端页面按钮（绿色）
style.configure("AI.TButton", foreground="#ffffff", background="#9b59b6")  # AI润色按钮（紫色）
style.configure("Dict.TButton", foreground="#ffffff", background="#f39c12")  # 词典按钮（橙色）
# 按钮悬停效果
style.map("Normal.TButton", background=[("active", "#e8e8e8")])
style.map("Repeat.TButton", background=[("active", "#c8102e")])  # 京东红加深
style.map("Frontend.TButton", background=[("active", "#219653")])  # 绿色加深
style.map("AI.TButton", background=[("active", "#8e44ad")])  # 紫色加深
style.map("Dict.TButton", background=[("active", "#e67e22")])  # 橙色加深

# 1. 顶部说明区（Grid行0）
top_frame = ttk.Frame(root)
top_frame.grid(row=0, column=0, sticky="nsew", pady=(10, 5), padx=10)

# 第1个标签：支配型SPU纯说明
dominant_desc_label = ttk.Label(
    top_frame,
    text="📌 支配型SPU：1个SPU支配多个SKU（需高亮需处理的SKU定位edit按钮）",
    font=("微软雅黑", 9, "bold"),
    foreground="#EAC100",
    background="#f5f5f5",
    wraplength=720
)
dominant_desc_label.pack(anchor="w", pady=(0, 2))

# 第2个标签：支配型SPU可点击示例
dominant_link_label = ttk.Label(
    top_frame,
    text="点击示例网站：iPad mini 2024 256GB Wi-Fi and Cel.",
    font=("微软雅黑", 9, "bold"),
    foreground="#000000",
    background="#f5f5f5",
    cursor="hand2",
    wraplength=720
)
dominant_link_label.pack(anchor="w", pady=(0, 2))
# 绑定支配型SPU的URL
dominant_link_label.bind(
    "<Button-1>",
    lambda event: open_example_url(
        "http://operation.joybuy.com/product/productEdit?productId=416844&refresh=1757041107817")
)

# 第3个标签：非支配型SPU纯说明
normal_desc_label = ttk.Label(
    top_frame,
    text="📌 非支配型SPU：1个SPU单独对应1个SKU，打开页面即可",
    font=("微软雅黑", 9, "bold"),
    foreground="#EAC100",
    background="#f5f5f5",
    wraplength=720
)
normal_desc_label.pack(anchor="w", pady=(0, 2))

# 第4个标签：非支配型SPU可点击示例
normal_link_label = ttk.Label(
    top_frame,
    text="点击示例网站：Logitech G29 Gaming Driving Force racing wheel",
    font=("微软雅黑", 9, "bold"),
    foreground="#000000",
    background="#f5f5f5",
    cursor="hand2",
    wraplength=720
)
normal_link_label.pack(anchor="w", pady=(0, 2))
# 绑定非支配型SPU的URL
normal_link_label.bind(
    "<Button-1>",
    lambda event: open_example_url(
        "http://operation.joybuy.com/product/productEdit?productId=416944&refresh=1757041152064")
)

# 第5行：功能说明
func_label = ttk.Label(
    top_frame,
    text="🔧 功能：1.分批打开支配型SPU编辑页面 2.批量打开非支配型SPU的编辑窗口  3.批量打开前端商品页面 4.AI商详润色 5.词典功能",
    foreground="#222222",
    font=("微软雅黑", 9),
    background="#f5f5f5"
)
func_label.pack(anchor="w", pady=(0, 2))

# 操作警告
warn_label = ttk.Label(
    top_frame,
    text="⚠️ 注意：优先处理支配型SPU，且处理支配型SPU勿动鼠标和键盘，再处理非支配型SPU",
    foreground="#e1251b",
    font=("微软雅黑", 9, "bold"),
    background="#f5f5f5"
)
warn_label.pack(anchor="w", pady=(0, 2))

# 输入格式提示（更新为两个输入框的说明）
format_label = ttk.Label(
    top_frame,
    text="📝 输入格式：批量输入，每行1个数字SKU（最多50个，支持表格数据粘贴）",
    foreground="#222222",
    font=("微软雅黑", 9),
    background="#f5f5f5"
)
format_label.pack(anchor="w", pady=(0, 2))


# 2. 输入与操作说明容器（Grid行1）
input_container_frame = ttk.Frame(root)
input_container_frame.grid(row=1, column=0, sticky="nsew", pady=(5, 5), padx=10)
# 输入容器内部Grid：左3右1分栏
input_container_frame.grid_rowconfigure(0, weight=2)  # 批量输入框
input_container_frame.grid_rowconfigure(1, weight=2)  # 前端输入框
input_container_frame.grid_rowconfigure(2, weight=3)  # 商详输入框
input_container_frame.grid_columnconfigure(0, weight=3)
input_container_frame.grid_columnconfigure(1, weight=1)

# 左侧：SKU输入区域（分为批量和单个两个输入框）
sku_input_frame = ttk.Frame(input_container_frame)
sku_input_frame.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(0, 10))

# 批量SKU输入框
batch_input_prompt = ttk.Label(sku_input_frame, text="商详查询-SKU列表（每行一个，最多50个，支持批量粘贴）：")
batch_input_prompt.pack(anchor="w", pady=(0, 3))

batch_sku_text = scrolledtext.ScrolledText(
    sku_input_frame,
    width=45,
    height=4,  # 调整高度
    font=("微软雅黑", 10),
    wrap=tk.WORD,
    bd=2,
    relief=tk.GROOVE
)
batch_sku_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

# 前端SKU输入框
batch_frontend_prompt = ttk.Label(sku_input_frame, text="前端检索-SKU列表（每行一个，最多50个，支持批量粘贴）：")
batch_frontend_prompt.pack(anchor="w", pady=(5, 3))

batch_frontend_sku_text = scrolledtext.ScrolledText(
    sku_input_frame,
    width=45,
    height=3,  # 可根据界面调整高度
    font=("微软雅黑", 10),
    wrap=tk.WORD,
    bd=2,
    relief=tk.GROOVE
)
batch_frontend_sku_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

# 商详输入框
product_desc_prompt = ttk.Label(sku_input_frame, text="商详润色-输入现有商详内容：")
product_desc_prompt.pack(anchor="w", pady=(5, 3))

product_desc_text = scrolledtext.ScrolledText(
    sku_input_frame,
    width=45,
    height=5,  # 商详输入框高度
    font=("微软雅黑", 10),
    wrap=tk.WORD,
    bd=2,
    relief=tk.GROOVE
)
product_desc_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

# 右侧：操作说明区域
instruction_frame = ttk.Frame(input_container_frame)
instruction_frame.grid(row=0, column=1, sticky="nsew")

instruction_label = ttk.Label(
    instruction_frame,
    text="操作过程：\n1.批量复制粘贴SKU-ID到对应输入框（最多50个）\n2.先用按钮2批量打开支配型SPU编辑页面并高亮SKU\n3.再用按钮1打开非支配型SPU编辑页面\n4.点击edit编辑商详后保存\n5.在下方输入框键入SKU后进入前台审阅\n6.使用AI润色功能处理商详内容\n7.使用词典功能快速复制常用词汇\n\nChrome快捷键\nend 到页面最下方\ntab 到页面最上方\nctrl+tab 下一页\nctrl+shift+tab 上一页\nctrl+w 关页面",
    font=("微软雅黑", 9),
    foreground="#222222",
    wraplength=300
)
instruction_label.pack(anchor="w", pady=5, fill=tk.Y)

# 3. 操作按钮区（Grid行2）
btn_frame = ttk.Frame(root)
btn_frame.grid(row=2, column=0, sticky="nsew", pady=(5, 5), padx=10)
btn_frame.grid_columnconfigure(0, weight=1)  # 按钮区水平填充

# 按钮2：分批处理支配型SPU检索
only_repeat_btn = ttk.Button(
    btn_frame,
    text="1. 分批打开支配型SPU编辑界面（每批≤10个，分批处理完）",
    command=handle_only_repeat_skus,
    style="Normal.TButton"
)
only_repeat_btn.pack(pady=2, fill=tk.X)

# 按钮1：仅打开非支配型SPU窗口
only_normal_btn = ttk.Button(
    btn_frame,
    text="2. 批量打开非支配型SPU编辑界面（一次性全部）",
    command=handle_only_normal_skus,
    style="Normal.TButton"
)
only_normal_btn.pack(pady=2, fill=tk.X)

# 按钮3：打开前端商品页面
frontend_btn = ttk.Button(
    btn_frame,
    text="3. 打开Joybuy前端商品页面（批量检索）",
    command=handle_batch_frontend_product,
    style="Normal.TButton"
)
frontend_btn.pack(pady=2, fill=tk.X)

# 4. 新增商详功能按钮区（Grid行3）
ai_frame = ttk.Frame(root)
ai_frame.grid(row=3, column=0, sticky="nsew", pady=(5, 5), padx=10)
ai_frame.grid_columnconfigure(0, weight=1)
ai_frame.grid_columnconfigure(1, weight=1)
ai_frame.grid_columnconfigure(2, weight=1)

# AI润色按钮
ai_polish_btn = ttk.Button(
    ai_frame,
    text="4. AI商详润色（复制到剪贴板）",
    command=handle_ai_polish,
    style="AI.TButton"
)
ai_polish_btn.grid(row=0, column=0, padx=5, pady=2, sticky="ew")

# 词典按钮
dict_btn = ttk.Button(
    ai_frame,
    text="5. 复制词典内容",
    command=handle_dictionary_copy,
    style="Dict.TButton"
)
dict_btn.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

# 清空商详按钮
clear_btn = ttk.Button(
    ai_frame,
    text="6. 清空商详输入框",
    command=handle_clear_product_desc,
    style="Normal.TButton"
)
clear_btn.grid(row=0, column=2, padx=5, pady=2, sticky="ew")

# 5. 底部状态区（Grid行4）
status_label = ttk.Label(
    root,
    text="✅ 就绪：请输入SKU列表并选择操作按钮",
    foreground="#e1251b",
    font=("微软雅黑", 10, "bold"),
    background="#ffffff"
)
status_label.grid(row=4, column=0, sticky="s", pady=5)

# 启动时加载数据（延迟100ms，确保GUI先渲染）
root.after(100, load_essential_data)

root.mainloop()