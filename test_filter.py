#!/usr/bin/env python3
"""测试过滤效果"""

import sys
sys.path.insert(0, '/Users/changhao/Desktop/pdf_translate')

from pdf_translator import PDFTranslator

def test_extraction():
    """测试文本提取和过滤"""
    pdf_path = "/Users/changhao/Desktop/pdf_translate/420601AFC_SECRET_CC2021_PC.indd.pdf"
    
    # 创建翻译器（不需要API key来测试提取）
    translator = PDFTranslator(
        api_key="test",  # 占位符
        auto_detect_watermarks=True
    )
    
    print("=" * 60)
    print("📖 测试PDF文本提取和过滤")
    print("=" * 60)
    
    # 提取文本
    pages_text = translator.extract_text_from_pdf(pdf_path)
    
    print(f"\n✅ 成功提取 {len(pages_text)} 页文本")
    
    # 显示前几页的内容
    print("\n" + "=" * 60)
    print("📝 过滤后的文本预览（前10页）:")
    print("=" * 60)
    
    for page_data in pages_text[:10]:
        page_num = page_data["page"]
        text = page_data["text"]
        
        print(f"\n--- 第 {page_num} 页 ---")
        # 显示前500个字符
        preview = text[:500]
        if len(text) > 500:
            preview += "\n... [更多内容] ..."
        print(preview)
        print(f"\n[本页字符数: {len(text)}]")

if __name__ == "__main__":
    test_extraction()
