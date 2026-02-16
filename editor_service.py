#!/usr/bin/env python3
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
from typing import List, Dict, Optional, Callable

from openai import OpenAI
from dotenv import load_dotenv

from word_processor import WordProcessor
from text_aligner import TextAligner

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
- 问题：（列出主要问题，如有）
- 参考：（说明从 AI 译文中借鉴了什么，如有）

[最终译文]
打磨后的最佳译文
```

## 编辑原则

1. **忠实原文**：不得擅自增删内容
2. **尊重作者**：保留用户译文的优秀表达
3. **取长补短**：综合各版本优点
4. **精益求精**：每个词语都要反复推敲
5. **术语一致**：保持专业术语翻译的一致性
6. **格式清理**：删除残留的水印、页码、文件名等无关内容
"""

    # 翻译对比提示词
    DEFAULT_TRANSLATION_PROMPT = """你是一位精通法语和中文的专业翻译官。
请将以下法语文本翻译为中文。

要求：
1. 准确传达原意，语言流畅自然
2. 保持学术性/文学性风格
3. 专业术语后可加括号标注原文
4. 直接返回译文，不要解释
"""

    # 无用户译文时的整合提示词
    DEFAULT_INTEGRATION_PROMPT = """你是一位资深的翻译审校专家，精通法语和中文。

你将收到：
1. 法语原文
2. 多个 AI 模型的翻译版本

请整合出最优翻译。

## 输出格式

```
[分析]
简要说明取舍依据

[译文]
最终整合的译文
```
"""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        translation_models: List = None,  # 支持字符串列表或模型配置列表
        editor_model = None,              # 支持字符串或模型配置
        editor_prompt: str = None,
        translation_prompts: List[str] = None,
        alignment_model = None,           # 支持字符串或模型配置
        use_smart_alignment: bool = True,
        output_dir: str = "output"
    ):
        """
        初始化编辑服务
        
        Args:
            api_key: 默认 API 密钥
            base_url: 默认 API 基础 URL
            translation_models: 用于对比翻译的模型列表，支持两种格式：
                - 字符串列表: ["model1", "model2"]
                - 配置列表: [{"model": "doubao-1.5-pro", "base_url": "...", "api_key": "..."}, ...]
            editor_model: 用于编辑审校的模型，支持字符串或配置字典
            editor_prompt: 自定义编辑提示词
            translation_prompts: 每个翻译模型的提示词
            alignment_model: 用于段落对齐的模型，支持字符串或配置字典
            use_smart_alignment: 是否使用智能对齐（大模型）
            output_dir: 输出目录
        """
        # 默认配置
        self.default_api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.default_base_url = base_url or os.getenv("OPENAI_BASE_URL")
        
        # 解析模型配置
        self.translation_model_configs = self._parse_model_configs(
            translation_models or ["x-ai/grok-4.1-fast", "x-ai/grok-4.1-fast"]
        )
        self.editor_model_config = self._parse_single_model_config(
            editor_model or "x-ai/grok-4.1-fast"
        )
        self.alignment_model_config = self._parse_single_model_config(
            alignment_model or "x-ai/grok-4.1-fast"
        )
        
        self.use_smart_alignment = use_smart_alignment
        self.editor_prompt = editor_prompt or self.DEFAULT_EDITOR_PROMPT
        
        # 每个翻译模型的提示词
        if translation_prompts and len(translation_prompts) >= len(self.translation_model_configs):
            self.translation_prompts = translation_prompts
        else:
            self.translation_prompts = [self.DEFAULT_TRANSLATION_PROMPT] * len(self.translation_model_configs)
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 缓存 API 客户端 {(base_url, api_key): client}
        self._client_cache = {}
        
        # 初始化子模块
        self.word_processor = WordProcessor()
        
        # 对齐器使用对齐模型的配置
        align_config = self.alignment_model_config
        self.text_aligner = TextAligner(
            api_key=align_config.get("api_key", self.default_api_key),
            base_url=align_config.get("base_url", self.default_base_url),
            alignment_model=align_config["model"]
        )
    
    def _parse_single_model_config(self, model_config) -> dict:
        """解析单个模型配置"""
        if isinstance(model_config, str):
            return {
                "model": model_config,
                "base_url": self.default_base_url,
                "api_key": self.default_api_key
            }
        elif isinstance(model_config, dict):
            return {
                "model": model_config.get("model", "x-ai/grok-4.1-fast"),
                "base_url": model_config.get("base_url", self.default_base_url),
                "api_key": model_config.get("api_key", self.default_api_key),
                "name": model_config.get("name", model_config.get("model", "unknown"))
            }
        else:
            return {
                "model": "x-ai/grok-4.1-fast",
                "base_url": self.default_base_url,
                "api_key": self.default_api_key
            }
    
    def _parse_model_configs(self, models: List) -> List[dict]:
        """解析模型配置列表"""
        configs = []
        for m in models:
            configs.append(self._parse_single_model_config(m))
        return configs
    
    def _get_client(self, base_url: str = None, api_key: str = None) -> OpenAI:
        """获取或创建 API 客户端（带缓存）"""
        url = base_url or self.default_base_url
        key = api_key or self.default_api_key
        
        cache_key = (url, key)
        if cache_key not in self._client_cache:
            client_kwargs = {"api_key": key}
            if url:
                client_kwargs["base_url"] = url
            self._client_cache[cache_key] = OpenAI(**client_kwargs)
        
        return self._client_cache[cache_key]
    
    # 兼容旧属性
    @property
    def translation_models(self):
        return [c["model"] for c in self.translation_model_configs]
    
    @property
    def editor_model(self):
        return self.editor_model_config["model"]
    
    @property
    def alignment_model(self):
        return self.alignment_model_config["model"]
    
    @property
    def client(self):
        """默认客户端（用于编辑模型）"""
        config = self.editor_model_config
        return self._get_client(config.get("base_url"), config.get("api_key"))
    
    def _call_model_with_config(
        self, 
        model_config: dict,
        system_prompt: str, 
        user_content: str,
        max_retries: int = 3
    ) -> str:
        """
        使用指定配置调用模型 API
        
        Args:
            model_config: {"model": "...", "base_url": "...", "api_key": "..."}
        """
        client = self._get_client(
            model_config.get("base_url"),
            model_config.get("api_key")
        )
        model = model_config.get("model")
        
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
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
    
    def _call_model(
        self, 
        model: str, 
        system_prompt: str, 
        user_content: str,
        max_retries: int = 3
    ) -> str:
        """调用模型 API（使用默认配置，兼容旧代码）"""
        config = {
            "model": model,
            "base_url": self.default_base_url,
            "api_key": self.default_api_key
        }
        return self._call_model_with_config(config, system_prompt, user_content, max_retries)

    def translate_for_comparison(self, source_text: str) -> Dict[str, str]:
        """
        调用多个模型翻译，用于对比
        每个模型可以有不同的 URL 和 API Key
        
        Returns:
            {model_key: translation}
        """
        translations = {}
        
        with ThreadPoolExecutor(max_workers=len(self.translation_model_configs)) as executor:
            futures = {}
            for idx, model_config in enumerate(self.translation_model_configs):
                prompt = self.translation_prompts[idx] if idx < len(self.translation_prompts) \
                    else self.DEFAULT_TRANSLATION_PROMPT
                
                # 获取显示名称
                display_name = model_config.get("name", model_config.get("model", "unknown"))
                
                future = executor.submit(
                    self._call_model_with_config, 
                    model_config,
                    prompt, 
                    f"请翻译以下法语文本：\n\n{source_text}"
                )
                # 使用序号+显示名称作为key
                futures[future] = f"{idx+1}_{display_name}"
            
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
        user_translation: str,      # 用户译文（可以是多个译文合并的）
        ai_translations: Dict[str, str] = None,  # AI 对比译文（可选）
        alignment_info: Dict = None  # 对齐信息（可选，用于展示复杂情况）
    ) -> Dict:
        """
        编辑审校单个段落
        
        Args:
            source_text: 法语原文
            user_translation: 用户的译文（可能是多个译文合并）
            ai_translations: AI 翻译版本（可选，若无则调用获取）
            alignment_info: 对齐元信息，包含重叠、多译文等情况
            
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

{user_translation}"""

        # 如果有对齐信息，添加说明
        if alignment_info:
            coverage = alignment_info.get("coverage", "")
            is_multi = alignment_info.get("is_multi_target", False)
            note = alignment_info.get("alignment_note", "")
            
            if is_multi or coverage == "overlap":
                user_content += f"\n\n⚠️ 注意：此原文对应多个译文段落"
                if note:
                    user_content += f"（{note}）"
                user_content += "，上方的用户译文是合并后的内容，请特别注意连贯性和完整性。"

        user_content += "\n\n## AI 参考译文\n\n"
        for model, trans in sorted(ai_translations.items()):
            # 从key中提取显示名
            model_display = model.split("_", 1)[-1] if "_" in model else model
            model_short = model_display.split("/")[-1] if "/" in model_display else model_display
            user_content += f"### {model_short}\n{trans}\n\n"
        
        user_content += "## 请按格式输出评审意见和最终译文"
        
        # 调用编辑模型（使用编辑模型的独立配置）
        result = self._call_model_with_config(self.editor_model_config, self.editor_prompt, user_content)
        
        # 解析结果
        review = ""
        final_text = result
        
        if "[评审意见]" in result and "[最终译文]" in result:
            parts = result.split("[最终译文]")
            if len(parts) == 2:
                review = parts[0].replace("[评审意见]", "").strip()
                final_text = parts[1].strip()
                # 清理可能的 markdown 代码块标记
                final_text = final_text.replace("```", "").strip()
        
        return {
            "source": source_text,
            "user_translation": user_translation,
            "ai_translations": ai_translations,
            "review": review,
            "final": final_text
        }
    
    def translate_and_integrate(
        self,
        source_text: str,
        ai_translations: Dict[str, str] = None
    ) -> Dict:
        """
        无用户译文时，仅翻译并整合
        
        Returns:
            {
                "ai_translations": {...},
                "review": "整合分析",
                "final": "最终译文"
            }
        """
        if ai_translations is None:
            ai_translations = self.translate_for_comparison(source_text)
        
        # 构建整合请求
        user_content = f"""## 法语原文

{source_text}

## AI 翻译版本

"""
        for model, trans in sorted(ai_translations.items()):
            model_display = model.split("_", 1)[-1] if "_" in model else model
            model_short = model_display.split("/")[-1] if "/" in model_display else model_display
            user_content += f"### {model_short}\n{trans}\n\n"
        
        user_content += "## 请按格式输出分析和整合译文"
        
        # 使用编辑模型的独立配置
        result = self._call_model_with_config(
            self.editor_model_config,
            self.DEFAULT_INTEGRATION_PROMPT,
            user_content
        )
        
        # 解析结果
        review = ""
        final_text = result
        
        if "[分析]" in result and "[译文]" in result:
            parts = result.split("[译文]")
            if len(parts) == 2:
                review = parts[0].replace("[分析]", "").strip()
                final_text = parts[1].strip()
                final_text = final_text.replace("```", "").strip()
        
        return {
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
        progress_callback: Callable[[int, int], None] = None
    ) -> Dict:
        """
        处理完整文档：对齐、翻译、编辑
        
        Args:
            pdf_path: PDF 原文路径
            word_path: Word 译文路径
            start_page: 起始页码
            end_page: 结束页码
            max_workers: 并发数
            progress_callback: 进度回调函数 (completed, total)
            
        Returns:
            处理结果
        """
        results = {
            "paragraphs": [],
            "stats": {
                "total": 0,
                "matched": 0,
                "edited": 0,
                "translated_only": 0,
                "overlap": 0,       # 重叠覆盖的段落数
                "missing": 0,       # 漏译的段落数
                "multi_target": 0,  # 对应多个译文的段落数
                "skipped": 0        # 跳过的段落数（出版信息等）
            }
        }
        
        # 1. 提取 PDF 原文
        from pdf_translator import PDFTranslator
        pdf_helper = PDFTranslator(api_key="dummy", base_url="dummy")
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
                if para and len(para) > 10:  # 过滤过短内容
                    pdf_paragraphs.append({
                        "page": page_num,
                        "text": para,
                        "index": len(pdf_paragraphs)
                    })
        
        print(f"📄 提取 PDF 段落: {len(pdf_paragraphs)} 个")
        
        # 2. 提取 Word 译文
        word_paragraphs = self.word_processor.extract_paragraphs(word_path)
        print(f"📝 提取 Word 段落: {len(word_paragraphs)} 个")
        
        # 3. 智能对齐段落
        print(f"🤖 使用{'智能' if self.use_smart_alignment else '规则'}对齐...")
        
        if self.use_smart_alignment:
            aligned = self.text_aligner.smart_align(pdf_paragraphs, word_paragraphs)
        else:
            aligned = self.text_aligner.align_paragraphs(pdf_paragraphs, word_paragraphs)
        
        # 打印对齐质量
        quality = self.text_aligner.calculate_alignment_quality(aligned)
        print(f"🔗 对齐完成: 匹配率 {quality['match_rate']:.1%}, 平均置信度 {quality['average_confidence']:.2f}")
        
        # 统计各种对齐情况
        missing_count = 0
        overlap_count = 0
        multi_target_count = 0
        skipped_count = 0
        
        for a in aligned:
            coverage = a.get("coverage", "")
            if coverage == "skip":
                skipped_count += 1
            elif coverage == "missing" or not a.get("matched"):
                missing_count += 1
            if coverage == "overlap":
                overlap_count += 1
            if a.get("is_multi_target"):
                multi_target_count += 1
        
        # 打印详细统计
        if skipped_count > 0:
            print(f"⏭️ 有 {skipped_count} 个原文段落跳过（出版信息等）")
        if missing_count > 0:
            print(f"⚠️ 有 {missing_count} 个原文段落没有找到对应译文（漏译）")
        if overlap_count > 0:
            print(f"🔀 有 {overlap_count} 个原文段落被多个译文重叠覆盖")
        if multi_target_count > 0:
            print(f"📑 有 {multi_target_count} 个原文段落对应多个译文段落")
        
        results["stats"]["total"] = len(aligned)
        results["stats"]["matched"] = quality["matched_paragraphs"]
        results["stats"]["missing"] = missing_count
        results["stats"]["overlap"] = overlap_count
        results["stats"]["multi_target"] = multi_target_count
        results["stats"]["skipped"] = skipped_count
        
        # 4. 并发处理每个段落
        lock = threading.Lock()
        processed = 0
        processed_results = []
        
        def process_paragraph(item):
            nonlocal processed
            
            source_text = item["source_text"]
            user_trans = item["target_text"] if item["matched"] else None
            coverage = item.get("coverage", "")
            
            # 提取对齐信息用于编辑提示
            alignment_info = {
                "coverage": coverage,
                "is_multi_target": item.get("is_multi_target", False),
                "alignment_note": item.get("alignment_note", ""),
                "target_indices": item.get("target_indices", [])
            }
            
            # 跳过不需要翻译的内容（出版信息等）
            if coverage == "skip":
                result = {
                    **item,
                    "ai_translations": {},
                    "review": "⏭️ 此段为出版信息/页眉页脚，无需翻译",
                    "final": "",  # 不输出
                    "edited": False,
                    "has_user_translation": False,
                    "skipped": True
                }
                with lock:
                    processed += 1
                    if progress_callback:
                        progress_callback(processed, len(aligned))
                return result
            
            try:
                # 获取 AI 翻译
                ai_trans = self.translate_for_comparison(source_text)
                
                if user_trans:
                    # 有用户译文，进行编辑审校
                    edit_result = self.edit_paragraph(
                        source_text, 
                        user_trans, 
                        ai_trans,
                        alignment_info=alignment_info
                    )
                    result = {
                        **item,
                        "ai_translations": edit_result["ai_translations"],
                        "review": edit_result["review"],
                        "final": edit_result["final"],
                        "edited": True,
                        "has_user_translation": True
                    }
                else:
                    # 无用户译文，仅翻译整合
                    integrate_result = self.translate_and_integrate(source_text, ai_trans)
                    
                    # 添加漏译标记
                    review = integrate_result["review"]
                    if coverage == "missing":
                        review = "⚠️ 此段为漏译，原文没有对应译文。\n" + review
                    
                    result = {
                        **item,
                        "ai_translations": integrate_result["ai_translations"],
                        "review": review,
                        "final": integrate_result["final"],
                        "edited": False,
                        "has_user_translation": False
                    }
            except Exception as e:
                # 出错时使用第一个 AI 翻译作为备选
                result = {
                    **item,
                    "ai_translations": {},
                    "review": f"[处理出错: {str(e)}]",
                    "final": source_text,  # 保留原文
                    "edited": False,
                    "has_user_translation": bool(user_trans),
                    "error": str(e)
                }
            
            with lock:
                processed += 1
                if progress_callback:
                    progress_callback(processed, len(aligned))
            
            return result
        
        # 并发处理
        print(f"\n🚀 开始处理 {len(aligned)} 个段落 (并发数: {max_workers})...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_paragraph, item): item for item in aligned}
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    processed_results.append(result)
                    if result.get("edited"):
                        results["stats"]["edited"] += 1
                    elif not result.get("has_user_translation"):
                        results["stats"]["translated_only"] += 1
                except Exception as e:
                    print(f"⚠️ 处理段落失败: {e}")
        
        # 按页码和索引排序
        processed_results.sort(key=lambda x: (x.get("page", 0), x.get("source_index", 0)))
        results["paragraphs"] = processed_results
        
        return results
    
    def generate_output_files(self, results: Dict, base_name: str) -> Dict[str, str]:
        """
        生成输出文件
        
        Returns:
            {"final": path, "review": path, "comparison": path}
        """
        output_files = {}
        model_suffix = self.editor_model.split("/")[-1].replace(".", "-")[:15]
        
        # 1. 最终译文
        final_file = self.output_dir / f"{base_name}_edited_{model_suffix}.txt"
        with open(final_file, 'w', encoding='utf-8') as f:
            f.write("┏" + "━" * 58 + "┓\n")
            f.write("┃" + "  编辑打磨后的最终译文  ".center(50) + "┃\n")
            f.write("┗" + "━" * 58 + "┛\n\n")
            
            current_page = None
            for para in results["paragraphs"]:
                page = para.get("page", 0)
                if page != current_page:
                    f.write(f"\n╔{'═' * 20} 第 {page} 页 {'═' * 20}╗\n\n")
                    current_page = page
                
                f.write(para.get("final", "") + "\n\n")
        
        output_files["final"] = str(final_file)
        
        # 2. 评审报告
        review_file = self.output_dir / f"{base_name}_review_{model_suffix}.txt"
        with open(review_file, 'w', encoding='utf-8') as f:
            f.write("┏" + "━" * 58 + "┓\n")
            f.write("┃" + "  编辑审校报告  ".center(50) + "┃\n")
            f.write("┗" + "━" * 58 + "┛\n\n")
            
            stats = results["stats"]
            f.write(f"📊 统计信息:\n")
            f.write(f"  - 总段落数: {stats['total']}\n")
            f.write(f"  - 成功对齐: {stats['matched']}\n")
            f.write(f"  - 完成编辑: {stats['edited']}\n")
            f.write(f"  - 仅AI翻译: {stats['translated_only']}\n")
            f.write(f"\n📋 对齐详情:\n")
            f.write(f"  - 跳过段落: {stats.get('skipped', 0)} (出版信息等)\n")
            f.write(f"  - 漏译段落: {stats.get('missing', 0)}\n")
            f.write(f"  - 重叠覆盖: {stats.get('overlap', 0)}\n")
            f.write(f"  - 多译文对应: {stats.get('multi_target', 0)}\n")
            f.write(f"\n{'─' * 60}\n\n")
            
            for i, para in enumerate(results["paragraphs"], 1):
                f.write(f"╔{'═' * 56}╗\n")
                f.write(f"║ 段落 {i} | 第 {para.get('page', 0)} 页 | ")
                if para.get("edited"):
                    f.write("✅ 已编辑审校\n")
                elif para.get("has_user_translation"):
                    f.write("⚠️ 有用户译文但未编辑\n")
                else:
                    f.write("📝 无用户译文，使用AI翻译\n")
                f.write(f"╚{'═' * 56}╝\n\n")
                
                # 显示对齐信息
                coverage = para.get("coverage", "")
                is_multi = para.get("is_multi_target", False)
                align_note = para.get("alignment_note", "")
                
                if coverage or is_multi or align_note:
                    f.write("【对齐信息】")
                    if coverage == "overlap":
                        f.write("🔀 重叠覆盖 ")
                    elif coverage == "missing":
                        f.write("⚠️ 漏译 ")
                    elif coverage == "partial":
                        f.write("📌 部分翻译 ")
                    elif coverage == "skip":
                        f.write("⏭️ 跳过 ")
                    if is_multi:
                        f.write(f"| 对应 {len(para.get('target_indices', []))} 个译文段落 ")
                    if align_note:
                        f.write(f"| {align_note}")
                    f.write("\n\n")
                
                # 原文摘要
                src_text = para.get("source_text", "")
                f.write(f"【原文摘要】\n{src_text[:200]}{'...' if len(src_text) > 200 else ''}\n\n")
                
                # 用户译文（如有）
                if para.get("target_text"):
                    user_text = para.get("target_text", "")
                    f.write(f"【用户译文】\n{user_text[:200]}{'...' if len(user_text) > 200 else ''}\n\n")
                
                # 评审意见
                f.write(f"【评审意见】\n{para.get('review', '无')}\n\n")
                
                f.write(f"{'─' * 60}\n\n")
        
        output_files["review"] = str(review_file)
        
        # 3. 完整对照
        comparison_file = self.output_dir / f"{base_name}_comparison_{model_suffix}.txt"
        with open(comparison_file, 'w', encoding='utf-8') as f:
            f.write("┏" + "━" * 58 + "┓\n")
            f.write("┃" + "  完整翻译对照  ".center(50) + "┃\n")
            f.write("┗" + "━" * 58 + "┛\n\n")
            
            for i, para in enumerate(results["paragraphs"], 1):
                f.write(f"╔{'═' * 56}╗\n")
                f.write(f"║ 段落 {i} - 第 {para.get('page', 0)} 页\n")
                f.write(f"╚{'═' * 56}╝\n\n")
                
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【原文】                                │\n")
                f.write("└─────────────────────────────────────────┘\n")
                f.write(para.get("source_text", "") + "\n\n")
                
                if para.get("target_text"):
                    f.write("┌─────────────────────────────────────────┐\n")
                    f.write("│ 【用户译文】                            │\n")
                    f.write("└─────────────────────────────────────────┘\n")
                    f.write(para.get("target_text", "") + "\n\n")
                
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【AI 参考译文】                         │\n")
                f.write("└─────────────────────────────────────────┘\n")
                for model, trans in para.get("ai_translations", {}).items():
                    model_display = model.split("_", 1)[-1] if "_" in model else model
                    model_short = model_display.split("/")[-1] if "/" in model_display else model_display
                    f.write(f"◆ {model_short}:\n{trans}\n\n")
                
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【评审意见】                            │\n")
                f.write("└─────────────────────────────────────────┘\n")
                f.write(para.get("review", "") + "\n\n")
                
                f.write("┌─────────────────────────────────────────┐\n")
                f.write("│ 【✨ 最终译文】                         │\n")
                f.write("└─────────────────────────────────────────┘\n")
                f.write(para.get("final", "") + "\n\n")
                
                f.write("═" * 60 + "\n\n")
        
        output_files["comparison"] = str(comparison_file)
        
        print(f"\n✨ 输出文件已生成:")
        print(f"  📄 最终译文: {final_file}")
        print(f"  📋 评审报告: {review_file}")
        print(f"  📚 完整对照: {comparison_file}")
        
        return output_files


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="编辑服务 - 对比、评审、打磨译文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python editor_service.py original.pdf translation.docx
  python editor_service.py original.pdf translation.docx --start 1 --end 10
  python editor_service.py original.pdf translation.docx --editor-model anthropic/claude-sonnet-4
        """
    )
    
    parser.add_argument("pdf_path", help="PDF 原文路径")
    parser.add_argument("word_path", help="Word 译文路径")
    parser.add_argument("--start", type=int, help="起始页码")
    parser.add_argument("--end", type=int, help="结束页码")
    parser.add_argument("--translation-models", help="翻译模型列表，逗号分隔")
    parser.add_argument("--editor-model", help="编辑模型")
    parser.add_argument("--workers", type=int, default=5, help="并发数 (默认: 5)")
    parser.add_argument("--output", default="output", help="输出目录")
    
    args = parser.parse_args()
    
    # 检查文件
    if not Path(args.pdf_path).exists():
        print(f"❌ PDF 文件不存在: {args.pdf_path}")
        return 1
    
    if not Path(args.word_path).exists():
        print(f"❌ Word 文件不存在: {args.word_path}")
        return 1
    
    # 解析模型列表
    translation_models = None
    if args.translation_models:
        translation_models = [m.strip() for m in args.translation_models.split(",")]
    
    # 创建编辑服务
    editor = EditorService(
        translation_models=translation_models,
        editor_model=args.editor_model,
        output_dir=args.output
    )
    
    # 处理文档
    def progress_callback(completed, total):
        print(f"\r⏳ 进度: {completed}/{total} ({completed/total*100:.1f}%)", end="", flush=True)
    
    results = editor.process_document(
        pdf_path=args.pdf_path,
        word_path=args.word_path,
        start_page=args.start,
        end_page=args.end,
        max_workers=args.workers,
        progress_callback=progress_callback
    )
    
    print()  # 换行
    
    # 生成输出文件
    base_name = Path(args.pdf_path).stem
    editor.generate_output_files(results, base_name)
    
    return 0


if __name__ == "__main__":
    exit(main())
