#!/usr/bin/env python3
"""
PDF文本分析工具 - 用于分析PDF中的水印、角注等重复内容
"""

import sys
from pathlib import Path
from collections import Counter
import fitz  # PyMuPDF


def analyze_pdf(pdf_path: str, num_pages: int = 10):
    """
    分析PDF前几页的文本，找出重复出现的内容（可能是水印/角注）
    
    Args:
        pdf_path: PDF文件路径
        num_pages: 分析的页数
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    pages_to_analyze = min(num_pages, total_pages)
    
    print(f"📖 PDF文件: {pdf_path}")
    print(f"📄 总页数: {total_pages}")
    print(f"🔍 分析前 {pages_to_analyze} 页...\n")
    
    # 收集每页的所有文本行
    all_lines = []
    page_lines = {}
    
    for page_num in range(pages_to_analyze):
        page = doc[page_num]
        text = page.get_text("text")
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        page_lines[page_num + 1] = lines
        all_lines.extend(lines)
    
    # 统计每行出现的次数
    line_counter = Counter(all_lines)
    
    # 找出在多页重复出现的内容（可能是水印/页眉/页脚）
    repeated_lines = {line: count for line, count in line_counter.items() 
                      if count >= pages_to_analyze * 0.5}  # 出现在50%以上的页面
    
    print("=" * 60)
    print("🔄 重复出现的内容（可能是水印/页眉/页脚）:")
    print("=" * 60)
    
    if repeated_lines:
        for line, count in sorted(repeated_lines.items(), key=lambda x: -x[1]):
            print(f"  [{count}次] {line[:80]}{'...' if len(line) > 80 else ''}")
    else:
        print("  未发现明显的重复内容")
    
    print("\n" + "=" * 60)
    print("📝 各页文本预览:")
    print("=" * 60)
    
    for page_num in range(min(5, pages_to_analyze)):  # 只显示前5页
        print(f"\n--- 第 {page_num + 1} 页 ---")
        lines = page_lines[page_num + 1]
        for i, line in enumerate(lines[:20]):  # 每页最多显示20行
            # 标记重复内容
            marker = "⚠️" if line in repeated_lines else "  "
            print(f"{marker} {line[:100]}{'...' if len(line) > 100 else ''}")
        if len(lines) > 20:
            print(f"  ... 还有 {len(lines) - 20} 行 ...")
    
    doc.close()
    
    # 返回建议过滤的内容
    print("\n" + "=" * 60)
    print("💡 建议过滤的内容:")
    print("=" * 60)
    
    suggestions = []
    for line, count in sorted(repeated_lines.items(), key=lambda x: -x[1]):
        if count >= pages_to_analyze * 0.7:  # 出现在70%以上页面的内容
            suggestions.append(line)
            print(f"  - {line[:80]}{'...' if len(line) > 80 else ''}")
    
    if not suggestions:
        print("  暂无明确建议，请根据上面的分析结果手动确定")
    
    return suggestions


def extract_with_blocks(pdf_path: str, page_num: int = 0):
    """
    使用块级提取，可以获取文本的位置信息
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    
    print(f"\n📐 第 {page_num + 1} 页的文本块位置分析:")
    print("=" * 60)
    
    # 获取页面尺寸
    rect = page.rect
    print(f"页面尺寸: {rect.width:.0f} x {rect.height:.0f}")
    
    # 定义页眉页脚区域（通常在页面顶部和底部10%的区域）
    header_threshold = rect.height * 0.1
    footer_threshold = rect.height * 0.9
    
    # 获取文本块
    blocks = page.get_text("blocks")
    
    header_blocks = []
    footer_blocks = []
    main_blocks = []
    
    for block in blocks:
        if block[6] == 0:  # 文本块
            x0, y0, x1, y1, text, block_no, block_type = block
            text = text.strip()
            if not text:
                continue
                
            if y0 < header_threshold:
                header_blocks.append((y0, text))
                print(f"📍 [页眉区 y={y0:.0f}] {text[:60]}...")
            elif y1 > footer_threshold:
                footer_blocks.append((y0, text))
                print(f"📍 [页脚区 y={y0:.0f}] {text[:60]}...")
            else:
                main_blocks.append((y0, text))
    
    print(f"\n统计: 页眉区 {len(header_blocks)} 块, 正文区 {len(main_blocks)} 块, 页脚区 {len(footer_blocks)} 块")
    
    doc.close()
    return header_blocks, main_blocks, footer_blocks


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python analyze_pdf.py <pdf文件路径> [分析页数]")
        print("示例: python analyze_pdf.py book.pdf 20")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    num_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    if not Path(pdf_path).exists():
        print(f"❌ 文件不存在: {pdf_path}")
        sys.exit(1)
    
    # 分析重复内容
    suggestions = analyze_pdf(pdf_path, num_pages)
    
    # 分析第一页的块位置
    extract_with_blocks(pdf_path, 0)
