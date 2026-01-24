#!/usr/bin/env python3
"""
PDF法语翻译工具 - 逐段翻译大型PDF文档
支持断点续传、并发翻译，每段独立调用API确保翻译质量
"""

import os
import re
import json
import time
import argparse
import threading
from pathlib import Path
from typing import Generator
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

# 加载环境变量
load_dotenv()


# 默认需要过滤的水印/角注模式（针对这本PDF）
DEFAULT_FILTER_PATTERNS = [
    r'^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}$',  # 时间戳 如 19/12/2023   10:20:10
    r'^ÉPREUVES$',
    r'^NON$',
    r'^CORRIGÉES$',
    r'^TOUS DROITS DE REPRODUCTION',  # 版权声明
    r'^\d+AFC.*\.indd\s+\d+$',  # 文件名+页码 如 420601AFC_SECRET_CC2021_PC.indd   5
    r'^420601AFC.*\.indd\s+\d+$',  # 具体文件名
]


class PDFTranslator:
    """PDF翻译器类"""
    
    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = "gpt-4o-mini",
        max_chars_per_segment: int = 2000,
        output_dir: str = "output",
        header_ratio: float = 0.08,
        footer_ratio: float = 0.92,
        filter_patterns: list = None,
        auto_detect_watermarks: bool = True
    ):
        """
        初始化翻译器
        
        Args:
            api_key: OpenAI API密钥
            base_url: API基础URL（可选，用于兼容其他API）
            model: 使用的模型名称
            max_chars_per_segment: 每段最大字符数
            output_dir: 输出目录
            header_ratio: 页眉区域比例（页面顶部多少比例视为页眉）
            footer_ratio: 页脚区域比例（页面底部从哪里开始视为页脚）
            filter_patterns: 自定义过滤正则表达式列表
            auto_detect_watermarks: 是否自动检测水印
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model or os.getenv("MODEL_NAME", "gpt-4o-mini")
        self.max_chars = max_chars_per_segment
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 页眉页脚区域设置
        self.header_ratio = header_ratio
        self.footer_ratio = footer_ratio
        
        # 过滤模式
        self.filter_patterns = filter_patterns or DEFAULT_FILTER_PATTERNS
        self.auto_detect_watermarks = auto_detect_watermarks
        self.detected_watermarks = set()  # 自动检测到的水印
        
        # 初始化OpenAI客户端
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = OpenAI(**client_kwargs)
        
        # 翻译提示词 - 每次调用都会使用
        self.system_prompt = """你是一位精通法语和中文的专业翻译官。
你的任务是将输入的法语文本翻译为中文。
要求：
1. 保持翻译的学术性或文学性，语气灵动自然优雅，表达顺畅准确，确保语句结构完整，优先使用简洁句式，保证行文易懂，保证所有哲学学术术语的准确性，在你觉得重要的哲学学术术语后面加括号，在括号内标注原文并进行一到两句话的解释用于该文本的脚注。
2. 保留原有的格式（如标题、列表）。
3. 直接返回翻译后的中文内容，不要添加任何解释或说明。
"""

    def _should_filter_line(self, line: str) -> bool:
        """
        检查一行文本是否应该被过滤
        
        Args:
            line: 文本行
            
        Returns:
            是否应该过滤
        """
        line = line.strip()
        if not line:
            return True
            
        # 检查自动检测到的水印
        if line in self.detected_watermarks:
            return True
            
        # 检查正则模式
        for pattern in self.filter_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                return True
        
        return False

    def _detect_watermarks(self, pdf_path: str, sample_pages: int = 30) -> set:
        """
        自动检测PDF中的水印（在多页重复出现的内容）
        
        Args:
            pdf_path: PDF文件路径
            sample_pages: 采样页数
            
        Returns:
            检测到的水印文本集合
        """
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        pages_to_check = min(sample_pages, total_pages)
        
        # 收集所有文本行
        all_lines = []
        for page_num in range(pages_to_check):
            page = doc[page_num]
            text = page.get_text("text")
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            all_lines.extend(lines)
        
        doc.close()
        
        # 统计每行出现的次数
        line_counter = Counter(all_lines)
        
        # 出现在60%以上页面的短文本（<100字符）视为水印
        threshold = pages_to_check * 0.6
        watermarks = set()
        
        for line, count in line_counter.items():
            if count >= threshold and len(line) < 100:
                watermarks.add(line)
        
        return watermarks

    def extract_text_from_pdf(self, pdf_path: str) -> list[dict]:
        """
        从PDF提取文本，按页分割，自动过滤水印和页眉页脚
        
        Args:
            pdf_path: PDF文件路径
            
        Returns:
            包含页码和文本的字典列表
        """
        # 自动检测水印
        if self.auto_detect_watermarks:
            print("🔍 正在自动检测水印...")
            self.detected_watermarks = self._detect_watermarks(pdf_path)
            if self.detected_watermarks:
                print(f"✅ 检测到 {len(self.detected_watermarks)} 个水印/重复内容，将自动过滤")
                for wm in list(self.detected_watermarks)[:5]:  # 只显示前5个
                    print(f"   - {wm[:50]}{'...' if len(wm) > 50 else ''}")
                if len(self.detected_watermarks) > 5:
                    print(f"   ... 等 {len(self.detected_watermarks)} 项")
        
        doc = fitz.open(pdf_path)
        pages_text = []
        filtered_count = 0
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            rect = page.rect
            
            # 计算页眉页脚边界
            header_threshold = rect.height * self.header_ratio
            footer_threshold = rect.height * self.footer_ratio
            
            # 使用块级提取获取位置信息
            blocks = page.get_text("blocks")
            
            page_lines = []
            for block in blocks:
                if block[6] == 0:  # 文本块 (type 0)
                    x0, y0, x1, y1, text, block_no, block_type = block
                    text = text.strip()
                    
                    if not text:
                        continue
                    
                    # 过滤页眉区域
                    if y0 < header_threshold:
                        filtered_count += 1
                        continue
                    
                    # 过滤页脚区域
                    if y1 > footer_threshold:
                        filtered_count += 1
                        continue
                    
                    # 按行处理文本块，过滤水印
                    lines = text.split('\n')
                    clean_lines = []
                    for line in lines:
                        if not self._should_filter_line(line):
                            clean_lines.append(line.strip())
                        else:
                            filtered_count += 1
                    
                    if clean_lines:
                        page_lines.append('\n'.join(clean_lines))
            
            # 合并页面文本
            page_text = '\n\n'.join(page_lines)
            
            if page_text.strip():
                pages_text.append({
                    "page": page_num + 1,
                    "text": page_text.strip()
                })
        
        doc.close()
        print(f"🗑️  已过滤 {filtered_count} 个水印/页眉页脚内容")
        return pages_text

    def split_into_segments(self, pages_text: list[dict]) -> list[dict]:
        """
        将页面文本分割成适合翻译的段落
        
        Args:
            pages_text: 页面文本列表
            
        Returns:
            分段后的文本列表
        """
        segments = []
        segment_id = 0
        
        for page_data in pages_text:
            page_num = page_data["page"]
            text = page_data["text"]
            
            # 按段落分割
            paragraphs = text.split('\n\n')
            current_segment = ""
            
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                    
                # 如果当前段落加上新段落不超过限制，合并
                if len(current_segment) + len(para) + 2 <= self.max_chars:
                    if current_segment:
                        current_segment += "\n\n" + para
                    else:
                        current_segment = para
                else:
                    # 保存当前段落，开始新段落
                    if current_segment:
                        segments.append({
                            "id": segment_id,
                            "page": page_num,
                            "text": current_segment
                        })
                        segment_id += 1
                    
                    # 如果单个段落就超过限制，需要进一步分割
                    if len(para) > self.max_chars:
                        # 按句子分割
                        sentences = para.replace('。', '。\n').replace('. ', '.\n').split('\n')
                        current_segment = ""
                        for sent in sentences:
                            sent = sent.strip()
                            if not sent:
                                continue
                            if len(current_segment) + len(sent) + 1 <= self.max_chars:
                                current_segment = current_segment + " " + sent if current_segment else sent
                            else:
                                if current_segment:
                                    segments.append({
                                        "id": segment_id,
                                        "page": page_num,
                                        "text": current_segment
                                    })
                                    segment_id += 1
                                current_segment = sent
                    else:
                        current_segment = para
            
            # 保存最后一个段落
            if current_segment:
                segments.append({
                    "id": segment_id,
                    "page": page_num,
                    "text": current_segment
                })
                segment_id += 1
        
        return segments

    def translate_segment(self, text: str, retry_count: int = 3) -> str:
        """
        翻译单个段落，支持空返回检测和自动重试
        
        Args:
            text: 要翻译的文本
            retry_count: 重试次数
            
        Returns:
            翻译后的文本
        """
        for attempt in range(retry_count):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": f"请将以下法语文本翻译成中文：\n\n{text}"}
                    ],
                    temperature=0.3,  # 较低的温度确保翻译一致性
                    max_tokens=4000
                )
                result = response.choices[0].message.content
                
                # 检测空返回或无效返回
                if not result or not result.strip():
                    print(f"\n⚠️  返回为空 (尝试 {attempt + 1}/{retry_count})，正在重试...")
                    if attempt < retry_count - 1:
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        return f"[翻译返回为空，原文保留]\n{text}"
                
                return result.strip()
                
            except Exception as e:
                print(f"\n❌ 翻译出错 (尝试 {attempt + 1}/{retry_count}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    return f"[翻译失败: {str(e)}]\n原文: {text}"
        
        return f"[翻译失败]\n原文: {text}"

    def load_progress(self, progress_file: Path) -> dict:
        """加载进度文件，处理空文件或损坏的情况"""
        if progress_file.exists():
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return json.loads(content)
            except (json.JSONDecodeError, Exception) as e:
                print(f"⚠️  进度文件损坏，将重新开始: {e}")
        return {"completed": [], "translations": {}}

    def save_progress(self, progress_file: Path, progress: dict):
        """保存进度文件（线程安全），completed列表保持排序"""
        # 对completed列表排序，方便查看
        progress_to_save = {
            "completed": sorted(progress["completed"]),
            "translations": progress["translations"]
        }
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress_to_save, f, ensure_ascii=False, indent=2)

    def _translate_single(self, segment: dict, progress: dict, progress_file: Path, 
                          translations: dict, lock: threading.Lock, pbar: tqdm) -> dict:
        """
        翻译单个段落（用于并发）
        """
        seg_id = segment["id"]
        
        try:
            translated = self.translate_segment(segment["text"])
            
            # 线程安全地更新进度
            with lock:
                translations[str(seg_id)] = {
                    "page": segment["page"],
                    "original": segment["text"],
                    "translated": translated
                }
                
                if seg_id not in progress["completed"]:
                    progress["completed"].append(seg_id)
                
                # 保存进度
                self.save_progress(progress_file, progress)
                pbar.update(1)
            
            return {"id": seg_id, "success": True, "translated": translated}
        except Exception as e:
            return {"id": seg_id, "success": False, "error": str(e)}

    def translate_pdf(
        self,
        pdf_path: str,
        start_page: int = None,
        end_page: int = None,
        delay_between_calls: float = 0.5,
        max_workers: int = 5
    ) -> str:
        """
        翻译整个PDF（支持并发）
        
        Args:
            pdf_path: PDF文件路径
            start_page: 起始页码（可选）
            end_page: 结束页码（可选）
            delay_between_calls: API调用间隔（秒）- 并发模式下忽略
            max_workers: 并发线程数（默认5）
            
        Returns:
            输出文件路径
        """
        pdf_path = Path(pdf_path)
        pdf_name = pdf_path.stem
        
        # 模型名处理：去掉斜杠等特殊字符，用于文件名
        model_suffix = self.model.replace("/", "_").replace(":", "_") if self.model else "unknown"
        
        # 进度文件（包含模型名，不同模型进度独立）
        progress_file = self.output_dir / f"{pdf_name}_progress_{model_suffix}.json"
        
        print(f"📖 正在读取PDF: {pdf_path}")
        
        # 提取文本
        pages_text = self.extract_text_from_pdf(str(pdf_path))
        print(f"✅ 成功提取 {len(pages_text)} 页文本")
        
        # 筛选页面范围
        if start_page or end_page:
            pages_text = [
                p for p in pages_text 
                if (start_page is None or p["page"] >= start_page) and
                   (end_page is None or p["page"] <= end_page)
            ]
            print(f"📄 选择页面范围: {start_page or 1} - {end_page or '末页'}")
        
        # 分段
        segments = self.split_into_segments(pages_text)
        print(f"📝 共分割成 {len(segments)} 个翻译段落")
        
        # 加载进度
        progress = self.load_progress(progress_file)
        completed_ids = set(progress["completed"])
        translations = progress["translations"]
        
        if completed_ids:
            print(f"📌 发现已有进度，已完成 {len(completed_ids)}/{len(segments)} 段")
        
        # 筛选需要翻译的段落（跳过已完成且有效的）
        segments_to_translate = []
        for segment in segments:
            seg_id = segment["id"]
            existing = translations.get(str(seg_id), {})
            existing_trans = existing.get("translated", "")
            
            if str(seg_id) in completed_ids or seg_id in completed_ids:
                if existing_trans and existing_trans.strip():
                    continue  # 已有有效翻译，跳过
                else:
                    print(f"🔄 段落 {seg_id} 翻译为空，将重新翻译")
            
            segments_to_translate.append(segment)
        
        if not segments_to_translate:
            print("✅ 所有段落已翻译完成！")
        else:
            # 开始并发翻译
            print(f"\n🚀 开始并发翻译... (模型: {self.model}, 并发数: {max_workers})")
            print("=" * 50)
            
            lock = threading.Lock()
            
            try:
                with tqdm(total=len(segments_to_translate), desc="翻译进度") as pbar:
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {
                            executor.submit(
                                self._translate_single, 
                                segment, progress, progress_file, 
                                translations, lock, pbar
                            ): segment 
                            for segment in segments_to_translate
                        }
                        
                        for future in as_completed(futures):
                            result = future.result()
                            if not result["success"]:
                                print(f"\n⚠️  段落 {result['id']} 翻译失败: {result.get('error', '未知错误')}")
                            
            except KeyboardInterrupt:
                print("\n\n⏸️  翻译已暂停，进度已保存。下次运行将从断点继续。")
                return None
        
        # 生成最终文档
        print("\n📄 正在生成最终文档...")
        # 模型名处理：去掉斜杠等特殊字符，用于文件名
        model_suffix = self.model.replace("/", "_").replace(":", "_") if self.model else "unknown"
        output_file = self.output_dir / f"{pdf_name}_translated_{model_suffix}.txt"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            # 美观的标题
            f.write("┏" + "━" * 58 + "┓\n")
            f.write("┃" + f" {pdf_name} ".center(58) + "┃\n")
            f.write("┃" + " 中文翻译 ".center(58) + "┃\n")
            f.write("┣" + "━" * 58 + "┫\n")
            f.write("┃" + f" 原文语言: 法语 | 翻译模型: {self.model} ".center(58) + "┃\n")
            f.write("┗" + "━" * 58 + "┛\n\n")
            
            current_page = None
            for i in range(len(segments)):
                trans_data = translations.get(str(i), {})
                page = trans_data.get("page", segments[i]["page"])
                translated = trans_data.get("translated", "[未翻译]")
                
                # 美观的页码标记
                if page != current_page:
                    f.write("\n")
                    f.write("╔" + "═" * 20 + f" 第 {page} 页 " + "═" * 20 + "╗\n")
                    f.write("\n")
                    current_page = page
                
                f.write(translated + "\n\n")
        
        # 同时生成双语对照版本
        bilingual_file = self.output_dir / f"{pdf_name}_bilingual_{model_suffix}.txt"
        with open(bilingual_file, 'w', encoding='utf-8') as f:
            # 美观的标题
            f.write("┏" + "━" * 58 + "┓\n")
            f.write("┃" + f" {pdf_name} ".center(58) + "┃\n")
            f.write("┃" + " 法中双语对照 ".center(58) + "┃\n")
            f.write("┗" + "━" * 58 + "┛\n\n")
            
            current_page = None
            for i in range(len(segments)):
                trans_data = translations.get(str(i), {})
                page = trans_data.get("page", segments[i]["page"])
                original = trans_data.get("original", segments[i]["text"])
                translated = trans_data.get("translated", "[未翻译]")
                
                if page != current_page:
                    f.write("\n")
                    f.write("╔" + "═" * 20 + f" 第 {page} 页 " + "═" * 20 + "╗\n")
                    f.write("\n")
                    current_page = page
                
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【原文】                                │\n")
                f.write("└─────────────────────────────────────────┘\n")
                f.write(original + "\n\n")
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【译文】                                │\n")
                f.write("└─────────────────────────────────────────┘\n")
                f.write(translated + "\n")
                f.write("─" * 45 + "\n\n")
        
        print(f"\n✨ 翻译完成!")
        print(f"📁 译文文件: {output_file}")
        print(f"📁 双语对照: {bilingual_file}")
        
        return str(output_file)


def main():
    parser = argparse.ArgumentParser(
        description="PDF法语翻译工具 - 支持并发翻译大型PDF文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 翻译整本书（默认5并发）
  python pdf_translator.py book.pdf
  
  # 翻译指定页面范围
  python pdf_translator.py book.pdf --start 1 --end 50
  
  # 使用10个并发加速翻译
  python pdf_translator.py book.pdf --workers 10
  
  # 使用自定义模型
  python pdf_translator.py book.pdf --model gpt-4o

使用 OpenRouter API:
  python pdf_translator.py book.pdf \\
    --base-url https://openrouter.ai/api/v1 \\
    --api-key your_openrouter_key \\
    --model anthropic/claude-3.5-sonnet

OpenRouter 推荐模型:
  deepseek/deepseek-chat        # 最便宜
  anthropic/claude-3.5-haiku    # 快速
  anthropic/claude-3.5-sonnet   # 质量最好

环境变量设置 (.env 文件):
  OPENAI_API_KEY=your_api_key
  OPENAI_BASE_URL=https://openrouter.ai/api/v1
  MODEL_NAME=deepseek/deepseek-chat
        """
    )
    
    parser.add_argument("pdf_path", help="PDF文件路径")
    parser.add_argument("--start", type=int, help="起始页码")
    parser.add_argument("--end", type=int, help="结束页码")
    parser.add_argument("--model", default=None, help="使用的模型 (默认: gpt-4o-mini)")
    parser.add_argument("--max-chars", type=int, default=2000, help="每段最大字符数 (默认: 2000)")
    parser.add_argument("--workers", type=int, default=5, help="并发线程数 (默认: 5)")
    parser.add_argument("--output", default="output", help="输出目录 (默认: output)")
    parser.add_argument("--api-key", help="API密钥 (也可通过环境变量设置)")
    parser.add_argument("--base-url", help="API基础URL (用于OpenRouter等)")
    
    args = parser.parse_args()
    
    # 检查PDF文件是否存在
    if not Path(args.pdf_path).exists():
        print(f"❌ 错误: 文件不存在: {args.pdf_path}")
        return 1
    
    # 检查API密钥
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ 错误: 未设置API密钥")
        print("请通过以下方式之一设置:")
        print("  1. 创建 .env 文件并添加: OPENAI_API_KEY=your_key")
        print("  2. 使用命令行参数: --api-key your_key")
        print("  3. 设置环境变量: export OPENAI_API_KEY=your_key")
        return 1
    
    # 创建翻译器并开始翻译
    translator = PDFTranslator(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        max_chars_per_segment=args.max_chars,
        output_dir=args.output
    )
    
    translator.translate_pdf(
        pdf_path=args.pdf_path,
        start_page=args.start,
        end_page=args.end,
        max_workers=args.workers
    )
    
    return 0


if __name__ == "__main__":
    exit(main())
