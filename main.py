#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
北航AI助手自动访问工具 - 主程序入口
"""

import os
import sys
import argparse
import logging
import json
from datetime import datetime

# 确保可以导入src模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入项目模块
from src.assistant import AIAssistant
from src.utils.logger import setup_logger
import config

def setup_directories():
    """创建必要的目录"""
    dirs = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads'),
    ]
    
    for directory in dirs:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"创建目录: {directory}")

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='北航AI助手自动访问工具')
    
    # 基本参数
    parser.add_argument('-u', '--username', help='北航统一认证用户名（学号）')
    parser.add_argument('-p', '--password', help='北航统一认证密码')
    parser.add_argument('-t', '--type', choices=['xiaohang', 'tongyi'], default=config.ASSISTANT_CONFIG['default_assistant'],
                        help='AI助手类型: xiaohang(小航AI助手) 或 tongyi(北航通义千问)')
    
    # 模式选择
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('-i', '--interactive', action='store_true', help='交互模式')
    mode_group.add_argument('-q', '--question', help='单次提问模式，直接提供问题')
    mode_group.add_argument('-f', '--file', help='批量处理模式，提供问题列表文件路径 (CSV或TXT)')
    
    # 输出选项
    parser.add_argument('-o', '--output', help='输出文件路径')
    parser.add_argument('--format', choices=['txt', 'csv', 'json'], default='txt',
                       help='输出格式，默认为txt')
    
    # 高级选项
    parser.add_argument('--headless', action='store_true', help='无头模式（无浏览器界面）')
    parser.add_argument('--debug', action='store_true', help='开启调试模式')
    
    return parser.parse_args()

def interactive_mode(assistant):
    """交互模式"""
    print("\n欢迎使用北航AI助手自动访问工具 - 交互模式")
    print("输入 'exit' 或 'quit' 退出程序\n")
    
    history = []
    
    while True:
        try:
            question = input("\n请输入您的问题: ")
            if question.lower() in ['exit', 'quit']:
                break
                
            if not question.strip():
                continue
                
            print("正在获取回答...\n")
            response = assistant.chat(question)
            
            print(f"AI助手回答:\n{response}\n")
            
            # 保存对话记录
            history.append({
                'question': question,
                'answer': response,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
        except KeyboardInterrupt:
            print("\n程序已中断")
            break
        except Exception as e:
            print(f"\n出现错误: {str(e)}")
    
    return history

def batch_mode(assistant, file_path):
    """批量处理模式"""
    results = []
    questions = []
    
    # 读取问题文件
    file_ext = os.path.splitext(file_path)[1].lower()
    
    try:
        if file_ext == '.csv':
            import csv
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                try:
                    header = next(reader)  # 尝试跳过表头
                    # 检查是否只有一列，如果是多列，只取第一列
                    col_index = 0
                    if len(header) > 1:
                        for i, col in enumerate(header):
                            if '问题' in col or 'question' in col.lower():
                                col_index = i
                                break
                    questions.append(header[col_index])  # 如果表头是问题，也加入
                    
                    for row in reader:
                        if row and len(row) > col_index:
                            questions.append(row[col_index])
                except StopIteration:
                    pass  # 文件为空
        else:  # 默认按txt处理
            with open(file_path, 'r', encoding='utf-8') as f:
                questions = [line.strip() for line in f if line.strip()]
    
        # 处理问题
        print(f"共加载 {len(questions)} 个问题，开始处理...\n")
        
        for i, question in enumerate(questions):
            print(f"[{i+1}/{len(questions)}] 处理问题: {question[:50]}{'...' if len(question) > 50 else ''}")
            try:
                response = assistant.chat(question)
                results.append({
                    'question': question,
                    'answer': response,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                print(f"√ 已获取回答 ({len(response)} 字符)\n")
            except Exception as e:
                print(f"× 处理失败: {str(e)}\n")
                results.append({
                    'question': question,
                    'answer': f"错误: {str(e)}",
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'error': True
                })
        
        print(f"批量处理完成，共处理 {len(questions)} 个问题，成功 {sum(1 for r in results if 'error' not in r)} 个")
        return results
    
    except Exception as e:
        print(f"批量处理出错: {str(e)}")
        return results

def save_results(results, output_path, format_type):
    """保存结果到文件"""
    if not results:
        print("没有可保存的结果")
        return False
        
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
            import csv
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['问题', '回答', '时间'])
                for item in results:
                    writer.writerow([item['question'], item['answer'], item['timestamp']])
        
        else:  # txt
            with open(output_path, 'w', encoding='utf-8') as f:
                for item in results:
                    f.write(f"问题: {item['question']}\n")
                    f.write(f"回答: {item['answer']}\n")
                    f.write(f"时间: {item['timestamp']}\n")
                    f.write("-" * 50 + "\n\n")
        
        print(f"结果已保存到 {output_path}")
        return True
    
    except Exception as e:
        print(f"保存结果出错: {str(e)}")
        return False

def main():
    """主函数"""
    # 创建必要的目录
    setup_directories()
    
    # 解析命令行参数
    args = parse_arguments()
    
    # 设置日志
    log_level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logger(log_level)
    
    # 配置参数
    username = args.username or config.AUTH_CONFIG['username']
    password = args.password or config.AUTH_CONFIG['password']
    
    # 检查凭据
    if not username or not password:
        print("错误: 缺少用户名或密码。请通过命令行参数提供，或在config.py或环境变量中设置。")
        sys.exit(1)
    
    # 更新配置
    if args.headless:
        config.WEBDRIVER_CONFIG['headless'] = True
    
    # 创建助手实例
    try:
        assistant = AIAssistant(
            username=username,
            password=password,
            assistant_type=args.type
        )
        
        results = []
        
        # 根据模式处理
        if args.interactive:
            results = interactive_mode(assistant)
        elif args.question:
            print(f"问题: {args.question}")
            print("正在获取回答...\n")
            response = assistant.chat(args.question)
            print(f"AI助手回答:\n{response}\n")
            results = [{
                'question': args.question,
                'answer': response,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }]
        elif args.file:
            results = batch_mode(assistant, args.file)
        
        # 保存结果
        if results and (args.output or args.file):
            save_results(results, args.output, args.format)
        
    except Exception as e:
        logger.error(f"程序出错: {str(e)}", exc_info=args.debug)
        print(f"程序出错: {str(e)}")
        sys.exit(1)
    finally:
        # 关闭助手
        if 'assistant' in locals():
            assistant.close()
    
    print("程序已完成")

if __name__ == "__main__":
    main() 