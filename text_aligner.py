#!/usr/bin/env python3
"""
文本对齐模块
功能：将 PDF 原文段落与 Word 译文段落进行对齐匹配
支持：基于规则的对齐 和 基于大模型的智能对齐
"""

import re
import os
import json
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class TextAligner:
    """文本段落对齐器"""
    
    # 智能对齐提示词
    ALIGNMENT_PROMPT = """你是一个专业的翻译文本对齐专家。你的任务是分析法语原文和中文译文，找出它们的对应关系。

## 输入说明
- 你会收到一系列编号的法语原文段落
- 你会收到一系列编号的中文译文段落
- 注意：这只是文档的一部分，译文窗口可能不够完整，有些原文的译文可能在后续段落中
- 原文和译文可能不是一一对应的，存在以下复杂情况：
  - 一个译文对应多个原文（译者合并翻译）
  - 一个原文对应多个译文（译者拆分翻译）
  - 多个译文可能有重叠（同一原文被多个译文部分覆盖）
  - 有的原文可能没有被翻译（漏译）
  - 有的译文可能是译者添加的（原文没有）

## 任务
1. 分析每个原文段落对应哪个（或哪些）译文段落
2. 对于没有找到译文的原文，判断是"真的漏译"还是"译文可能在后面"
3. 识别漏译和译者添加的内容

## 输出格式（严格遵守JSON格式）
```json
{
  "source_to_translation": [
    {"source_id": 1, "translation_ids": [1], "status": "matched", "confidence": "high"},
    {"source_id": 2, "translation_ids": [2], "status": "matched", "confidence": "high"},
    {"source_id": 3, "translation_ids": [], "status": "not_found_maybe_later", "reason": "内容看起来应该有译文，可能在后面"},
    {"source_id": 4, "translation_ids": [], "status": "not_found_skip", "reason": "出版信息/页眉页脚，通常不翻译"},
    {"source_id": 5, "translation_ids": [], "status": "missing", "reason": "正文内容但确实没找到译文，可能漏译"}
  ],
  "unmatched_translations": [4, 5],
  "window_status": {
    "all_sources_covered": false,
    "need_expand_window": true,
    "uncovered_sources": [3],
    "suggestion": "原文3的译文可能在当前窗口之后，建议扩大译文窗口"
  }
}
```

## status 说明
- matched: 已找到对应译文
- not_found_maybe_later: 没找到，但内容看起来应该有译文，可能在后续段落
- not_found_skip: 没找到，但这类内容通常不需要翻译（如出版信息、页眉页脚）
- missing: 确定是漏译（正文内容但没有译文）

## 判断"译文可能在后面"的依据
1. 原文是正文内容（不是页眉页脚、出版信息）
2. 原文内容完整，不像是残缺片段
3. 当前译文窗口的最后几段译文，内容上还没有覆盖到这个原文
4. 通常翻译是按顺序的，如果后面的原文都找到了译文，前面没找到的可能就是漏译

## 判断依据
1. 内容语义匹配：译文是否表达了原文的意思
2. 数字/专有名词：原文和译文中的数字、人名、地名应该一致
3. 段落结构：段落的长度和复杂度应该大致匹配
4. 顺序一致性：通常翻译会保持原文的顺序

请仔细分析以下文本并输出JSON结果："""

    def __init__(
        self, 
        similarity_threshold: float = 0.25,
        api_key: str = None,
        base_url: str = None,
        alignment_model: str = "x-ai/grok-4.1-fast"
    ):
        """
        Args:
            similarity_threshold: 相似度阈值（用于规则对齐）
            api_key: API 密钥（用于智能对齐）
            base_url: API 基础 URL
            alignment_model: 用于对齐的模型
        """
        self.similarity_threshold = similarity_threshold
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.alignment_model = alignment_model
        
        # 初始化 API 客户端
        if self.api_key:
            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self.client = OpenAI(**client_kwargs)
        else:
            self.client = None
    
    def smart_align(
        self,
        source_paragraphs: List[Dict],
        target_paragraphs: List[Dict],
        source_window: int = 5,      # 原文小窗口
        target_window: int = 30,     # 译文大窗口
        overlap: int = 3,            # 重叠段落数
        max_retry: int = 2           # 最大重试次数（扩大窗口）
    ) -> List[Dict]:
        """
        使用滑动窗口 + 大模型进行智能对齐（带容错机制）
        
        策略：
        - 原文用小窗口（5段），译文用大窗口（30段）
        - 找到匹配后，原文窗口滑动，译文窗口根据匹配位置调整
        - 如果大模型判断"译文可能在后面"，保留这些原文到下一批，并扩大译文窗口
        - 边界保留重叠，确保连续性
        
        Args:
            source_paragraphs: 原文段落列表
            target_paragraphs: 译文段落列表
            source_window: 原文窗口大小（默认5）
            target_window: 译文窗口大小（默认30）
            overlap: 窗口重叠段落数（默认3）
            max_retry: 扩大窗口的最大重试次数
        """
        if not self.client:
            print("⚠️ 未配置 API，使用规则对齐")
            return self.align_paragraphs(source_paragraphs, target_paragraphs)
        
        total_sources = len(source_paragraphs)
        total_targets = len(target_paragraphs)
        
        print(f"📊 开始智能对齐: {total_sources} 个原文段落, {total_targets} 个译文段落")
        print(f"   窗口设置: 原文窗口={source_window}, 译文窗口={target_window}, 重叠={overlap}")
        
        # 存储所有对齐结果 {source_id: {target_ids, confidence, status, note}}
        all_alignments = {}
        
        # 需要在下一批重试的原文ID（"可能在后面"的）
        retry_source_ids = set()
        
        # 滑动窗口索引
        src_start = 0
        tgt_start = 0
        batch_num = 0
        current_target_window = target_window  # 当前译文窗口大小（可能扩大）
        
        while src_start < total_sources:
            batch_num += 1
            
            # 获取当前原文窗口（包括需要重试的）
            src_end = min(src_start + source_window, total_sources)
            
            # 构建批次原文：需要重试的 + 新的原文
            batch_source_ids = []
            batch_sources = []
            
            # 先加入需要重试的原文
            for retry_id in sorted(retry_source_ids):
                if retry_id <= total_sources:
                    batch_source_ids.append(retry_id)
                    batch_sources.append(source_paragraphs[retry_id - 1])
            
            # 再加入新窗口的原文
            for i in range(src_start, src_end):
                src_id = i + 1
                if src_id not in retry_source_ids:
                    batch_source_ids.append(src_id)
                    batch_sources.append(source_paragraphs[i])
            
            if not batch_sources:
                break
            
            # 获取当前译文窗口（可能扩大）
            tgt_end = min(tgt_start + current_target_window, total_targets)
            batch_targets = target_paragraphs[tgt_start:tgt_end]
            
            retry_info = f" (含 {len(retry_source_ids)} 个重试)" if retry_source_ids else ""
            print(f"  批次 {batch_num}: 原文 {batch_source_ids}{retry_info} 在译文 [{tgt_start+1}-{tgt_end}] 中查找")
            
            # 调用大模型进行对齐
            batch_result = self._align_batch_with_llm(
                batch_sources, 
                batch_targets,
                source_ids=batch_source_ids,  # 传入实际的原文ID
                target_offset=tgt_start
            )
            
            # 解析对齐结果
            s2t_list = batch_result.get("source_to_translation", [])
            window_status = batch_result.get("window_status", {})
            
            # 兼容旧格式
            if not s2t_list:
                t2s_list = batch_result.get("translation_to_source", batch_result.get("alignments", []))
                if t2s_list:
                    s2t_map = {}
                    for t2s in t2s_list:
                        tgt_id = t2s.get("translation_id", 0)
                        for src_id in t2s.get("source_ids", []):
                            if src_id not in s2t_map:
                                s2t_map[src_id] = {
                                    "source_id": src_id,
                                    "translation_ids": [],
                                    "status": "matched",
                                    "confidence": t2s.get("confidence", "medium")
                                }
                            s2t_map[src_id]["translation_ids"].append(tgt_id)
                    s2t_list = list(s2t_map.values())
            
            # 清空重试集合，准备重新收集
            retry_source_ids.clear()
            
            # 收集本批次的对齐结果
            max_matched_target = tgt_start  # 记录匹配到的最大译文位置
            need_expand = False
            
            for s2t in s2t_list:
                src_id = s2t.get("source_id", 0)
                tgt_ids = s2t.get("translation_ids", s2t.get("target_ids", []))
                status = s2t.get("status", "matched" if tgt_ids else "missing")
                confidence = s2t.get("confidence", "medium")
                reason = s2t.get("reason", "")
                
                if status == "matched" and tgt_ids:
                    # 已匹配
                    if src_id not in all_alignments:
                        all_alignments[src_id] = {
                            "target_ids": set(tgt_ids),
                            "confidence": confidence,
                            "status": "matched",
                            "note": reason
                        }
                    else:
                        all_alignments[src_id]["target_ids"].update(tgt_ids)
                    
                    # 更新最大匹配位置
                    for tid in tgt_ids:
                        if tid > max_matched_target:
                            max_matched_target = tid
                
                elif status == "not_found_maybe_later":
                    # 可能在后面，加入重试集合
                    retry_source_ids.add(src_id)
                    need_expand = True
                    print(f"    ⏳ 原文{src_id}: 可能在后面 - {reason}")
                
                elif status == "not_found_skip":
                    # 不需要翻译的内容（出版信息等），标记为跳过
                    all_alignments[src_id] = {
                        "target_ids": set(),
                        "confidence": "high",
                        "status": "skip",
                        "note": reason or "出版信息/页眉页脚"
                    }
                    print(f"    ⏭️ 原文{src_id}: 跳过 - {reason}")
                
                else:  # missing 或其他
                    # 确认漏译
                    all_alignments[src_id] = {
                        "target_ids": set(),
                        "confidence": "low",
                        "status": "missing",
                        "note": reason or "漏译"
                    }
                    print(f"    ⚠️ 原文{src_id}: 漏译 - {reason}")
            
            # 检查 window_status
            if window_status.get("need_expand_window"):
                uncovered = window_status.get("uncovered_sources", [])
                for sid in uncovered:
                    if sid not in all_alignments or all_alignments.get(sid, {}).get("status") != "matched":
                        retry_source_ids.add(sid)
                        need_expand = True
            
            # 滑动原文窗口（跳过已处理和需要重试的）
            src_start = src_end
            
            # 滑动译文窗口：根据匹配到的最右侧边界 + 重叠
            # 新的左边界 = 最大匹配位置 - overlap（保留重叠容错）
            if max_matched_target > tgt_start:
                # 有新的匹配，根据匹配位置滑动
                new_tgt_start = max(max_matched_target - overlap, tgt_start)
                if new_tgt_start > tgt_start:
                    print(f"    📍 译文窗口滑动: {tgt_start+1} → {new_tgt_start+1} (最右匹配: 译文{max_matched_target})")
                    tgt_start = new_tgt_start
            # 如果没有匹配（可能是出版信息等跳过的部分），保持 tgt_start 不变
            
            # 如果需要扩大窗口，增加译文窗口大小
            if need_expand and retry_source_ids:
                current_target_window = min(target_window * 2, 60)  # 最大扩到60
                print(f"    🔄 扩大译文窗口到 {current_target_window}，{len(retry_source_ids)} 个原文待重试")
            else:
                current_target_window = target_window  # 恢复默认
            
            # 如果译文窗口已经接近末尾但还有重试的原文
            if tgt_end >= total_targets and retry_source_ids:
                print(f"  ⚠️ 译文已到末尾，{len(retry_source_ids)} 个原文仍未匹配，标记为漏译")
                for sid in retry_source_ids:
                    if sid not in all_alignments:
                        all_alignments[sid] = {
                            "target_ids": set(),
                            "confidence": "low",
                            "status": "missing",
                            "note": "译文窗口已到末尾仍未找到"
                        }
                retry_source_ids.clear()
        
        # 处理最后剩余的重试原文
        for sid in retry_source_ids:
            if sid not in all_alignments:
                all_alignments[sid] = {
                    "target_ids": set(),
                    "confidence": "low",
                    "status": "missing",
                    "note": "最终未找到对应译文"
                }
        
        print(f"✅ 对齐完成，共处理 {batch_num} 个批次，得到 {len(all_alignments)} 个对齐结果")
        
        # 统计
        matched = sum(1 for a in all_alignments.values() if a["status"] == "matched")
        skipped = sum(1 for a in all_alignments.values() if a["status"] == "skip")
        missing = sum(1 for a in all_alignments.values() if a["status"] == "missing")
        print(f"   匹配: {matched}, 跳过: {skipped}, 漏译: {missing}")
        
        # 转换为标准格式
        return self._convert_alignments_to_standard(
            all_alignments,
            source_paragraphs,
            target_paragraphs
        )
    
    def _convert_alignments_to_standard(
        self,
        alignments: Dict,  # {source_id: {target_ids, confidence, status, note}}
        source_paragraphs: List[Dict],
        target_paragraphs: List[Dict]
    ) -> List[Dict]:
        """
        将对齐结果转换为标准输出格式
        """
        result = []
        
        # 遍历每个原文段落
        for src_idx, src_para in enumerate(source_paragraphs):
            src_id = src_idx + 1  # 1-based
            src_text = src_para.get("text", "")
            src_page = src_para.get("page", 1)
            
            align = alignments.get(src_id, {})
            tgt_ids = list(align.get("target_ids", set())) if align else []
            status = align.get("status", "missing") if align else "missing"
            note = align.get("note", "")
            
            if status == "matched" and tgt_ids:
                # 有匹配的译文
                matched_texts = []
                valid_tgt_indices = []
                
                for tid in sorted(tgt_ids):
                    tgt_idx = tid - 1  # 0-based
                    if 0 <= tgt_idx < len(target_paragraphs):
                        matched_texts.append(target_paragraphs[tgt_idx].get("text", ""))
                        valid_tgt_indices.append(tgt_idx)
                
                # 合并译文
                combined_text = "\n\n".join(matched_texts) if matched_texts else ""
                
                # 确定 coverage
                coverage = "full"
                if len(valid_tgt_indices) > 1:
                    coverage = "overlap"
                
                result.append({
                    "source_index": src_idx,
                    "target_index": valid_tgt_indices[0] if valid_tgt_indices else None,
                    "target_indices": valid_tgt_indices,
                    "source_text": src_text,
                    "target_text": combined_text,
                    "confidence": {"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                        align.get("confidence", "medium"), 0.6
                    ),
                    "page": src_page,
                    "matched": True,
                    "coverage": coverage,
                    "alignment_note": note,
                    "is_multi_target": len(valid_tgt_indices) > 1
                })
            
            elif status == "skip":
                # 不需要翻译的内容（出版信息等）
                result.append({
                    "source_index": src_idx,
                    "target_index": None,
                    "target_indices": [],
                    "source_text": src_text,
                    "target_text": None,
                    "confidence": 0.9,  # 高置信度跳过
                    "page": src_page,
                    "matched": False,
                    "coverage": "skip",
                    "alignment_note": note or "出版信息/页眉页脚，无需翻译",
                    "is_multi_target": False
                })
            
            else:
                # 漏译或未找到
                result.append({
                    "source_index": src_idx,
                    "target_index": None,
                    "target_indices": [],
                    "source_text": src_text,
                    "target_text": None,
                    "confidence": 0,
                    "page": src_page,
                    "matched": False,
                    "coverage": "missing",
                    "alignment_note": note or "原文缺少对应译文（漏译）",
                    "is_multi_target": False
                })
        
        return result
    
    def _align_batch_with_llm(
        self,
        source_batch: List[Dict],
        target_batch: List[Dict],
        source_ids: List[int] = None,  # 原文的实际ID列表
        target_offset: int = 0
    ) -> Dict:
        """
        使用大模型对齐一个批次的段落
        
        Args:
            source_batch: 原文段落列表
            target_batch: 译文段落列表
            source_ids: 原文的实际ID列表（支持非连续，如 [1,2,5,6]）
            target_offset: 译文的偏移量
        """
        # 构建提示
        prompt = self.ALIGNMENT_PROMPT + "\n\n"
        
        prompt += "## 法语原文段落\n\n"
        for i, para in enumerate(source_batch):
            # 使用传入的ID或计算
            src_id = source_ids[i] if source_ids else (i + 1)
            text = para.get("text", "")[:500]  # 限制长度
            page = para.get("page", "?")
            prompt += f"[原文{src_id}] (第{page}页)\n{text}\n\n"
        
        prompt += "\n## 中文译文段落\n\n"
        for i, para in enumerate(target_batch):
            tgt_id = target_offset + i + 1
            text = para.get("text", "")[:500]
            prompt += f"[译文{tgt_id}]\n{text}\n\n"
        
        prompt += "\n请严格按照上述 JSON 格式输出对齐结果，特别注意区分 status 的几种情况："
        prompt += "\n- matched: 找到对应译文"
        prompt += "\n- not_found_maybe_later: 没找到但可能在后面"
        prompt += "\n- not_found_skip: 出版信息等不需要翻译"
        prompt += "\n- missing: 确认漏译"
        
        try:
            response = self.client.chat.completions.create(
                model=self.alignment_model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=3000
            )
            
            result_text = response.choices[0].message.content
            
            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                result = json.loads(json_match.group())
                # 确保结果包含必要字段
                if "source_to_translation" not in result:
                    result["source_to_translation"] = []
                if "window_status" not in result:
                    result["window_status"] = {}
                return result
            else:
                print(f"    警告: 无法解析对齐结果")
                return {"source_to_translation": [], "window_status": {}}
                
        except Exception as e:
            print(f"    对齐调用失败: {e}")
            return {"source_to_translation": [], "window_status": {}}
    
    def align_paragraphs(
        self, 
        source_paragraphs: List[Dict],
        target_paragraphs: List[Dict]
    ) -> List[Dict]:
        """
        基于规则的段落对齐（备用方法）
        """
        aligned = []
        target_idx = 0
        used_targets = set()
        
        for src_idx, src_para in enumerate(source_paragraphs):
            src_text = src_para.get("text", "")
            src_page = src_para.get("page", 1)
            
            best_match = None
            best_confidence = 0
            best_target_idx = None
            
            # 搜索范围
            search_start = max(0, target_idx - 2)
            search_end = min(len(target_paragraphs), target_idx + 8)
            
            for t_idx in range(search_start, search_end):
                if t_idx in used_targets:
                    continue
                    
                tgt_para = target_paragraphs[t_idx]
                tgt_text = tgt_para.get("text", "")
                
                confidence = self._calculate_match_confidence(
                    src_text, tgt_text, 
                    position_diff=abs(t_idx - target_idx)
                )
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_target_idx = t_idx
                    best_match = {
                        "target_index": t_idx,
                        "target_text": tgt_text
                    }
            
            if best_match and best_confidence >= self.similarity_threshold:
                aligned.append({
                    "source_index": src_idx,
                    "target_index": best_match["target_index"],
                    "source_text": src_text,
                    "target_text": best_match["target_text"],
                    "confidence": round(best_confidence, 3),
                    "page": src_page,
                    "matched": True
                })
                used_targets.add(best_target_idx)
                target_idx = best_target_idx + 1
            else:
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
    
    def _calculate_match_confidence(
        self, 
        source: str, 
        target: str,
        position_diff: int = 0
    ) -> float:
        """计算匹配置信度"""
        if not source or not target:
            return 0.0
        
        scores = []
        weights = []
        
        # 长度比例
        src_len = len(source)
        tgt_len = len(target)
        ratio = tgt_len / src_len if src_len > 0 else 0
        
        if 0.25 <= ratio <= 1.0:
            length_score = 1.0 - abs(ratio - 0.55) / 0.45
        elif ratio < 0.25:
            length_score = ratio / 0.25 * 0.5
        else:
            length_score = max(0, 1.0 - (ratio - 1.0) / 2)
        
        scores.append(length_score)
        weights.append(0.35)
        
        # 数字匹配
        src_numbers = set(re.findall(r'\d+', source))
        tgt_numbers = set(re.findall(r'\d+', target))
        if src_numbers:
            common = src_numbers & tgt_numbers
            number_score = len(common) / len(src_numbers)
        else:
            number_score = 1.0
        
        scores.append(number_score)
        weights.append(0.25)
        
        # 位置距离
        position_score = max(0, 1.0 - position_diff * 0.15)
        scores.append(position_score)
        weights.append(0.2)
        
        # 专有名词匹配
        src_caps = set(re.findall(r'\b[A-Z][A-Za-z]*\b', source))
        tgt_caps = set(re.findall(r'\b[A-Z][A-Za-z]*\b', target))
        if src_caps:
            caps_common = src_caps & tgt_caps
            caps_score = len(caps_common) / len(src_caps)
        else:
            caps_score = 1.0
        
        scores.append(caps_score)
        weights.append(0.2)
        
        return sum(s * w for s, w in zip(scores, weights))
    
    def calculate_alignment_quality(self, aligned: List[Dict]) -> Dict:
        """计算对齐质量统计"""
        total = len(aligned)
        matched = sum(1 for a in aligned if a.get("matched"))
        avg_confidence = sum(a.get("confidence", 0) for a in aligned) / total if total > 0 else 0
        
        high_conf = sum(1 for a in aligned if a.get("confidence", 0) >= 0.7)
        medium_conf = sum(1 for a in aligned if 0.4 <= a.get("confidence", 0) < 0.7)
        low_conf = sum(1 for a in aligned if 0 < a.get("confidence", 0) < 0.4)
        
        return {
            "total_paragraphs": total,
            "matched_paragraphs": matched,
            "match_rate": matched / total if total > 0 else 0,
            "average_confidence": round(avg_confidence, 3),
            "high_confidence_count": high_conf,
            "medium_confidence_count": medium_conf,
            "low_confidence_count": low_conf,
            "unmatched_count": total - matched
        }


def test_aligner():
    """测试对齐功能"""
    source_paragraphs = [
        {"text": "Bonjour, comment allez-vous aujourd'hui?", "page": 1},
        {"text": "Il fait beau aujourd'hui. Le soleil brille.", "page": 1},
        {"text": "J'aime lire des livres de philosophie.", "page": 2},
    ]
    
    target_paragraphs = [
        {"text": "你好，今天过得怎么样？", "index": 0},
        {"text": "今天天气很好。阳光明媚。", "index": 1},
        {"text": "我喜欢阅读哲学书籍。", "index": 2},
    ]
    
    aligner = TextAligner()
    
    # 测试规则对齐
    print("\n📊 规则对齐结果:")
    aligned = aligner.align_paragraphs(source_paragraphs, target_paragraphs)
    for item in aligned:
        status = "✅" if item["matched"] else "❌"
        conf = item["confidence"]
        src_preview = item['source_text'][:30]
        tgt_preview = item['target_text'][:20] if item['target_text'] else 'N/A'
        print(f"{status} [{conf:.2f}] {src_preview}... -> {tgt_preview}...")
    
    quality = aligner.calculate_alignment_quality(aligned)
    print(f"\n📈 对齐质量: 匹配率 {quality['match_rate']:.1%}")


if __name__ == "__main__":
    test_aligner()
