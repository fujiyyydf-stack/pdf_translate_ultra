#!/usr/bin/env python3
"""
PDF翻译服务 - Flask后端
支持单模型和多模型翻译，每个模型可以有独立的提示词
"""

import os
import json
import time
import re
import fitz  # PyMuPDF
import threading
import base64
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='web', static_url_path='')
CORS(app)

# 配置
UPLOAD_FOLDER = Path('uploads')
OUTPUT_FOLDER = Path('output')
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

# 存储翻译任务状态
translation_tasks = {}


# ============================================
# API Client
# ============================================

class UnifiedAPIClient:
    """统一的API客户端"""
    
    def __init__(self, provider: str, api_key: str = None, base_url: str = None):
        self.provider = provider
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.base_url = base_url or os.getenv('OPENAI_BASE_URL')
        
        if provider == 'gemini':
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.genai = genai
        else:
            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self.client = OpenAI(**client_kwargs)
    
    def chat(self, model: str, system_prompt: str, user_message: str, max_retries: int = 3) -> str:
        """发送聊天请求"""
        for attempt in range(max_retries):
            try:
                if self.provider == 'gemini':
                    return self._gemini_chat(model, system_prompt, user_message)
                else:
                    return self._openai_chat(model, system_prompt, user_message)
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise e
    
    def _gemini_chat(self, model: str, system_prompt: str, user_message: str) -> str:
        """Gemini API调用"""
        if '/' in model:
            model = model.split('/')[-1]
        
        gemini_model = self.genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt
        )
        response = gemini_model.generate_content(user_message)
        return response.text
    
    def _openai_chat(self, model: str, system_prompt: str, user_message: str) -> str:
        """OpenAI兼容API调用"""
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content


# ============================================
# PDF Processing
# ============================================

class PDFProcessor:
    """PDF处理器"""
    
    # 水印和页脚模式
    WATERMARK_PATTERNS = [
        r'ÉPREUVES',
        r'\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}',
        r'420601AFC.*\.indd',
        r'SECRET.*\.indd',
        r'^\d+$',
        r'^Page\s+\d+',
    ]
    
    def __init__(self):
        self.watermark_re = [re.compile(p, re.IGNORECASE) for p in self.WATERMARK_PATTERNS]
    
    def _should_filter_line(self, line: str) -> bool:
        """检查是否应该过滤该行"""
        line = line.strip()
        if not line:
            return True
        if len(line) < 3:
            return True
        for pattern in self.watermark_re:
            if pattern.search(line):
                return True
        return False
    
    def extract_text(self, pdf_path: str, start_page: int = 1, end_page: int = None) -> list:
        """提取PDF文本"""
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        if end_page is None or end_page > total_pages:
            end_page = total_pages
        
        pages_data = []
        
        for page_num in range(start_page - 1, end_page):
            page = doc[page_num]
            text = page.get_text()
            
            # 过滤水印
            lines = text.split('\n')
            filtered_lines = [line for line in lines if not self._should_filter_line(line)]
            clean_text = '\n'.join(filtered_lines)
            
            # 分段
            segments = self._split_into_segments(clean_text)
            
            if segments:
                pages_data.append({
                    'page': page_num + 1,
                    'segments': segments
                })
        
        doc.close()
        return pages_data
    
    def _split_into_segments(self, text: str, max_chars: int = 2000) -> list:
        """将文本分割成段落"""
        paragraphs = re.split(r'\n\s*\n', text)
        segments = []
        current_segment = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_segment) + len(para) + 2 <= max_chars:
                if current_segment:
                    current_segment += "\n\n" + para
                else:
                    current_segment = para
            else:
                if current_segment:
                    segments.append(current_segment)
                current_segment = para
        
        if current_segment:
            segments.append(current_segment)
        
        return segments if segments else [text] if text.strip() else []


# ============================================
# Translation Service
# ============================================

class TranslationService:
    """翻译服务"""
    
    DEFAULT_SYSTEM_PROMPT = """你是一位精通法语和中文的专业翻译官。
你的任务是将输入的法语文本翻译为中文。
要求：
1. 保持翻译的学术性或文学性，语气灵动自然优雅，表达顺畅准确，确保语句结构完整，优先使用简洁句式，保证行文易懂，保证所有哲学学术术语的准确性，在你觉得重要的哲学学术术语后面加括号，在括号内标注原文并进行一到两句话的解释用于该文本的脚注。
2. 保留原有的格式（如标题、列表）。
3. 直接返回翻译后的中文内容，不要添加任何解释或说明。
"""
    
    def __init__(self, client: UnifiedAPIClient, model: str, system_prompt: str = None):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
    
    def translate_segment(self, text: str) -> str:
        """翻译单个段落"""
        return self.client.chat(self.model, self.system_prompt, text)


def get_api_client(config: dict) -> UnifiedAPIClient:
    """根据配置创建API客户端"""
    api_key = config.get('api_key') or os.getenv('OPENAI_API_KEY')
    base_url = config.get('base_url') or os.getenv('OPENAI_BASE_URL')
    return UnifiedAPIClient('openai', api_key, base_url)


# ============================================
# Translation Tasks
# ============================================

def run_translation_task(task_id: str, pdf_path: str, config: dict):
    """后台运行翻译任务"""
    try:
        task = translation_tasks[task_id]
        task['status'] = 'processing'
        task['started_at'] = datetime.now().isoformat()
        
        is_multi_model = config.get('multi_model', False)
        
        if is_multi_model:
            run_multi_model_translation(task_id, pdf_path, config)
        else:
            run_single_model_translation(task_id, pdf_path, config)
        
    except Exception as e:
        task = translation_tasks[task_id]
        task['status'] = 'error'
        task['error'] = str(e)
        import traceback
        traceback.print_exc()


def run_single_model_translation(task_id: str, pdf_path: str, config: dict):
    """单模型翻译"""
    task = translation_tasks[task_id]
    
    processor = PDFProcessor()
    client = get_api_client(config)
    system_prompt = config.get('system_prompt')
    service = TranslationService(client, config.get('model', 'gpt-4o-mini'), system_prompt)
    
    start_page = config.get('start_page', 1)
    end_page = config.get('end_page')
    pages_data = processor.extract_text(pdf_path, start_page, end_page)
    
    total_segments = sum(len(p['segments']) for p in pages_data)
    task['total_segments'] = total_segments
    task['total_pages'] = len(pages_data)
    
    results = {}
    completed = 0
    
    max_workers = config.get('workers', 5)
    
    def translate_page_segment(page_num, seg_idx, segment):
        translation = service.translate_segment(segment)
        return page_num, seg_idx, segment, translation
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for page_data in pages_data:
            page_num = page_data['page']
            results[page_num] = {'original': [], 'translated': []}
            
            for seg_idx, segment in enumerate(page_data['segments']):
                future = executor.submit(translate_page_segment, page_num, seg_idx, segment)
                futures.append(future)
        
        for future in as_completed(futures):
            try:
                page_num, seg_idx, original, translated = future.result()
                
                while len(results[page_num]['original']) <= seg_idx:
                    results[page_num]['original'].append(None)
                    results[page_num]['translated'].append(None)
                
                results[page_num]['original'][seg_idx] = original
                results[page_num]['translated'][seg_idx] = translated
                
                completed += 1
                task['completed_segments'] = completed
                task['progress'] = int(completed / total_segments * 100)
                task['current_page'] = page_num
                
            except Exception as e:
                print(f"Translation error: {e}")
    
    # 清理None值
    for page_num in results:
        results[page_num]['original'] = [s for s in results[page_num]['original'] if s]
        results[page_num]['translated'] = [s for s in results[page_num]['translated'] if s]
    
    task['results'] = results
    task['status'] = 'completed'
    task['completed_at'] = datetime.now().isoformat()
    
    output_file = OUTPUT_FOLDER / f"{task_id}_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def run_multi_model_translation(task_id: str, pdf_path: str, config: dict):
    """多模型翻译 - 每个模型可以有独立的提示词"""
    from multi_model_translator import MultiModelTranslator
    
    task = translation_tasks[task_id]
    
    translation_models = config.get('translation_models', [
        'x-ai/grok-4.1-fast',
        'x-ai/grok-4.1-fast',
        'x-ai/grok-4.1-fast'
    ])
    integration_model = config.get('integration_model', 'x-ai/grok-4.1-fast')
    
    # 获取每个模型的独立提示词
    model_prompts = config.get('model_prompts', [])
    system_prompt = config.get('system_prompt')  # 默认提示词
    integration_prompt = config.get('integration_prompt')
    
    # 创建多模型翻译器
    translator = MultiModelTranslator(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        translation_models=translation_models,
        integration_model=integration_model,
        output_dir=str(OUTPUT_FOLDER),
        system_prompt=system_prompt,
        integration_prompt=integration_prompt,
        model_prompts=model_prompts  # 传递每个模型的独立提示词
    )
    
    processor = PDFProcessor()
    start_page = config.get('start_page', 1)
    end_page = config.get('end_page')
    pages_data = processor.extract_text(pdf_path, start_page, end_page)
    
    total_segments = sum(len(p['segments']) for p in pages_data)
    task['total_segments'] = total_segments
    task['total_pages'] = len(pages_data)
    task['translation_models'] = translation_models
    task['integration_model'] = integration_model
    
    results = {}
    completed = 0
    
    max_workers = config.get('workers', 5)
    
    def translate_segment_multi(page_num, seg_idx, segment):
        """使用多模型翻译单个段落"""
        try:
            result = translator.translate_segment_with_integration(segment)
            integrated = result.get('integrated', segment)
            return page_num, seg_idx, segment, integrated
        except Exception as e:
            print(f"Multi-model translation error for segment: {e}")
            try:
                fallback = translator.translate_with_single_model(segment, translation_models[0])
                return page_num, seg_idx, segment, fallback
            except:
                return page_num, seg_idx, segment, segment
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for page_data in pages_data:
            page_num = page_data['page']
            results[page_num] = {'original': [], 'translated': []}
            
            for seg_idx, segment in enumerate(page_data['segments']):
                future = executor.submit(translate_segment_multi, page_num, seg_idx, segment)
                futures.append(future)
        
        for future in as_completed(futures):
            try:
                page_num, seg_idx, original, translated = future.result()
                
                while len(results[page_num]['original']) <= seg_idx:
                    results[page_num]['original'].append(None)
                    results[page_num]['translated'].append(None)
                
                results[page_num]['original'][seg_idx] = original
                results[page_num]['translated'][seg_idx] = translated
                
                completed += 1
                task['completed_segments'] = completed
                task['progress'] = int(completed / total_segments * 100)
                task['current_page'] = page_num
                
            except Exception as e:
                print(f"Multi-model translation error: {e}")
    
    # 清理None值
    for page_num in results:
        results[page_num]['original'] = [s for s in results[page_num]['original'] if s]
        results[page_num]['translated'] = [s for s in results[page_num]['translated'] if s]
    
    task['results'] = results
    task['status'] = 'completed'
    task['completed_at'] = datetime.now().isoformat()
    
    output_file = OUTPUT_FOLDER / f"{task_id}_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


# ============================================
# API Routes
# ============================================

@app.route('/')
def index():
    return send_from_directory('web', 'index.html')


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传PDF文件"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': '只支持PDF文件'}), 400
    
    # 生成唯一文件名
    import uuid
    file_id = str(uuid.uuid4())[:8]
    filename = f"{file_id}_{file.filename}"
    filepath = UPLOAD_FOLDER / filename
    file.save(filepath)
    
    # 获取页数
    try:
        doc = fitz.open(filepath)
        total_pages = len(doc)
        doc.close()
    except Exception as e:
        return jsonify({'error': f'无法读取PDF: {str(e)}'}), 400
    
    return jsonify({
        'file_id': file_id,
        'filename': file.filename,
        'path': str(filepath),
        'total_pages': total_pages
    })


# 自定义模型存储
custom_models = []

@app.route('/api/models', methods=['GET'])
def get_models():
    """获取可用模型列表"""
    # 预置模型（OpenRouter）
    preset_models = [
        {'id': 'x-ai/grok-4.1-fast', 'name': 'Grok 4.1 Fast', 'provider': 'openrouter'},
        {'id': 'anthropic/claude-sonnet-4', 'name': 'Claude Sonnet 4', 'provider': 'openrouter'},
        {'id': 'google/gemini-3-flash-preview', 'name': 'gemini-3-flash', 'provider': 'openrouter'},
        {'id': 'openai/gpt-oss-120b', 'name': 'gpt-oss-120b', 'provider': 'openrouter'},
        {'id': 'google/gemini-2.5-pro-preview', 'name': 'Gemini 2.5 Pro', 'provider': 'openrouter'},
        {'id': 'google/gemini-2.5-flash-preview', 'name': 'Gemini 2.5 Flash', 'provider': 'openrouter'},
    ]
    
    # 预置的火山引擎豆包模型
    volcengine_models = [
        {
            'id': 'doubao-1.5-pro-256k',
            'name': '豆包 1.5 Pro 256K',
            'provider': 'volcengine',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
            'requires_api_key': True,
            'description': '火山引擎豆包大模型，需配置火山引擎 API Key'
        },
        {
            'id': 'doubao-1.5-pro-32k',
            'name': '豆包 1.5 Pro 32K',
            'provider': 'volcengine',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
            'requires_api_key': True,
            'description': '火山引擎豆包大模型，需配置火山引擎 API Key'
        },
        {
            'id': 'doubao-pro-32k',
            'name': '豆包 Pro 32K',
            'provider': 'volcengine',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
            'requires_api_key': True,
            'description': '火山引擎豆包大模型，需配置火山引擎 API Key'
        },
    ]
    
    # DeepSeek 模型
    deepseek_models = [
        {
            'id': 'deepseek-chat',
            'name': 'DeepSeek Chat',
            'provider': 'deepseek',
            'base_url': 'https://api.deepseek.com/v1',
            'requires_api_key': True,
            'description': 'DeepSeek 官方 API'
        },
        {
            'id': 'deepseek-reasoner',
            'name': 'DeepSeek Reasoner',
            'provider': 'deepseek',
            'base_url': 'https://api.deepseek.com/v1',
            'requires_api_key': True,
            'description': 'DeepSeek R1 推理模型'
        },
    ]
    
    return jsonify({
        'models': preset_models,
        'volcengine_models': volcengine_models,
        'deepseek_models': deepseek_models,
        'custom_models': custom_models
    })


@app.route('/api/models/custom', methods=['POST'])
def add_custom_model():
    """添加自定义模型"""
    data = request.json
    
    if not data.get('model'):
        return jsonify({'error': '缺少模型名称'}), 400
    
    model_config = {
        'id': data.get('id', data['model']),
        'model': data['model'],
        'name': data.get('name', data['model']),
        'provider': data.get('provider', 'custom'),
        'base_url': data.get('base_url', ''),
        'api_key': data.get('api_key', ''),  # 注意：生产环境不应明文存储
        'description': data.get('description', '自定义模型')
    }
    
    # 检查是否已存在
    existing = next((m for m in custom_models if m['id'] == model_config['id']), None)
    if existing:
        custom_models.remove(existing)
    
    custom_models.append(model_config)
    
    return jsonify({
        'success': True,
        'model': model_config
    })


@app.route('/api/models/custom/<model_id>', methods=['DELETE'])
def delete_custom_model(model_id):
    """删除自定义模型"""
    global custom_models
    custom_models = [m for m in custom_models if m['id'] != model_id]
    return jsonify({'success': True})


@app.route('/api/translate', methods=['POST'])
def start_translation():
    """开始翻译任务"""
    data = request.json
    
    if not data.get('pdf_path'):
        return jsonify({'error': '缺少PDF路径'}), 400
    
    import uuid
    task_id = str(uuid.uuid4())[:8]
    
    translation_tasks[task_id] = {
        'id': task_id,
        'status': 'pending',
        'progress': 0,
        'total_segments': 0,
        'completed_segments': 0,
        'current_page': 0,
        'total_pages': 0,
        'results': None,
        'error': None,
        'created_at': datetime.now().isoformat()
    }
    
    # 在后台线程运行翻译
    thread = threading.Thread(
        target=run_translation_task,
        args=(task_id, data['pdf_path'], data)
    )
    thread.start()
    
    return jsonify({'task_id': task_id})


@app.route('/api/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    task = translation_tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    
    return jsonify({
        'id': task['id'],
        'status': task['status'],
        'progress': task['progress'],
        'total_segments': task['total_segments'],
        'completed_segments': task['completed_segments'],
        'current_page': task['current_page'],
        'total_pages': task['total_pages'],
        'error': task.get('error')
    })


@app.route('/api/task/<task_id>/results', methods=['GET'])
def get_task_results(task_id):
    """获取任务结果"""
    task = translation_tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    
    if task['status'] != 'completed':
        return jsonify({'error': '任务未完成'}), 400
    
    return jsonify(task['results'])


@app.route('/api/pdf/<file_id>/page/<int:page_num>', methods=['GET'])
def get_pdf_page(file_id, page_num):
    """获取PDF页面图片"""
    # 查找文件
    pdf_file = None
    for f in UPLOAD_FOLDER.iterdir():
        if f.name.startswith(file_id) and f.suffix.lower() == '.pdf':
            pdf_file = f
            break
    
    if not pdf_file:
        return jsonify({'error': '文件不存在'}), 404
    
    try:
        doc = fitz.open(pdf_file)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return jsonify({'error': '页码超出范围'}), 400
        
        page = doc[page_num - 1]
        
        # 渲染为图片
        mat = fitz.Matrix(2, 2)  # 2x缩放
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        
        doc.close()
        
        # 转为base64
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        
        return jsonify({
            'image': f'data:image/png;base64,{img_base64}',
            'page': page_num
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/txt', methods=['POST'])
def export_txt():
    """导出TXT文件"""
    data = request.json
    results = data.get('results', {})
    filename = data.get('filename', 'translation')
    
    content = ''
    for page_num in sorted(results.keys(), key=int):
        page_data = results[page_num]
        content += f'\n========== 第 {page_num} 页 ==========\n\n'
        for text in page_data.get('translated', []):
            content += text + '\n\n'
    
    return jsonify({
        'content': content,
        'filename': f'{filename}.txt'
    })


@app.route('/api/export/md', methods=['POST'])
def export_md():
    """导出Markdown文件"""
    data = request.json
    results = data.get('results', {})
    filename = data.get('filename', 'translation')
    bilingual = data.get('bilingual', False)
    
    content = f'# {filename}\n\n'
    
    for page_num in sorted(results.keys(), key=int):
        page_data = results[page_num]
        content += f'\n## 第 {page_num} 页\n\n'
        
        if bilingual:
            original = page_data.get('original', [])
            translated = page_data.get('translated', [])
            for i, (orig, trans) in enumerate(zip(original, translated)):
                content += f'> {orig}\n\n{trans}\n\n---\n\n'
        else:
            for text in page_data.get('translated', []):
                content += text + '\n\n'
    
    return jsonify({
        'content': content,
        'filename': f'{filename}.md'
    })


@app.route('/api/export/pdf', methods=['POST'])
def export_pdf():
    """导出PDF文件"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return jsonify({'error': 'reportlab未安装'}), 500
    
    data = request.json
    results = data.get('results', {})
    filename = data.get('filename', 'translation')
    
    # 创建PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                           leftMargin=2*cm, rightMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    
    # 尝试注册中文字体
    try:
        # macOS 系统字体
        font_paths = [
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Light.ttc',
            '/Library/Fonts/Arial Unicode.ttf',
        ]
        font_registered = False
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('Chinese', font_path))
                    font_registered = True
                    break
                except:
                    continue
        
        if font_registered:
            chinese_style = ParagraphStyle(
                'Chinese',
                parent=styles['Normal'],
                fontName='Chinese',
                fontSize=11,
                leading=18,
            )
        else:
            chinese_style = styles['Normal']
    except:
        chinese_style = styles['Normal']
    
    story = []
    
    for page_num in sorted(results.keys(), key=int):
        page_data = results[page_num]
        
        # 页码标题
        story.append(Paragraph(f'<b>第 {page_num} 页</b>', styles['Heading2']))
        story.append(Spacer(1, 0.5*cm))
        
        for text in page_data.get('translated', []):
            # 处理特殊字符
            text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            try:
                story.append(Paragraph(text, chinese_style))
            except:
                story.append(Paragraph(text, styles['Normal']))
            story.append(Spacer(1, 0.3*cm))
    
    try:
        doc.build(story)
    except Exception as e:
        return jsonify({'error': f'PDF生成失败: {str(e)}'}), 500
    
    pdf_data = buffer.getvalue()
    buffer.close()
    
    pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
    
    return jsonify({
        'content': pdf_base64,
        'filename': f'{filename}.pdf'
    })


# ============================================
# Editor Mode Routes
# ============================================

@app.route('/api/editor/upload-word', methods=['POST'])
def upload_word():
    """上传 Word 译文文件"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
    
    if not file.filename.lower().endswith(('.docx', '.doc')):
        return jsonify({'error': '只支持 Word 文件 (.docx)'}), 400
    
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
        stats = processor.get_document_stats(str(filepath))
    except Exception as e:
        return jsonify({'error': f'无法读取 Word 文件: {str(e)}'}), 400
    
    return jsonify({
        'file_id': file_id,
        'filename': file.filename,
        'path': str(filepath),
        'paragraph_count': para_count,
        'stats': stats
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
        'output_files': None,
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
        task['started_at'] = datetime.now().isoformat()
        
        from editor_service import EditorService
        
        # 解析翻译模型配置
        # 支持两种格式:
        # 1. 字符串列表: ["model1", "model2"]
        # 2. 配置列表: [{"model": "...", "base_url": "...", "api_key": "...", "name": "..."}, ...]
        translation_models = config.get('translation_models')
        if isinstance(translation_models, str):
            translation_models = [m.strip() for m in translation_models.split(',')]
        
        # 解析编辑模型配置
        editor_model = config.get('editor_model', 'x-ai/grok-4.1-fast')
        
        # 解析对齐模型配置
        alignment_model = config.get('alignment_model', 'x-ai/grok-4.1-fast')
        
        # 获取默认 API 配置
        default_api_key = config.get('api_key', os.getenv('OPENAI_API_KEY'))
        default_base_url = config.get('base_url', os.getenv('OPENAI_BASE_URL'))
        
        editor = EditorService(
            api_key=default_api_key,
            base_url=default_base_url,
            translation_models=translation_models,
            editor_model=editor_model,
            editor_prompt=config.get('editor_prompt'),
            translation_prompts=config.get('translation_prompts'),
            alignment_model=alignment_model,
            use_smart_alignment=config.get('use_smart_alignment', True),
            output_dir=str(OUTPUT_FOLDER)
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


@app.route('/api/editor/task/<task_id>', methods=['GET'])
def get_editor_task_status(task_id):
    """获取编辑任务状态"""
    task = translation_tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    
    return jsonify({
        'id': task['id'],
        'type': task.get('type', 'editor'),
        'status': task['status'],
        'progress': task['progress'],
        'total_paragraphs': task.get('total_paragraphs', 0),
        'completed_paragraphs': task.get('completed_paragraphs', 0),
        'error': task.get('error'),
        'output_files': task.get('output_files')
    })


@app.route('/api/editor/task/<task_id>/results', methods=['GET'])
def get_editor_task_results(task_id):
    """获取编辑任务结果"""
    task = translation_tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    
    if task['status'] != 'completed':
        return jsonify({'error': '任务未完成'}), 400
    
    results = task.get('results', {})
    
    # 转换为前端友好的格式
    paragraphs = []
    for para in results.get('paragraphs', []):
        paragraphs.append({
            'page': para.get('page', 0),
            'source_index': para.get('source_index', 0),
            'source_text': para.get('source_text', ''),
            'user_translation': para.get('target_text', ''),
            'ai_translations': para.get('ai_translations', {}),
            'review': para.get('review', ''),
            'final': para.get('final', ''),
            'matched': para.get('matched', False),
            'edited': para.get('edited', False),
            'confidence': para.get('confidence', 0)
        })
    
    return jsonify({
        'paragraphs': paragraphs,
        'stats': results.get('stats', {}),
        'output_files': task.get('output_files', {})
    })


@app.route('/api/editor/prompts', methods=['GET'])
def get_editor_prompts():
    """获取默认编辑提示词"""
    from editor_service import EditorService
    
    return jsonify({
        'editor_prompt': EditorService.DEFAULT_EDITOR_PROMPT,
        'translation_prompt': EditorService.DEFAULT_TRANSLATION_PROMPT,
        'integration_prompt': EditorService.DEFAULT_INTEGRATION_PROMPT
    })


if __name__ == '__main__':
    print("=" * 50)
    print("PDF翻译服务启动中...")
    print("访问地址: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)
