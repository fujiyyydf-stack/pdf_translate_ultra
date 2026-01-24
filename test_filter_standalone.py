#!/usr/bin/env python3
"""
独立测试脚本 - 测试PDF文本提取和过滤效果
不依赖openai等库
"""

import re
from pathlib import Path
from collections import Counter
import fitz  # PyMuPDF

# 需要过滤的水印模式
FILTER_PATTERNS = [
    r'^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}$',  # 时间戳
    r'^ÉPREUVES$',
    r'^NON$',
    r'^CORRIGÉES$',
    r'^TOUS DROITS DE REPRODUCTION',  # 版权声明
    r'^\d+AFC.*\.indd\s+\d+$',  # 文件名+页码
    r'^420601AFC.*\.indd\s+\d+$',  # 具体文件名
]

def should_filter_line(line: str, detected_watermarks: set) -> bool:
    """检查一行是否应该被过滤"""
    line = line.strip()
    if not line:
        return True
    
    # 检查自动检测到的水印
    if line in detected_watermarks:
        return True
    
    # 检查正则模式
    for pattern in FILTER_PATTERNS:
        if re.match(pattern, line, re.IGNORECASE):
            return True
    
    return False

def detect_watermarks(pdf_path: str, sample_pages: int = 30) -> set:
    """自动检测水印"""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    pages_to_check = min(sample_pages, total_pages)
    
    all_lines = []
    for page_num in range(pages_to_check):
        page = doc[page_num]
        text = page.get_text("text")
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        all_lines.extend(lines)
    
    doc.close()
    
    line_counter = Counter(all_lines)
    threshold = pages_to_check * 0.6
    
    watermarks = set()
    for line, count in line_counter.items():
        if count >= threshold and len(line) < 100:
            watermarks.add(line)
    
    return watermarks

def extract_filtered_text(pdf_path: str, header_ratio: float = 0.08, footer_ratio: float = 0.92):
    """提取并过滤PDF文本"""
    
    print("🔍 正在自动检测水印...")
    detected_watermarks = detect_watermarks(pdf_path)
    
    if detected_watermarks:
        print(f"✅ 检测到 {len(detected_watermarks)} 个水印/重复内容:")
        for wm in list(detected_watermarks):
            print(f"   - {wm[:60]}{'...' if len(wm) > 60 else ''}")
    
    doc = fitz.open(pdf_path)
    pages_text = []
    filtered_count = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        rect = page.rect
        
        header_threshold = rect.height * header_ratio
        footer_threshold = rect.height * footer_ratio
        
        blocks = page.get_text("blocks")
        page_lines = []
        
        for block in blocks:
            if block[6] == 0:  # 文本块
                x0, y0, x1, y1, text, block_no, block_type = block
                text = text.strip()
                
                if not text:
                    continue
                
                # 过滤页眉
                if y0 < header_threshold:
                    filtered_count += 1
                    continue
                
                # 过滤页脚
                if y1 > footer_threshold:
                    filtered_count += 1
                    continue
                
                # 过滤水印
                lines = text.split('\n')
                clean_lines = []
                for line in lines:
                    if not should_filter_line(line, detected_watermarks):
                        clean_lines.append(line.strip())
                    else:
                        filtered_count += 1
                
                if clean_lines:
                    page_lines.append('\n'.join(clean_lines))
        
        page_text = '\n\n'.join(page_lines)
        
        if page_text.strip():
            pages_text.append({
                "page": page_num + 1,
                "text": page_text.strip()
            })
    
    doc.close()
    return pages_text, filtered_count


def main():
    pdf_path = "/Users/changhao/Desktop/pdf_translate/420601AFC_SECRET_CC2021_PC.indd.pdf"
    
    if not Path(pdf_path).exists():
        print(f"❌ PDF文件不存在: {pdf_path}")
        return
    
    print("=" * 60)
    print("📖 测试PDF文本提取和过滤")
    print("=" * 60)
    
    pages_text, filtered_count = extract_filtered_text(pdf_path)
    
    print(f"\n✅ 成功提取 {len(pages_text)} 页文本")
    print(f"🗑️  已过滤 {filtered_count} 个水印/页眉页脚内容")
    
    print("\n" + "=" * 60)
    print("📝 过滤后的文本预览（第5-15页，正文开始部分）:")
    print("=" * 60)
    
    # 跳过前几页（通常是封面、版权页等）
    for page_data in pages_text:
        page_num = page_data["page"]
        if page_num < 5 or page_num > 15:
            continue
            
        text = page_data["text"]
        
        print(f"\n{'='*20} 第 {page_num} 页 {'='*20}")
        # 显示前800个字符
        preview = text[:800]
        if len(text) > 800:
            preview += "\n... [更多内容] ..."
        print(preview)
        print(f"\n[本页字符数: {len(text)}]")


if __name__ == "__main__":
    main()
