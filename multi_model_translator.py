#!/usr/bin/env python3
"""
多模型翻译整合器 - 调用多个模型翻译，然后整合出最优结果
"""

import os
import json
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()


class MultiModelTranslator:
    """多模型翻译整合器"""
    
    # 默认的翻译模型列表（使用不同模型以获得多样化翻译）
    DEFAULT_TRANSLATION_MODELS = [
        "x-ai/grok-4.1-fast",
        "x-ai/grok-4.1-fast", 
        "x-ai/grok-4.1-fast",
    ]
    
    # 默认的整合模型
    DEFAULT_INTEGRATION_MODEL = "x-ai/grok-4.1-fast"
    
    # 默认翻译提示词
    DEFAULT_TRANSLATION_PROMPT = """你是一位精通法语和中文的专业翻译官。
你的任务是将输入的法语文本翻译为中文。
要求：
1. 保持翻译的学术性或文学性，语气灵动自然优雅，表达顺畅准确，确保语句结构完整，优先使用简洁句式，保证行文易懂，保证所有哲学学术术语的准确性，在你觉得重要的哲学学术术语后面加括号，在括号内标注原文并进行一到两句话的解释用于该文本的脚注。
2. 保留原有的格式（如标题、列表）。
3. 直接返回翻译后的中文内容，不要添加任何解释或说明。
"""
    
    # 默认整合提示词
    DEFAULT_INTEGRATION_PROMPT = """你是一位资深的翻译审校与编辑专家，精通法语和中文，尤其擅长哲学文本的翻译与编辑。

你将收到：
1. 一段法语原文（注意：原文来自PDF提取，可能存在格式问题）
2. 多个中文翻译版本

你的任务是**整合出最优翻译**，同时承担**编辑梳理**工作。

**输出格式（严格遵守）**：
```
[分析]
简要说明：采用了哪个版本的优点，修正了什么问题，清理了什么格式错误

[译文]
最终整合的翻译内容
```

**整合原则**：
- 取各版本之长，避其所短
- 保持术语翻译准确一致
- 脚注精炼，不要过多

**编辑梳理（重要）**：
- 检查并删除残留的水印、页码、文件名等无关内容（如日期时间戳、"ÉPREUVES"、".indd"等）
- 修正PDF提取导致的格式问题（如断行错误、多余空格、乱码字符）
- 确保段落结构清晰、行文流畅
- 如果原文有明显的OCR错误或乱码，根据上下文合理修正
"""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        translation_models: list = None,
        integration_model: str = None,
        output_dir: str = "output",
        system_prompt: str = None,
        integration_prompt: str = None,
        model_prompts: list = None
    ):
        """
        初始化多模型翻译器
        
        Args:
            api_key: API密钥
            base_url: API基础URL（如OpenRouter）
            translation_models: 用于翻译的模型列表（默认3个）
            integration_model: 用于整合的模型
            output_dir: 输出目录
            system_prompt: 默认翻译提示词（当model_prompts未指定时使用）
            integration_prompt: 自定义整合提示词
            model_prompts: 每个模型的独立提示词列表（与translation_models一一对应）
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.translation_models = translation_models or self.DEFAULT_TRANSLATION_MODELS
        self.integration_model = integration_model or self.DEFAULT_INTEGRATION_MODEL
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 初始化客户端
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = OpenAI(**client_kwargs)
        
        # 默认翻译提示词
        self.translation_prompt = system_prompt or self.DEFAULT_TRANSLATION_PROMPT
        
        # 每个模型的独立提示词（如果提供）
        # 如果model_prompts长度不够，用默认提示词补齐
        self.model_prompts = []
        if model_prompts:
            for i, model in enumerate(self.translation_models):
                if i < len(model_prompts) and model_prompts[i]:
                    self.model_prompts.append(model_prompts[i])
                else:
                    self.model_prompts.append(self.translation_prompt)
        else:
            self.model_prompts = [self.translation_prompt] * len(self.translation_models)
        
        # 整合提示词（支持自定义）
        self.integration_prompt = integration_prompt or self.DEFAULT_INTEGRATION_PROMPT

    def _call_model(self, model: str, system_prompt: str, user_content: str, 
                    retry_count: int = 3) -> str:
        """
        调用指定模型
        
        Args:
            model: 模型名称
            system_prompt: 系统提示词
            user_content: 用户内容
            retry_count: 重试次数
            
        Returns:
            模型返回的内容
        """
        for attempt in range(retry_count):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.3,
                    max_tokens=8000
                )
                result = response.choices[0].message.content
                if result and result.strip():
                    return result.strip()
                else:
                    if attempt < retry_count - 1:
                        time.sleep(2 ** attempt)
                        continue
            except Exception as e:
                if attempt < retry_count - 1:
                    time.sleep(2 ** attempt)
                else:
                    return f"[模型 {model} 调用失败: {str(e)}]"
        
        return f"[模型 {model} 返回为空]"

    def translate_with_single_model(self, text: str, model: str, prompt: str = None) -> str:
        """使用单个模型翻译"""
        user_content = f"请将以下法语文本翻译成中文：\n\n{text}"
        system_prompt = prompt or self.translation_prompt
        return self._call_model(model, system_prompt, user_content)

    def translate_segment_multi(self, original_text: str) -> dict:
        """
        使用多个模型翻译同一段文本，每个模型使用其独立的提示词
        
        Args:
            original_text: 原文
            
        Returns:
            包含各模型翻译结果的字典，key为 "模型名_序号" 以避免重复
        """
        translations = {}
        
        # 并发调用多个翻译模型，每个模型使用其独立的提示词
        with ThreadPoolExecutor(max_workers=len(self.translation_models)) as executor:
            # 使用enumerate为每个模型添加序号，避免相同模型名覆盖
            futures = {
                executor.submit(
                    self.translate_with_single_model, 
                    original_text, 
                    model, 
                    self.model_prompts[idx]  # 使用该模型的独立提示词
                ): (idx, model)
                for idx, model in enumerate(self.translation_models)
            }
            
            for future in as_completed(futures):
                idx, model = futures[future]
                # 使用 "序号_模型名" 作为key，确保唯一性
                key = f"{idx+1}_{model}"
                try:
                    translations[key] = future.result()
                except Exception as e:
                    translations[key] = f"[翻译失败: {str(e)}]"
        
        return translations

    def integrate_translations(self, original_text: str, translations: dict) -> dict:
        """
        整合多个翻译版本，生成最优结果
        
        Args:
            original_text: 法语原文
            translations: 各模型的翻译结果 {model: translation}
            
        Returns:
            包含reasoning和译文的字典
        """
        # 构建整合请求
        user_content = f"""## 法语原文

{original_text}

## 翻译版本

"""
        for i, (model, trans) in enumerate(sorted(translations.items()), 1):
            # 从key中提取模型名（去掉序号前缀）
            model_display = model.split("_", 1)[-1] if "_" in model else model
            model_short = model_display.split("/")[-1] if "/" in model_display else model_display
            user_content += f"### 译者{i} ({model_short})\n\n{trans}\n\n"
        
        user_content += "## 请按格式输出分析和整合译文"
        
        raw_result = self._call_model(
            self.integration_model, 
            self.integration_prompt, 
            user_content
        )
        
        # 解析返回结果，提取reasoning和译文
        reasoning = ""
        integrated = raw_result
        
        if "[分析]" in raw_result and "[译文]" in raw_result:
            parts = raw_result.split("[译文]")
            if len(parts) == 2:
                reasoning_part = parts[0]
                integrated = parts[1].strip()
                # 提取分析内容
                if "[分析]" in reasoning_part:
                    reasoning = reasoning_part.split("[分析]")[-1].strip()
        elif "分析" in raw_result[:50] or "译文" in raw_result[:100]:
            # 尝试其他格式
            lines = raw_result.split("\n")
            in_reasoning = False
            in_translation = False
            reasoning_lines = []
            translation_lines = []
            
            for line in lines:
                if "分析" in line and len(line) < 20:
                    in_reasoning = True
                    in_translation = False
                    continue
                elif "译文" in line and len(line) < 20:
                    in_reasoning = False
                    in_translation = True
                    continue
                
                if in_reasoning:
                    reasoning_lines.append(line)
                elif in_translation:
                    translation_lines.append(line)
            
            if reasoning_lines:
                reasoning = "\n".join(reasoning_lines).strip()
            if translation_lines:
                integrated = "\n".join(translation_lines).strip()
        
        return {
            "reasoning": reasoning,
            "text": integrated if integrated else raw_result
        }

    def translate_segment_with_integration(self, original_text: str) -> dict:
        """
        完整的多模型翻译+整合流程
        
        Args:
            original_text: 原文
            
        Returns:
            包含各模型翻译和最终整合结果的字典
        """
        # 第一步：多模型翻译
        translations = self.translate_segment_multi(original_text)
        
        # 第二步：整合（返回包含reasoning的结果）
        integration_result = self.integrate_translations(original_text, translations)
        
        return {
            "individual_translations": translations,
            "reasoning": integration_result["reasoning"],
            "integrated": integration_result["text"]
        }


class MultiModelPDFTranslator:
    """多模型PDF翻译器 - 整合到PDF翻译流程"""
    
    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        translation_models: list = None,
        integration_model: str = None,
        max_chars_per_segment: int = 2000,
        output_dir: str = "output",
        header_ratio: float = 0.08,
        footer_ratio: float = 0.92
    ):
        """
        初始化
        
        Args:
            api_key: API密钥
            base_url: API基础URL
            translation_models: 翻译模型列表
            integration_model: 整合模型
            max_chars_per_segment: 每段最大字符数
            output_dir: 输出目录
            header_ratio: 页眉区域比例
            footer_ratio: 页脚区域比例
        """
        self.multi_translator = MultiModelTranslator(
            api_key=api_key,
            base_url=base_url,
            translation_models=translation_models,
            integration_model=integration_model,
            output_dir=output_dir
        )
        
        self.max_chars = max_chars_per_segment
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.header_ratio = header_ratio
        self.footer_ratio = footer_ratio
        
        # 导入原有的PDF处理功能
        from pdf_translator import PDFTranslator, DEFAULT_FILTER_PATTERNS
        self._pdf_helper = PDFTranslator(
            api_key=api_key or "dummy",  # 只用于PDF处理，不用于翻译
            base_url=base_url,
            max_chars_per_segment=max_chars_per_segment,
            output_dir=output_dir,
            header_ratio=header_ratio,
            footer_ratio=footer_ratio
        )

    def load_progress(self, progress_file: Path) -> dict:
        """加载进度"""
        if progress_file.exists():
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return json.loads(content)
            except:
                pass
        return {"completed": [], "translations": {}}

    def save_progress(self, progress_file: Path, progress: dict):
        """保存进度"""
        progress_to_save = {
            "completed": sorted(progress["completed"]),
            "translations": progress["translations"]
        }
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress_to_save, f, ensure_ascii=False, indent=2)

    def translate_pdf(
        self,
        pdf_path: str,
        start_page: int = None,
        end_page: int = None,
        max_workers: int = 10
    ) -> str:
        """
        使用多模型翻译PDF
        
        Args:
            pdf_path: PDF文件路径
            start_page: 起始页码
            end_page: 结束页码
            max_workers: 并发处理的段落数
            
        Returns:
            输出文件路径
        """
        pdf_path = Path(pdf_path)
        pdf_name = pdf_path.stem
        
        # 生成模型标识（适配相同模型和不同模型的情况）
        trans_models = self.multi_translator.translation_models
        unique_models = list(set(trans_models))
        
        if len(unique_models) == 1:
            # 相同模型多次调用：multi3x_grok-4-1-fast
            model_short = unique_models[0].split("/")[-1].replace(".", "-")[:12]
            trans_suffix = f"multi{len(trans_models)}x_{model_short}"
        else:
            # 不同模型：multi_claude+gpt4+deepseek
            model_shorts = [m.split("/")[-1].replace(".", "-")[:8] for m in unique_models]
            trans_suffix = f"multi_{'+'.join(model_shorts)}"
        
        integration_short = self.multi_translator.integration_model.split("/")[-1].replace(".", "-")[:12]
        model_suffix = f"{trans_suffix}_int_{integration_short}"
        
        progress_file = self.output_dir / f"{pdf_name}_progress_{model_suffix}.json"
        
        print(f"📖 正在读取PDF: {pdf_path}")
        print(f"🤖 翻译模型: {', '.join(self.multi_translator.translation_models)}")
        print(f"🔧 整合模型: {self.multi_translator.integration_model}")
        
        # 使用原有的PDF处理功能
        pages_text = self._pdf_helper.extract_text_from_pdf(str(pdf_path))
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
        segments = self._pdf_helper.split_into_segments(pages_text)
        print(f"📝 共分割成 {len(segments)} 个翻译段落")
        
        # 加载进度
        progress = self.load_progress(progress_file)
        completed_ids = set(progress["completed"])
        translations = progress["translations"]
        
        if completed_ids:
            print(f"📌 发现已有进度，已完成 {len(completed_ids)}/{len(segments)} 段")
        
        # 筛选需要翻译的段落
        segments_to_translate = []
        for segment in segments:
            seg_id = segment["id"]
            existing = translations.get(str(seg_id), {})
            existing_trans = existing.get("integrated", "")
            
            if str(seg_id) in completed_ids or seg_id in completed_ids:
                if existing_trans and existing_trans.strip():
                    continue
            
            segments_to_translate.append(segment)
        
        if not segments_to_translate:
            print("✅ 所有段落已翻译完成！")
        else:
            print(f"\n🚀 开始多模型翻译... (并发段落数: {max_workers})")
            print("=" * 50)
            
            lock = threading.Lock()
            
            def process_segment(segment):
                seg_id = segment["id"]
                try:
                    result = self.multi_translator.translate_segment_with_integration(segment["text"])
                    
                    with lock:
                        translations[str(seg_id)] = {
                            "page": segment["page"],
                            "original": segment["text"],
                            "individual": result["individual_translations"],
                            "reasoning": result["reasoning"],  # 新增：整合分析
                            "integrated": result["integrated"]
                        }
                        
                        if seg_id not in progress["completed"]:
                            progress["completed"].append(seg_id)
                        
                        self.save_progress(progress_file, progress)
                    
                    return {"id": seg_id, "success": True}
                except Exception as e:
                    return {"id": seg_id, "success": False, "error": str(e)}
            
            try:
                with tqdm(total=len(segments_to_translate), desc="多模型翻译") as pbar:
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {
                            executor.submit(process_segment, seg): seg
                            for seg in segments_to_translate
                        }
                        
                        for future in as_completed(futures):
                            result = future.result()
                            pbar.update(1)
                            if not result["success"]:
                                print(f"\n⚠️  段落 {result['id']} 失败: {result.get('error')}")
                                
            except KeyboardInterrupt:
                print("\n\n⏸️  翻译已暂停，进度已保存。")
                return None
        
        # 生成输出文件
        print("\n📄 正在生成最终文档...")
        
        # 整合版译文
        output_file = self.output_dir / f"{pdf_name}_translated_{model_suffix}.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("┏" + "━" * 58 + "┓\n")
            f.write("┃" + " 多模型整合翻译 ".center(54) + "┃\n")
            f.write("┣" + "━" * 58 + "┫\n")
            f.write("┃" + f" 翻译: {', '.join([m.split('/')[-1] for m in self.multi_translator.translation_models])} ".center(54) + "┃\n")
            f.write("┃" + f" 整合: {self.multi_translator.integration_model.split('/')[-1]} ".center(54) + "┃\n")
            f.write("┗" + "━" * 58 + "┛\n\n")
            
            current_page = None
            for i in range(len(segments)):
                trans_data = translations.get(str(i), {})
                page = trans_data.get("page", segments[i]["page"])
                integrated = trans_data.get("integrated", "[未翻译]")
                
                if page != current_page:
                    f.write("\n")
                    f.write("╔" + "═" * 20 + f" 第 {page} 页 " + "═" * 20 + "╗\n")
                    f.write("\n")
                    current_page = page
                
                f.write(integrated + "\n\n")
        
        # 双语对照版（包含所有翻译版本）
        bilingual_file = self.output_dir / f"{pdf_name}_bilingual_{model_suffix}.txt"
        with open(bilingual_file, 'w', encoding='utf-8') as f:
            f.write("┏" + "━" * 58 + "┓\n")
            f.write("┃" + " 多模型翻译对照 ".center(54) + "┃\n")
            f.write("┗" + "━" * 58 + "┛\n\n")
            
            current_page = None
            for i in range(len(segments)):
                trans_data = translations.get(str(i), {})
                page = trans_data.get("page", segments[i]["page"])
                original = trans_data.get("original", segments[i]["text"])
                individual = trans_data.get("individual", {})
                reasoning = trans_data.get("reasoning", "")
                integrated = trans_data.get("integrated", "[未翻译]")
                
                if page != current_page:
                    f.write("\n")
                    f.write("╔" + "═" * 20 + f" 第 {page} 页 " + "═" * 20 + "╗\n")
                    f.write("\n")
                    current_page = page
                
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【原文】                                │\n")
                f.write("└─────────────────────────────────────────┘\n")
                f.write(original + "\n\n")
                
                # 各模型翻译（按序号排序）
                for model, trans in sorted(individual.items()):
                    # 从key中提取显示名（去掉序号前缀如 "1_"）
                    model_display = model.split("_", 1)[-1] if "_" in model else model
                    model_short = model_display.split("/")[-1] if "/" in model_display else model_display
                    # 提取序号
                    idx = model.split("_")[0] if "_" in model else ""
                    f.write(f"┌─── 【译者{idx}: {model_short}】 ───┐\n")
                    f.write(trans + "\n\n")
                
                # 整合分析（如果有）
                if reasoning:
                    f.write("┌─────────────────────────────────────────┐\n")
                    f.write("│ 【🔍 整合分析】                         │\n")
                    f.write("└─────────────────────────────────────────┘\n")
                    f.write(reasoning + "\n\n")
                
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【✨ 整合译文】                         │\n")
                f.write("└─────────────────────────────────────────┘\n")
                f.write(integrated + "\n")
                f.write("═" * 50 + "\n\n")
        
        print(f"\n✨ 翻译完成!")
        print(f"📁 整合译文: {output_file}")
        print(f"📁 多版本对照: {bilingual_file}")
        
        return str(output_file)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="多模型翻译整合器 - 调用多个模型翻译后整合最优结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 使用默认模型翻译
  python multi_model_translator.py book.pdf
  
  # 指定翻译模型
  python multi_model_translator.py book.pdf \\
    --models "anthropic/claude-3.5-sonnet,openai/gpt-4o,deepseek/deepseek-chat"
  
  # 指定整合模型
  python multi_model_translator.py book.pdf --integration-model "anthropic/claude-3.5-sonnet"
  
  # 翻译指定页面
  python multi_model_translator.py book.pdf --start 1 --end 10

默认配置:
  翻译模型: claude-3.5-sonnet, gpt-4o, deepseek-chat
  整合模型: claude-3.5-sonnet
        """
    )
    
    parser.add_argument("pdf_path", help="PDF文件路径")
    parser.add_argument("--start", type=int, help="起始页码")
    parser.add_argument("--end", type=int, help="结束页码")
    parser.add_argument("--models", help="翻译模型列表，逗号分隔")
    parser.add_argument("--integration-model", help="整合模型")
    parser.add_argument("--workers", type=int, default=10, help="并发段落数 (默认: 10)")
    parser.add_argument("--output", default="output", help="输出目录")
    parser.add_argument("--api-key", help="API密钥")
    parser.add_argument("--base-url", help="API基础URL")
    
    args = parser.parse_args()
    
    if not Path(args.pdf_path).exists():
        print(f"❌ 文件不存在: {args.pdf_path}")
        return 1
    
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ 未设置API密钥")
        return 1
    
    # 解析模型列表
    translation_models = None
    if args.models:
        translation_models = [m.strip() for m in args.models.split(",")]
    
    translator = MultiModelPDFTranslator(
        api_key=api_key,
        base_url=args.base_url or os.getenv("OPENAI_BASE_URL"),
        translation_models=translation_models,
        integration_model=args.integration_model,
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
