# 编辑功能（Editor Mode）开发文档

## 1. 功能概述

### 1.1 需求描述

用户已有一份自己翻译的 Word 文档，希望系统能够：
1. 读取用户的 Word 译文
2. 与 PDF 原文进行段落级对齐匹配
3. 调用多个大模型，一边独立翻译，一边对比用户译文
4. 作为"严厉的编辑"角色，评审并打磨用户的译文
5. 输出一个超越原有译文的最终版本

### 1.2 核心价值

- **译者视角**：系统独立翻译，提供参考译文
- **编辑视角**：评审用户译文，指出问题并提出修改建议
- **整合视角**：综合各方优点，输出最优版本

### 1.3 与现有功能的关系

```
                    ┌─────────────────────────────────────┐
                    │         PDF 翻译工具                │
                    └─────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
    ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
    │  Flash Mode   │      │ High Quality  │      │  Editor Mode  │
    │   单模型翻译   │      │  多模型翻译    │      │  编辑打磨模式  │ ← 新功能
    └───────────────┘      └───────────────┘      └───────────────┘
```

---

## 2. 系统架构设计

### 2.1 模块结构

```
pdf_translate/
├── server.py                    # Flask 服务（新增编辑相关路由）
├── editor_service.py            # 【新增】编辑服务核心模块
├── word_processor.py            # 【新增】Word 文档处理模块
├── text_aligner.py              # 【新增】文本对齐匹配模块
├── multi_model_translator.py    # 现有多模型翻译器（复用）
├── pdf_translator.py            # 现有PDF处理器（复用）
└── web/
    ├── index.html               # 前端主页（新增编辑模式tab）
    ├── editor.html              # 【新增】编辑模式页面
    ├── style.css                # 样式（新增编辑相关样式）
    └── app.js                   # 前端逻辑（新增编辑功能）
```

### 2.2 数据流程图

```
                              ┌──────────────────┐
                              │   用户上传文件    │
                              └────────┬─────────┘
                                       │
                      ┌────────────────┴────────────────┐
                      │                                 │
                      ▼                                 ▼
              ┌──────────────┐                 ┌──────────────┐
              │   PDF 原文    │                 │  Word 译文   │
              └──────┬───────┘                 └──────┬───────┘
                     │                                │
                     ▼                                ▼
              ┌──────────────┐                 ┌──────────────┐
              │  文本提取     │                 │  文本提取     │
              │ (按页/段落)   │                 │ (按段落)      │
              └──────┬───────┘                 └──────┬───────┘
                     │                                │
                     └────────────┬───────────────────┘
                                  │
                                  ▼
                         ┌──────────────┐
                         │   段落对齐    │
                         │ Text Aligner │
                         └──────┬───────┘
                                │
                                ▼
              ┌─────────────────────────────────────┐
              │        对齐后的段落对               │
              │  [(原文1, 译文1), (原文2, 译文2)..] │
              └─────────────────┬───────────────────┘
                                │
                                ▼
        ┌───────────────────────┴───────────────────────┐
        │                                               │
        │              并发处理每个段落                  │
        │                                               │
        │  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
        │  │ Model A │  │ Model B │  │ Model C │       │
        │  │ 翻译版本 │  │ 翻译版本 │  │ 翻译版本 │       │
        │  └────┬────┘  └────┬────┘  └────┬────┘       │
        │       │            │            │            │
        │       └────────────┼────────────┘            │
        │                    │                         │
        │                    ▼                         │
        │           ┌────────────────┐                 │
        │           │   编辑整合模型  │                 │
        │           │                │                 │
        │           │ 输入：          │                 │
        │           │ - 原文          │                 │
        │           │ - 用户译文      │                 │
        │           │ - 多个AI译文    │                 │
        │           │                │                 │
        │           │ 输出：          │                 │
        │           │ - 评审分析      │                 │
        │           │ - 最终译文      │                 │
        │           └────────┬───────┘                 │
        │                    │                         │
        └────────────────────┼─────────────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │    输出结果       │
                    │ - 最终打磨译文    │
                    │ - 评审报告        │
                    │ - 修改追踪        │
                    └──────────────────┘
```

---

## 3. 核心模块设计

### 3.1 Word 文档处理模块 (`word_processor.py`)

```python
"""
Word 文档处理模块
功能：读取、解析 Word 文档，提取段落文本
"""

from pathlib import Path
from docx import Document
from typing import List, Dict

class WordProcessor:
    """Word 文档处理器"""
    
    def __init__(self):
        pass
    
    def extract_paragraphs(self, docx_path: str) -> List[Dict]:
        """
        从 Word 文档提取段落
        
        Args:
            docx_path: Word 文件路径
            
        Returns:
            段落列表 [{"index": 0, "text": "...", "style": "Normal"}]
        """
        doc = Document(docx_path)
        paragraphs = []
        
        for i, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if text:  # 忽略空段落
                paragraphs.append({
                    "index": i,
                    "text": text,
                    "style": para.style.name if para.style else "Normal",
                    "is_heading": para.style and "Heading" in para.style.name
                })
        
        return paragraphs
    
    def extract_with_formatting(self, docx_path: str) -> List[Dict]:
        """
        提取段落，保留更多格式信息（用于精确匹配）
        """
        doc = Document(docx_path)
        paragraphs = []
        
        for i, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if not text:
                continue
            
            # 检测格式特征
            is_bold = any(run.bold for run in para.runs if run.bold)
            is_italic = any(run.italic for run in para.runs if run.italic)
            
            paragraphs.append({
                "index": i,
                "text": text,
                "style": para.style.name if para.style else "Normal",
                "is_heading": para.style and "Heading" in para.style.name,
                "is_bold": is_bold,
                "is_italic": is_italic,
                "char_count": len(text)
            })
        
        return paragraphs


# 支持的文件格式
SUPPORTED_FORMATS = ['.docx', '.doc']

def is_supported_word_file(filepath: str) -> bool:
    """检查是否为支持的 Word 文件格式"""
    return Path(filepath).suffix.lower() in SUPPORTED_FORMATS
```

### 3.2 文本对齐模块 (`text_aligner.py`)

```python
"""
文本对齐模块
功能：将 PDF 原文段落与 Word 译文段落进行对齐匹配
"""

import re
from typing import List, Dict, Tuple
from difflib import SequenceMatcher

class TextAligner:
    """文本段落对齐器"""
    
    def __init__(self, similarity_threshold: float = 0.3):
        """
        Args:
            similarity_threshold: 相似度阈值，低于此值认为不匹配
        """
        self.similarity_threshold = similarity_threshold
    
    def align_paragraphs(
        self, 
        source_paragraphs: List[Dict],  # PDF 原文段落
        target_paragraphs: List[Dict]   # Word 译文段落
    ) -> List[Dict]:
        """
        对齐原文段落和译文段落
        
        策略：
        1. 按顺序匹配（假设译文顺序与原文一致）
        2. 通过段落长度比例进行辅助匹配
        3. 标记无法匹配的段落
        
        Returns:
            对齐结果列表 [{
                "source_index": 0,
                "target_index": 0,
                "source_text": "原文...",
                "target_text": "译文...",
                "confidence": 0.85,
                "page": 1
            }]
        """
        aligned = []
        target_idx = 0
        
        for src_para in source_paragraphs:
            src_text = src_para.get("text", "")
            src_page = src_para.get("page", 1)
            src_idx = src_para.get("index", len(aligned))
            
            best_match = None
            best_confidence = 0
            
            # 在当前位置附近搜索最佳匹配
            search_range = range(
                max(0, target_idx - 2),
                min(len(target_paragraphs), target_idx + 5)
            )
            
            for t_idx in search_range:
                if t_idx >= len(target_paragraphs):
                    break
                    
                tgt_para = target_paragraphs[t_idx]
                tgt_text = tgt_para.get("text", "")
                
                # 计算匹配置信度
                confidence = self._calculate_match_confidence(src_text, tgt_text)
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = {
                        "target_index": t_idx,
                        "target_text": tgt_text
                    }
            
            # 记录对齐结果
            if best_match and best_confidence >= self.similarity_threshold:
                aligned.append({
                    "source_index": src_idx,
                    "target_index": best_match["target_index"],
                    "source_text": src_text,
                    "target_text": best_match["target_text"],
                    "confidence": best_confidence,
                    "page": src_page,
                    "matched": True
                })
                target_idx = best_match["target_index"] + 1
            else:
                # 无法匹配，标记为仅有原文
                aligned.append({
                    "source_index": src_idx,
                    "target_index": None,
                    "source_text": src_text,
                    "target_text": None,
                    "confidence": 0,
                    "page": src_page,
                    "matched": False
                })
        
        return aligned
    
    def _calculate_match_confidence(self, source: str, target: str) -> float:
        """
        计算源文本和目标文本的匹配置信度
        
        考虑因素：
        1. 长度比例（译文通常比原文短30%-50%）
        2. 段落位置（假设顺序一致）
        3. 特殊标记（如数字、专有名词）
        """
        if not source or not target:
            return 0.0
        
        # 1. 长度比例分数
        src_len = len(source)
        tgt_len = len(target)
        
        # 法译中的合理长度比例：0.3 - 0.8
        ratio = tgt_len / src_len if src_len > 0 else 0
        length_score = 1.0 if 0.3 <= ratio <= 0.9 else max(0, 1 - abs(ratio - 0.6))
        
        # 2. 数字匹配分数
        src_numbers = set(re.findall(r'\d+', source))
        tgt_numbers = set(re.findall(r'\d+', target))
        if src_numbers:
            number_score = len(src_numbers & tgt_numbers) / len(src_numbers)
        else:
            number_score = 1.0
        
        # 3. 标点密度匹配（段落结构相似性）
        src_punct = len(re.findall(r'[.,;:!?]', source))
        tgt_punct = len(re.findall(r'[，。；：！？]', target))
        punct_ratio = min(src_punct, tgt_punct) / max(src_punct, tgt_punct, 1)
        punct_score = punct_ratio if punct_ratio > 0.3 else 0.5
        
        # 综合得分
        confidence = (length_score * 0.4 + number_score * 0.4 + punct_score * 0.2)
        
        return confidence
    
    def merge_short_paragraphs(
        self, 
        paragraphs: List[Dict], 
        min_length: int = 50
    ) -> List[Dict]:
        """
        合并过短的段落（可能是被错误分割的）
        """
        merged = []
        buffer = None
        
        for para in paragraphs:
            if buffer is None:
                buffer = para.copy()
            elif len(buffer["text"]) < min_length:
                # 合并到 buffer
                buffer["text"] += "\n" + para["text"]
            else:
                merged.append(buffer)
                buffer = para.copy()
        
        if buffer:
            merged.append(buffer)
        
        return merged
```

### 3.3 编辑服务核心模块 (`editor_service.py`)

```python
"""
编辑服务核心模块
功能：整合翻译与编辑审校功能，打磨用户译文
"""

import os
import json
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from openai import OpenAI
from dotenv import load_dotenv

from word_processor import WordProcessor
from text_aligner import TextAligner
from multi_model_translator import MultiModelTranslator

load_dotenv()


class EditorService:
    """编辑服务 - 对比、评审、打磨译文"""
    
    # 编辑审校默认提示词
    DEFAULT_EDITOR_PROMPT = """你是一位资深的翻译编辑，同时精通法语和中文，拥有丰富的出版编辑经验。

你将收到：
1. 法语原文
2. 用户自己的中文译文（初稿）
3. 多个 AI 模型的翻译版本

## 你的角色

你同时担任两个角色：

### 角色1：翻译者
- 独立理解原文，判断各译文的准确性
- 识别翻译中的错误（漏译、误译、过译）

### 角色2：严厉的编辑
- 以出版标准审视译文质量
- 检查术语准确性、行文流畅度、风格一致性
- 给出具体的修改建议

## 输出格式（严格遵守）

```
[评审意见]
对用户译文的简要评价：
- 优点：（1-2 句）
- 问题：（列出主要问题）
- 参考价值：说明从 AI 译文中借鉴了什么

[最终译文]
打磨后的最佳译文
```

## 编辑原则

1. **忠实原文**：不得擅自增删内容
2. **尊重作者**：保留用户译文的优秀表达
3. **取长补短**：综合各版本优点
4. **精益求精**：每个词语都要反复推敲
5. **术语一致**：保持专业术语翻译的一致性
"""

    # 翻译对比提示词
    TRANSLATION_COMPARE_PROMPT = """你是一位精通法语和中文的专业翻译官。
请将以下法语文本翻译为中文。

要求：
1. 准确传达原意，语言流畅自然
2. 保持学术性/文学性风格
3. 专业术语后可加括号标注原文
4. 直接返回译文，不要解释
"""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        translation_models: List[str] = None,
        editor_model: str = None,
        editor_prompt: str = None,
        translation_prompts: List[str] = None,
        output_dir: str = "output"
    ):
        """
        初始化编辑服务
        
        Args:
            api_key: API 密钥
            base_url: API 基础 URL
            translation_models: 用于对比翻译的模型列表
            editor_model: 用于编辑审校的模型
            editor_prompt: 自定义编辑提示词
            translation_prompts: 每个翻译模型的提示词
            output_dir: 输出目录
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        
        self.translation_models = translation_models or [
            "x-ai/grok-4.1-fast",
            "anthropic/claude-sonnet-4",
            "deepseek/deepseek-chat"
        ]
        self.editor_model = editor_model or "anthropic/claude-sonnet-4"
        
        self.editor_prompt = editor_prompt or self.DEFAULT_EDITOR_PROMPT
        self.translation_prompts = translation_prompts or \
            [self.TRANSLATION_COMPARE_PROMPT] * len(self.translation_models)
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 初始化 API 客户端
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = OpenAI(**client_kwargs)
        
        # 初始化子模块
        self.word_processor = WordProcessor()
        self.text_aligner = TextAligner()
    
    def _call_model(
        self, 
        model: str, 
        system_prompt: str, 
        user_content: str,
        max_retries: int = 3
    ) -> str:
        """调用模型 API"""
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.3,
                    max_tokens=4000
                )
                result = response.choices[0].message.content
                if result and result.strip():
                    return result.strip()
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise e
        return ""

    def translate_for_comparison(self, source_text: str) -> Dict[str, str]:
        """
        调用多个模型翻译，用于对比
        
        Returns:
            {model_name: translation}
        """
        translations = {}
        
        with ThreadPoolExecutor(max_workers=len(self.translation_models)) as executor:
            futures = {}
            for idx, model in enumerate(self.translation_models):
                prompt = self.translation_prompts[idx] if idx < len(self.translation_prompts) \
                    else self.TRANSLATION_COMPARE_PROMPT
                future = executor.submit(
                    self._call_model, 
                    model, 
                    prompt, 
                    f"请翻译：\n\n{source_text}"
                )
                futures[future] = f"{idx+1}_{model}"
            
            for future in as_completed(futures):
                key = futures[future]
                try:
                    translations[key] = future.result()
                except Exception as e:
                    translations[key] = f"[翻译失败: {str(e)}]"
        
        return translations
    
    def edit_paragraph(
        self, 
        source_text: str,           # 原文
        user_translation: str,      # 用户译文
        ai_translations: Dict[str, str] = None  # AI 对比译文（可选）
    ) -> Dict:
        """
        编辑审校单个段落
        
        Args:
            source_text: 法语原文
            user_translation: 用户的译文
            ai_translations: AI 翻译版本（可选，若无则调用获取）
            
        Returns:
            {
                "review": "评审意见",
                "final": "最终译文",
                "ai_translations": {...}
            }
        """
        # 如果没有 AI 译文，先获取
        if ai_translations is None:
            ai_translations = self.translate_for_comparison(source_text)
        
        # 构建编辑请求
        user_content = f"""## 法语原文

{source_text}

## 用户译文（待审校）

{user_translation}

## AI 参考译文

"""
        for model, trans in sorted(ai_translations.items()):
            model_short = model.split("/")[-1] if "/" in model else model
            user_content += f"### {model_short}\n{trans}\n\n"
        
        user_content += "## 请按格式输出评审意见和最终译文"
        
        # 调用编辑模型
        result = self._call_model(self.editor_model, self.editor_prompt, user_content)
        
        # 解析结果
        review = ""
        final_text = result
        
        if "[评审意见]" in result and "[最终译文]" in result:
            parts = result.split("[最终译文]")
            if len(parts) == 2:
                review = parts[0].replace("[评审意见]", "").strip()
                final_text = parts[1].strip()
        
        return {
            "source": source_text,
            "user_translation": user_translation,
            "ai_translations": ai_translations,
            "review": review,
            "final": final_text
        }
    
    def process_document(
        self,
        pdf_path: str,
        word_path: str,
        start_page: int = None,
        end_page: int = None,
        max_workers: int = 5,
        progress_callback = None
    ) -> Dict:
        """
        处理完整文档：对齐、翻译、编辑
        
        Args:
            pdf_path: PDF 原文路径
            word_path: Word 译文路径
            start_page: 起始页码
            end_page: 结束页码
            max_workers: 并发数
            progress_callback: 进度回调函数
            
        Returns:
            处理结果
        """
        results = {
            "paragraphs": [],
            "stats": {
                "total": 0,
                "matched": 0,
                "edited": 0
            }
        }
        
        # 1. 提取 PDF 原文
        from pdf_translator import PDFTranslator
        pdf_helper = PDFTranslator(api_key="dummy")
        pdf_pages = pdf_helper.extract_text_from_pdf(pdf_path)
        
        # 筛选页面范围
        if start_page or end_page:
            pdf_pages = [
                p for p in pdf_pages
                if (start_page is None or p["page"] >= start_page) and
                   (end_page is None or p["page"] <= end_page)
            ]
        
        # 转换为段落列表
        pdf_paragraphs = []
        for page_data in pdf_pages:
            page_num = page_data["page"]
            text = page_data["text"]
            # 按段落分割
            for para in text.split("\n\n"):
                para = para.strip()
                if para:
                    pdf_paragraphs.append({
                        "page": page_num,
                        "text": para,
                        "index": len(pdf_paragraphs)
                    })
        
        # 2. 提取 Word 译文
        word_paragraphs = self.word_processor.extract_paragraphs(word_path)
        
        # 3. 对齐段落
        aligned = self.text_aligner.align_paragraphs(pdf_paragraphs, word_paragraphs)
        
        results["stats"]["total"] = len(aligned)
        results["stats"]["matched"] = sum(1 for a in aligned if a["matched"])
        
        # 4. 并发处理每个段落
        lock = threading.Lock()
        processed = 0
        
        def process_paragraph(item):
            nonlocal processed
            
            source_text = item["source_text"]
            user_trans = item["target_text"] if item["matched"] else None
            
            if user_trans:
                # 有用户译文，进行编辑审校
                edit_result = self.edit_paragraph(source_text, user_trans)
                result = {
                    **item,
                    "ai_translations": edit_result["ai_translations"],
                    "review": edit_result["review"],
                    "final": edit_result["final"],
                    "edited": True
                }
            else:
                # 无用户译文，仅翻译
                ai_trans = self.translate_for_comparison(source_text)
                # 使用整合模型生成最终版本
                best_trans = list(ai_trans.values())[0] if ai_trans else source_text
                result = {
                    **item,
                    "ai_translations": ai_trans,
                    "review": "[无对应用户译文，使用 AI 翻译]",
                    "final": best_trans,
                    "edited": False
                }
            
            with lock:
                processed += 1
                if progress_callback:
                    progress_callback(processed, len(aligned))
            
            return result
        
        # 并发处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_paragraph, item) for item in aligned]
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results["paragraphs"].append(result)
                    if result.get("edited"):
                        results["stats"]["edited"] += 1
                except Exception as e:
                    print(f"处理段落失败: {e}")
        
        # 按页码和索引排序
        results["paragraphs"].sort(key=lambda x: (x.get("page", 0), x.get("source_index", 0)))
        
        return results
    
    def generate_output_files(self, results: Dict, base_name: str) -> Dict[str, str]:
        """
        生成输出文件
        
        Returns:
            {"final": path, "review": path, "comparison": path}
        """
        output_files = {}
        
        # 1. 最终译文
        final_file = self.output_dir / f"{base_name}_edited_final.txt"
        with open(final_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("  编辑打磨后的最终译文\n")
            f.write("=" * 60 + "\n\n")
            
            current_page = None
            for para in results["paragraphs"]:
                page = para.get("page", 0)
                if page != current_page:
                    f.write(f"\n【第 {page} 页】\n\n")
                    current_page = page
                
                f.write(para.get("final", "") + "\n\n")
        
        output_files["final"] = str(final_file)
        
        # 2. 评审报告
        review_file = self.output_dir / f"{base_name}_edit_review.txt"
        with open(review_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("  编辑审校报告\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"总段落数: {results['stats']['total']}\n")
            f.write(f"成功匹配: {results['stats']['matched']}\n")
            f.write(f"完成编辑: {results['stats']['edited']}\n\n")
            f.write("-" * 60 + "\n\n")
            
            for i, para in enumerate(results["paragraphs"], 1):
                f.write(f"【段落 {i}】第 {para.get('page', 0)} 页\n\n")
                f.write(f"原文: {para.get('source_text', '')[:100]}...\n\n")
                
                if para.get("target_text"):
                    f.write(f"用户译文: {para.get('target_text', '')[:100]}...\n\n")
                
                f.write(f"评审意见:\n{para.get('review', '')}\n\n")
                f.write("-" * 40 + "\n\n")
        
        output_files["review"] = str(review_file)
        
        # 3. 完整对照
        comparison_file = self.output_dir / f"{base_name}_full_comparison.txt"
        with open(comparison_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("  完整翻译对照\n")
            f.write("=" * 60 + "\n\n")
            
            for i, para in enumerate(results["paragraphs"], 1):
                f.write(f"╔{'═' * 56}╗\n")
                f.write(f"║ 段落 {i} - 第 {para.get('page', 0)} 页\n")
                f.write(f"╚{'═' * 56}╝\n\n")
                
                f.write("【原文】\n")
                f.write(para.get("source_text", "") + "\n\n")
                
                if para.get("target_text"):
                    f.write("【用户译文】\n")
                    f.write(para.get("target_text", "") + "\n\n")
                
                f.write("【AI 参考译文】\n")
                for model, trans in para.get("ai_translations", {}).items():
                    model_short = model.split("/")[-1] if "/" in model else model
                    f.write(f"- {model_short}:\n{trans}\n\n")
                
                f.write("【评审意见】\n")
                f.write(para.get("review", "") + "\n\n")
                
                f.write("【最终译文】\n")
                f.write(para.get("final", "") + "\n\n")
                
                f.write("=" * 60 + "\n\n")
        
        output_files["comparison"] = str(comparison_file)
        
        return output_files
```

---

## 4. API 路由设计

### 4.1 新增 API 端点

在 `server.py` 中新增以下路由：

```python
# ============================================
# Editor Mode Routes
# ============================================

@app.route('/api/editor/upload-word', methods=['POST'])
def upload_word():
    """上传 Word 译文文件"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    if not file.filename.lower().endswith(('.docx', '.doc')):
        return jsonify({'error': '只支持 Word 文件 (.docx, .doc)'}), 400
    
    import uuid
    file_id = str(uuid.uuid4())[:8]
    filename = f"{file_id}_{file.filename}"
    filepath = UPLOAD_FOLDER / filename
    file.save(filepath)
    
    # 提取段落数
    try:
        from word_processor import WordProcessor
        processor = WordProcessor()
        paragraphs = processor.extract_paragraphs(str(filepath))
        para_count = len(paragraphs)
    except Exception as e:
        return jsonify({'error': f'无法读取 Word 文件: {str(e)}'}), 400
    
    return jsonify({
        'file_id': file_id,
        'filename': file.filename,
        'path': str(filepath),
        'paragraph_count': para_count
    })


@app.route('/api/editor/start', methods=['POST'])
def start_editor_task():
    """开始编辑任务"""
    data = request.json
    
    pdf_path = data.get('pdf_path')
    word_path = data.get('word_path')
    
    if not pdf_path or not word_path:
        return jsonify({'error': '缺少 PDF 或 Word 文件路径'}), 400
    
    import uuid
    task_id = str(uuid.uuid4())[:8]
    
    translation_tasks[task_id] = {
        'id': task_id,
        'type': 'editor',
        'status': 'pending',
        'progress': 0,
        'total_paragraphs': 0,
        'completed_paragraphs': 0,
        'results': None,
        'error': None,
        'created_at': datetime.now().isoformat()
    }
    
    # 后台线程运行
    thread = threading.Thread(
        target=run_editor_task,
        args=(task_id, pdf_path, word_path, data)
    )
    thread.start()
    
    return jsonify({'task_id': task_id})


def run_editor_task(task_id: str, pdf_path: str, word_path: str, config: dict):
    """运行编辑任务"""
    try:
        task = translation_tasks[task_id]
        task['status'] = 'processing'
        
        from editor_service import EditorService
        
        editor = EditorService(
            translation_models=config.get('translation_models'),
            editor_model=config.get('editor_model'),
            editor_prompt=config.get('editor_prompt'),
            translation_prompts=config.get('translation_prompts')
        )
        
        def progress_callback(completed, total):
            task['completed_paragraphs'] = completed
            task['total_paragraphs'] = total
            task['progress'] = int(completed / total * 100) if total > 0 else 0
        
        results = editor.process_document(
            pdf_path=pdf_path,
            word_path=word_path,
            start_page=config.get('start_page'),
            end_page=config.get('end_page'),
            max_workers=config.get('workers', 5),
            progress_callback=progress_callback
        )
        
        # 生成输出文件
        from pathlib import Path
        base_name = Path(pdf_path).stem
        output_files = editor.generate_output_files(results, base_name)
        
        task['results'] = results
        task['output_files'] = output_files
        task['status'] = 'completed'
        task['completed_at'] = datetime.now().isoformat()
        
    except Exception as e:
        task = translation_tasks[task_id]
        task['status'] = 'error'
        task['error'] = str(e)
        import traceback
        traceback.print_exc()
```

---

## 5. 前端界面设计

### 5.1 编辑模式页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  PDF 翻译工具                    [Flash] [High] [Editor]    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │                     │  │                     │          │
│  │   上传 PDF 原文      │  │   上传 Word 译文    │          │
│  │      📄             │  │      📝            │          │
│  │                     │  │                     │          │
│  └─────────────────────┘  └─────────────────────┘          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  配置选项                                            │   │
│  │                                                      │   │
│  │  翻译模型:  [+ 添加模型]                             │   │
│  │    ┌────────────────┐  ┌────────────────┐           │   │
│  │    │ grok-4.1-fast  │  │ claude-sonnet  │  [删除]   │   │
│  │    │ [编辑提示词]    │  │ [编辑提示词]    │           │   │
│  │    └────────────────┘  └────────────────┘           │   │
│  │                                                      │   │
│  │  编辑模型:  [claude-sonnet-4 ▼]                      │   │
│  │    [编辑审校提示词]                                   │   │
│  │                                                      │   │
│  │  页面范围:  [1] - [全部]    并发数: [5]              │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│              [开始编辑打磨]                                  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  进度: ████████████░░░░░░░░ 65%  (26/40 段落)              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────┬───────────────────────┐         │
│  │      原文 & 用户译文    │     编辑结果          │         │
│  ├───────────────────────┼───────────────────────┤         │
│  │                       │                       │         │
│  │  【原文】              │  【评审意见】          │         │
│  │  Il est important...  │  用户译文整体准确...   │         │
│  │                       │                       │         │
│  │  【用户译文】          │  【最终译文】          │         │
│  │  重要的是...          │  重要的是要理解...    │         │
│  │                       │                       │         │
│  └───────────────────────┴───────────────────────┘         │
│                                                             │
│  [下载最终译文] [下载评审报告] [下载完整对照]                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 前端交互流程

```
1. 用户选择 "Editor" 模式
           │
           ▼
2. 上传 PDF 原文 & Word 译文
           │
           ▼
3. 配置翻译模型和编辑模型
   - 可添加/删除翻译模型
   - 每个模型可设置独立提示词
   - 可自定义编辑审校提示词
           │
           ▼
4. 点击 "开始编辑打磨"
           │
           ▼
5. 实时显示进度
   - 当前处理段落
   - 进度百分比
           │
           ▼
6. 完成后显示结果
   - 左侧：原文 + 用户译文
   - 右侧：评审意见 + 最终译文
   - 可翻页查看每个段落
           │
           ▼
7. 下载输出文件
   - 最终译文 (TXT/MD/PDF)
   - 评审报告
   - 完整对照
```

---

## 6. 提示词配置

### 6.1 翻译对比提示词（可自定义）

```
你是一位精通法语和中文的专业翻译官。
请将以下法语文本翻译为中文。

要求：
1. 准确传达原意，语言流畅自然
2. 保持学术性/文学性风格
3. 专业术语后可加括号标注原文
4. 直接返回译文，不要解释
```

### 6.2 编辑审校提示词（可自定义）

```
你是一位资深的翻译编辑，同时精通法语和中文，拥有丰富的出版编辑经验。

你将收到：
1. 法语原文
2. 用户自己的中文译文（初稿）
3. 多个 AI 模型的翻译版本

## 你的角色

### 角色1：翻译者
- 独立理解原文，判断各译文的准确性
- 识别翻译中的错误（漏译、误译、过译）

### 角色2：严厉的编辑
- 以出版标准审视译文质量
- 检查术语准确性、行文流畅度、风格一致性
- 给出具体的修改建议

## 输出格式

[评审意见]
对用户译文的简要评价：
- 优点：（1-2 句）
- 问题：（列出主要问题）
- 参考价值：说明从 AI 译文中借鉴了什么

[最终译文]
打磨后的最佳译文

## 编辑原则

1. 忠实原文：不得擅自增删内容
2. 尊重作者：保留用户译文的优秀表达
3. 取长补短：综合各版本优点
4. 精益求精：每个词语都要反复推敲
5. 术语一致：保持专业术语翻译的一致性
```

---

## 7. 依赖项

新增以下 Python 包：

```txt
# requirements.txt 新增
python-docx>=0.8.11    # Word 文档处理
```

---

## 8. 开发计划

### Phase 1: 核心模块开发
- [ ] `word_processor.py` - Word 文档解析
- [ ] `text_aligner.py` - 段落对齐算法
- [ ] `editor_service.py` - 编辑服务核心

### Phase 2: 后端集成
- [ ] 新增 API 路由
- [ ] 编辑任务管理
- [ ] 输出文件生成

### Phase 3: 前端开发
- [ ] 编辑模式 UI
- [ ] 文件上传组件
- [ ] 结果展示组件
- [ ] 提示词编辑器

### Phase 4: 测试优化
- [ ] 段落对齐准确性测试
- [ ] 大文档性能优化
- [ ] 用户体验优化

---

## 9. 注意事项

1. **段落对齐是关键**
   - 法译中长度变化大，对齐算法需要调优
   - 建议提供手动调整对齐的功能

2. **保持模块独立**
   - 编辑功能应作为独立模块，不影响现有翻译功能
   - 复用现有的 `multi_model_translator.py`

3. **提示词可配置**
   - 每个步骤都支持自定义提示词
   - 提供合理的默认值

4. **进度保存**
   - 支持断点续传
   - 保存中间结果

5. **输出格式**
   - 支持 TXT/MD/PDF 多种格式
   - 保留评审修改痕迹
