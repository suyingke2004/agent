#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
北航AI助手批量处理示例
"""

import os
import sys
import argparse
import csv
import json
import time
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv
from tqdm import tqdm

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.assistant import AIAssistant
import config

def read_questions(file_path: str) -> List[str]:
    """
    从文件读取问题
    
    Args:
        file_path (str): 文件路径
        
    Returns:
        list: 问题列表
    """
    questions = []
    
    # 根据文件扩展名选择读取方式
    file_ext = os.path.splitext(file_path)[1].lower()
    
    try:
        if file_ext == '.csv':
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                # 尝试识别列
                header = next(reader, None)
                
                if header:
                    # 判断哪一列是问题
                    question_col = 0
                    for i, col in enumerate(header):
                        if '问题' in col or 'question' in col.lower():
                            question_col = i
                            break
                    
                    # 如果标题行就是问题，也加入
                    if not any(h.lower() in ['问题', 'question'] for h in header):
                        questions.append(header[question_col])
                    
                    # 读取其余行
                    for row in reader:
                        if row and len(row) > question_col:
                            questions.append(row[question_col])
                else:
                    print("CSV文件为空或格式错误")
        
        elif file_ext == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # 处理不同可能的JSON格式
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            questions.append(item)
                        elif isinstance(item, dict):
                            # 尝试查找可能包含问题的键
                            for key in ['question', 'prompt', 'text', 'content', 'q']:
                                if key in item:
                                    questions.append(item[key])
                                    break
                elif isinstance(data, dict):
                    # 如果是字典，查找可能包含问题列表的键
                    for key in ['questions', 'prompts', 'items', 'data']:
                        if key in data and isinstance(data[key], list):
                            for item in data[key]:
                                if isinstance(item, str):
                                    questions.append(item)
                                elif isinstance(item, dict) and 'question' in item:
                                    questions.append(item['question'])
                            break
        
        else:  # 默认按文本文件处理
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        questions.append(line)
    
    except Exception as e:
        print(f"读取问题文件出错: {str(e)}")
    
    return questions

def save_results(results: List[Dict[str, Any]], output_path: str, format_type: str) -> bool:
    """
    保存结果
    
    Args:
        results (list): 结果列表
        output_path (str): 输出文件路径
        format_type (str): 输出格式
        
    Returns:
        bool: 保存是否成功
    """
    try:
        # 如果未指定输出路径，生成默认路径
        if not output_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"output_{timestamp}.{format_type}"
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 根据格式保存
        if format_type == 'json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        
        elif format_type == 'csv':
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['问题', '回答', '时间'])
                for item in results:
                    writer.writerow([
                        item['question'], 
                        item['answer'], 
                        item['timestamp']
                    ])
        
        else:  # txt
            with open(output_path, 'w', encoding='utf-8') as f:
                for i, item in enumerate(results):
                    f.write(f"问题 {i+1}: {item['question']}\n")
                    f.write(f"回答: {item['answer']}\n")
                    f.write(f"时间: {item['timestamp']}\n")
                    f.write("-" * 80 + "\n\n")
        
        print(f"结果已保存到 {output_path}")
        return True
    
    except Exception as e:
        print(f"保存结果出错: {str(e)}")
        return False

def main():
    """主函数"""
    # 加载环境变量
    load_dotenv()
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='北航AI助手批量处理示例')
    parser.add_argument('-u', '--username', help='北航统一认证用户名（学号）')
    parser.add_argument('-p', '--password', help='北航统一认证密码')
    parser.add_argument('-t', '--type', choices=['xiaohang', 'tongyi'], 
                        default=config.ASSISTANT_CONFIG['default_assistant'],
                        help='AI助手类型：xiaohang(小航AI助手) 或 tongyi(北航通义千问)')
    parser.add_argument('-i', '--input', required=True, help='输入文件路径，支持CSV、JSON或TXT格式')
    parser.add_argument('-o', '--output', help='输出文件路径')
    parser.add_argument('-f', '--format', choices=['txt', 'csv', 'json'], default='csv',
                       help='输出格式，默认为csv')
    parser.add_argument('--delay', type=int, default=2, help='每个问题之间的延迟时间（秒），默认为2秒')
    args = parser.parse_args()
    
    # 获取凭据
    username = args.username or config.AUTH_CONFIG.get('username', '')
    password = args.password or config.AUTH_CONFIG.get('password', '')
    
    # 检查凭据
    if not username or not password:
        print("错误：缺少用户名或密码。请通过命令行参数提供，或在config.py或环境变量中设置。")
        sys.exit(1)
    
    # 检查输入文件
    if not os.path.exists(args.input):
        print(f"错误：输入文件 {args.input} 不存在")
        sys.exit(1)
    
    # 读取问题
    print(f"从 {args.input} 读取问题...")
    questions = read_questions(args.input)
    
    if not questions:
        print("没有找到问题，请检查输入文件格式")
        sys.exit(1)
    
    print(f"共读取 {len(questions)} 个问题")
    
    # 处理问题
    results = []
    
    try:
        # 初始化AI助手
        print(f"正在初始化AI助手 (类型: {args.type})...")
        assistant = AIAssistant(username=username, password=password, assistant_type=args.type)
        print("初始化成功！")
        
        # 处理每个问题
        print("\n开始处理问题：")
        for i, question in enumerate(tqdm(questions, desc="处理进度")):
            try:
                print(f"\n[{i+1}/{len(questions)}] 问题: {question[:100]}{'...' if len(question) > 100 else ''}")
                
                # 发送问题并获取回复
                response = assistant.chat(question)
                
                # 记录结果
                results.append({
                    'question': question,
                    'answer': response,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'success': True
                })
                
                # 输出回答的前200个字符
                answer_preview = response[:200] + ('...' if len(response) > 200 else '')
                print(f"回答: {answer_preview}")
                
                # 延迟一段时间，避免请求过快
                if i < len(questions) - 1 and args.delay > 0:
                    time.sleep(args.delay)
                
            except Exception as e:
                print(f"处理问题 '{question[:50]}...' 时出错: {str(e)}")
                results.append({
                    'question': question,
                    'answer': f"错误: {str(e)}",
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'success': False
                })
        
        # 保存结果
        if results:
            output_path = args.output
            if not output_path:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_path = f"output_{timestamp}.{args.format}"
            
            save_results(results, output_path, args.format)
        
        # 关闭AI助手
        assistant.close()
        
        # 输出统计信息
        success_count = sum(1 for r in results if r.get('success', False))
        print(f"\n处理完成: 共 {len(results)} 个问题，成功 {success_count} 个，失败 {len(results) - success_count} 个")
        
    except Exception as e:
        print(f"程序出错: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 