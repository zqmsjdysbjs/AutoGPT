import tkinter as tk
from tkinter import scrolledtext, ttk
import pyperclip

# ---------------- GUI -----------------
root = tk.Tk()
root.title("商详润色辅助工具")
root.geometry("600x500")
root.resizable(True, True)

style = ttk.Style()
style.configure("TLabel", font=("微软雅黑", 10), foreground="#333")
style.configure("TButton", font=("微软雅黑", 10, "bold"), padding=6)

# 1. 输入框
input_label = ttk.Label(root, text="请输入已翻译的德语商详：")
input_label.pack(anchor="w", padx=10, pady=(10, 3))

text_box = scrolledtext.ScrolledText(root, width=70, height=15, font=("微软雅黑", 10), wrap=tk.WORD)
text_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

# 2. 功能函数
def build_review_prompt():
    original = text_box.get("1.0", tk.END).strip()
    if not original:
        return
    suffix = (
        "这是一个商品的商详，是机器翻译的结果，在不改变原来框架结构和行文内容的基础上，我需要你从两个维度检查，语言维度和商详维度，最后润色到如同德语母语者说的。\n\n"
        "（1）语言层面：从德语母语者视角出发，审视是否有语法错误，是否有不准确不地道的搭配，是否有不合适的词汇，是否有中文乱码英文乱码，是否有错误的拼写等其他语言上不恰当需要润色的地方；\n\n"
        "（2）商详维度，根据你的经验，不同类目的商详文字特点，3C Beauty等等类目标品的商详内容。帮我检查这段德语商详写得怎么样，有没有润色的地方，要求内容表达和框架结构上上不要修改，只润色语言。\n\n"
        "不用输出思考和分析过程，只写给出润色后的德语结果，只有副标题加粗，副标题前不要有123序列号。"
    )
    full_prompt = original + "\n\n" + suffix
    pyperclip.copy(full_prompt)


def build_dictionary():
    dict_lines = [
        "产品描述, Product description, 1.Produktbeschreibung, Produktbeschreibung, Kurzbeschreibung,",
    ]
    # 添加 2~15 行的空格占位
    for i in range(2, 16):
        dict_lines.append(f"{i}. ")
    result = "\n".join(dict_lines)
    pyperclip.copy(result)
    # 清空输入框
    text_box.delete("1.0", tk.END)

# 3. 按钮
btn_frame = ttk.Frame(root)
btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

prompt_btn = ttk.Button(btn_frame, text="生成润色请求并复制", command=build_review_prompt)
prompt_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

dict_btn = ttk.Button(btn_frame, text="生成词典并复制/清空输入", command=build_dictionary)
dict_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

root.mainloop()