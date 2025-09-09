# 德国站商详批量打开和Joybuy前端页面批量审阅工具

这是一个用于管理德国电商平台产品SKU和SPU的批量操作工具，支持自动化打开产品编辑页面和前端商品页面。

## 功能特性

### 1. 支配型SPU处理
- **功能**: 1个SPU支配多个SKU，需要高亮特定SKU来定位编辑按钮
- **处理方式**: 分批处理（每批最多10个），自动检索和高亮SKU
- **示例**: iPad mini 2024 256GB Wi-Fi and Cel.

### 2. 非支配型SPU处理
- **功能**: 1个SPU单独对应1个SKU，直接打开页面即可
- **处理方式**: 批量一次性打开所有页面
- **示例**: Logitech G29 Gaming Driving Force racing wheel

### 3. 前端商品页面审阅
- **功能**: 批量打开Joybuy前端商品页面进行审阅
- **URL格式**: https://www.joybuy.de/dp/{SKU}

## 安装依赖

```bash
pip install -r requirements.txt
```

## 数据文件要求

工具需要以下Excel文件（放在脚本同目录下）：

1. **重复SPU_结果.xlsx** - 包含支配型SPU列表
   - A列第2行开始：SPU编号（仅数字）

2. **SKU_SPU.xlsx** - SKU到SPU的映射表
   - 首列：SKU编号
   - 次列：SPU编号

## 使用方法

### 1. 启动工具
```bash
python german_product_tool.py
```

### 2. 操作流程
1. 在"商详查询-SKU列表"输入框中输入SKU（每行一个，最多50个）
2. 在"前端检索-SKU列表"输入框中输入前端SKU（每行一个，最多50个）
3. 按顺序点击操作按钮：
   - 按钮1：分批打开支配型SPU编辑界面
   - 按钮2：批量打开非支配型SPU编辑界面
   - 按钮3：打开Joybuy前端商品页面

### 3. 注意事项
- 优先处理支配型SPU
- 处理支配型SPU时不要移动鼠标和键盘
- 支持表格数据批量粘贴
- 最多处理50个SKU

## Chrome快捷键

- `End`: 到页面最下方
- `Tab`: 到页面最上方
- `Ctrl+Tab`: 下一页
- `Ctrl+Shift+Tab`: 上一页
- `Ctrl+W`: 关闭页面

## 系统要求

- Python 3.6+
- Google Chrome浏览器
- Windows/macOS/Linux支持

## 技术特性

- 跨平台Chrome启动支持
- 自动窗口识别和激活
- 批量URL生成和打开
- 智能等待时间优化
- 线程化处理避免UI阻塞
- 错误处理和状态提示

## 文件结构

```
├── german_product_tool.py    # 主程序文件
├── requirements.txt          # 依赖包列表
├── README.md                # 说明文档
├── 重复SPU_结果.xlsx        # 支配型SPU数据文件
├── SKU_SPU.xlsx            # SKU-SPU映射文件
└── id_T_HwOLT_1757043427406.ico  # 程序图标（可选）
```