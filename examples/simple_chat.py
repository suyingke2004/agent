#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
北航AI助手简单聊天示例
"""

import os
import sys
import argparse
from dotenv import load_dotenv

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.assistant import AIAssistant
import config

def main():
    """主函数"""
    # 加载环境变量
    load_dotenv()
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='北航AI助手简单聊天示例')
    parser.add_argument('-u', '--username', help='北航统一认证用户名（学号）')
    parser.add_argument('-p', '--password', help='北航统一认证密码')
    parser.add_argument('-t', '--type', choices=['xiaohang', 'tongyi'], 
                        default=config.ASSISTANT_CONFIG['default_assistant'],
                        help='AI助手类型：xiaohang(小航AI助手) 或 tongyi(北航通义千问)')
    args = parser.parse_args()
    
    # 获取凭据
    username = args.username or config.AUTH_CONFIG.get('username', '')
    password = args.password or config.AUTH_CONFIG.get('password', '')
    
    # 检查凭据
    if not username or not password:
        print("错误：缺少用户名或密码。请通过命令行参数提供，或在config.py或环境变量中设置。")
        sys.exit(1)
    
    # 初始化AI助手
    try:
        print(f"正在初始化AI助手 (类型: {args.type})...")
        assistant = AIAssistant(username=username, password=password, assistant_type=args.type)
        print("初始化成功！")
        
        print("\n欢迎使用北航AI助手聊天程序！")
        print("输入 'exit' 或 'quit' 退出程序\n")
        
        while True:
            # 获取用户输入
            user_input = input("\n请输入问题: ")
            
            # 检查是否退出
            if user_input.lower() in ('exit', 'quit'):
                break
            
            # 忽略空输入
            if not user_input.strip():
                continue
            
            # 发送消息并获取回复
            print("正在思考...")
            try:
                response = assistant.chat(user_input)
                print("\n回答：")
                print(response)
            except Exception as e:
                print(f"\n发生错误: {str(e)}")
        
        # 关闭AI助手
        assistant.close()
        print("\n感谢使用，再见！")
        
    except Exception as e:
        print(f"程序出错: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 