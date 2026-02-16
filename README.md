# PDF 法语翻译工具

一个专门用于翻译大型法语 PDF 文档的 Python 工具。支持 **Web 界面** 和 **命令行** 两种使用方式，提供单模型翻译和多模型智能整合翻译。

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## ✨ 功能特点

### 核心功能
- 📄 **智能文本提取**: 直接从 PDF 提取文本，自动过滤水印和页脚
- ✂️ **智能分段**: 自动将文本分割成适合翻译的段落
- 🔄 **断点续传**: 支持中断后继续翻译，不会重复翻译已完成的内容
- ⚡ **并发翻译**: 支持多线程并发，大幅提升翻译速度
- 📝 **双输出**: 同时生成纯译文和双语对照两个版本

### Web 界面特色
- 🎨 **现代化界面**: 类似 Gemini 的简洁设计，支持深色/浅色主题
- ⚡ **Flash 模式**: 单模型快速翻译
- 🏆 **High Quality 模式**: 多模型翻译 + 智能整合，质量更高
- ✏️ **Editor 模式**: 上传已有译文，AI 对比审校并打磨润色 🆕
- ✏️ **提示词自定义**: 每个模型可以设置独立的翻译提示词
- 📖 **对比阅读**: 左侧原文 PDF，右侧翻译结果，方便校对
- 📜 **翻译历史**: 保存历史记录，支持下载 TXT/MD/PDF

## 📦 安装

### 环境要求

- Python 3.8+
- pip 包管理器

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/your-username/pdf_translate.git
cd pdf_translate

# 2. 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt
```

### 依赖说明

| 包名 | 用途 |
|------|------|
| `pymupdf` | PDF 文本提取和页面渲染 |
| `openai` | OpenAI/OpenRouter API 客户端 |
| `python-dotenv` | 环境变量管理 |
| `tqdm` | 命令行进度条 |
| `flask` | Web 服务框架 |
| `flask-cors` | 跨域请求支持 |
| `reportlab` | PDF 导出功能 |

## ⚙️ 配置

### 创建配置文件

在项目根目录创建 `.env` 文件：

```bash
# OpenRouter API（推荐，支持多种模型）
OPENAI_API_KEY=your_openrouter_api_key
OPENAI_BASE_URL=https://openrouter.ai/api/v1

# 或使用 OpenAI 官方 API
# OPENAI_API_KEY=your_openai_api_key
# OPENAI_BASE_URL=https://api.openai.com/v1

# 或使用 DeepSeek API
# OPENAI_API_KEY=your_deepseek_api_key
# OPENAI_BASE_URL=https://api.deepseek.com/v1
```

### 推荐模型

**通过 OpenRouter 使用（推荐）：**

| 模型 | OpenRouter 模型名 | 特点 |
|------|------------------|------|
| Grok 4.1 Fast | `x-ai/grok-4.1-fast` | ⚡ 快速，性价比高 |
| DeepSeek V3 | `deepseek/deepseek-chat` | 💰 最便宜，中文好 |
| Claude Sonnet 4 | `anthropic/claude-sonnet-4` | 🏆 质量最好 |
| Gemini 2.5 Flash | `google/gemini-2.5-flash-preview` | ⚡ 快速，免费额度 |
| GPT-4o | `openai/gpt-4o` | 📚 稳定可靠 |

## 🚀 使用方法

### 方式一：Web 界面（推荐）

```bash
# 启动服务器
python3 server.py
```

启动后访问：**http://localhost:5000**

#### Web 界面使用流程

1. **上传 PDF**: 点击上传区域或拖拽文件
2. **选择翻译模式**:
   - **Flash**: 单模型翻译，速度快
   - **High Quality**: 多模型翻译后整合，质量更高
3. **配置选项**:
   - 选择翻译模型
   - 设置页面范围（可选）
   - 调整并发数（默认 10）
   - 自定义翻译提示词（可选）
4. **开始翻译**: 实时显示进度
5. **查看结果**: 
   - 对比阅读模式
   - 下载 TXT/MD/PDF 格式

#### 多模型翻译说明

High Quality 模式下：
- 可添加多个翻译模型（默认 3 个）
- **每个模型可以设置独立的提示词**
- 整合模型会综合各版本优点，输出最优翻译
- 自动修正格式问题和残留水印

#### Editor 编辑模式说明 🆕

Editor 模式适用于已有自己翻译稿的用户：

1. **同时上传两个文件**：
   - PDF 原文（法语）
   - Word 译文（你自己的翻译稿 .docx）

2. **AI 智能处理**：
   - 自动对齐原文与译文段落
   - 调用多个 AI 模型独立翻译
   - 编辑模型作为"严厉的编辑"角色，对比评审

3. **输出内容**：
   - 最终打磨后的译文
   - 详细的评审报告（指出问题和改进点）
   - 完整的多版本对照

4. **编辑原则**：
   - 忠实原文，不擅自增删
   - 尊重作者，保留用户译文的优秀表达
   - 取长补短，综合各版本优点
   - 精益求精，每个词语都反复推敲

### 方式二：命令行

```bash
# 翻译整本 PDF
python pdf_translator.py your_book.pdf

# 翻译指定页面范围
python pdf_translator.py your_book.pdf --start 1 --end 10

# 使用指定模型
python pdf_translator.py book.pdf --model deepseek/deepseek-chat

# 设置并发数
python pdf_translator.py book.pdf --workers 5

# 完整参数示例
python pdf_translator.py book.pdf \
  --start 1 \
  --end 100 \
  --model x-ai/grok-4.1-fast \
  --workers 10 \
  --output my_translations
```

#### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `pdf_path` | PDF 文件路径 | 必需 |
| `--start` | 起始页码 | 1 |
| `--end` | 结束页码 | 最后一页 |
| `--model` | 使用的模型 | gpt-4o-mini |
| `--workers` | 并发数 | 5 |
| `--max-chars` | 每段最大字符数 | 2000 |
| `--output` | 输出目录 | output |
| `--api-key` | API 密钥 | 从 .env 读取 |
| `--base-url` | API 基础 URL | 从 .env 读取 |

## 📁 项目结构

```
pdf_translate/
├── server.py              # Flask Web 服务
├── pdf_translator.py      # 命令行翻译工具
├── multi_model_translator.py  # 多模型翻译器
├── requirements.txt       # Python 依赖
├── .env                   # 环境变量配置（需自行创建）
├── web/                   # Web 前端文件
│   ├── index.html
│   ├── style.css
│   └── app.js
├── uploads/               # 上传的 PDF 文件
└── output/                # 翻译输出文件
```

## 📤 输出文件

翻译完成后，会在 `output` 目录生成：

| 文件 | 说明 |
|------|------|
| `{书名}_translated_{模型名}.txt` | 纯中文译文 |
| `{书名}_bilingual_{模型名}.txt` | 法中双语对照 |
| `{书名}_progress_{模型名}.json` | 翻译进度（用于断点续传） |

## 💰 费用估算

对于 600 页的 PDF（假设每页约 500 词）：

| 模型 | 预估费用 |
|------|---------|
| DeepSeek V3 | ¥5-10 |
| Grok 4.1 Fast | $2-5 |
| GPT-4o-mini | $3-5 |
| Claude Sonnet 4 | $15-25 |
| GPT-4o | $30-50 |

**建议**: 先用 `--start 1 --end 5` 测试 5 页效果，确认满意后再翻译全书。

## ❓ 常见问题

### Q: PDF 无法提取文本怎么办？

如果 PDF 是扫描版（图片），需要先进行 OCR：
- Adobe Acrobat 的 OCR 功能
- 在线 OCR 工具（如 smallpdf.com）
- 本地 OCR 工具（如 Tesseract）

### Q: 翻译速度太慢？

1. 增加 `--workers` 并发数（注意 API 限流）
2. 使用更快的模型（如 Grok 4.1 Fast）
3. 增大 `--max-chars` 减少 API 调用次数

### Q: 如何使用国内 API？

DeepSeek 示例：
```bash
# .env 配置
OPENAI_API_KEY=your_deepseek_key
OPENAI_BASE_URL=https://api.deepseek.com/v1
```

### Q: 断点续传如何工作？

程序会自动保存进度到 `output/{书名}_progress.json`。下次运行相同命令时，会自动跳过已完成的段落。

如需重新翻译，删除对应的 `_progress.json` 文件即可。

## 🔧 开发

```bash
# 安装开发依赖
pip install -r requirements.txt

# 启动开发服务器（自动重载）
python3 server.py
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
