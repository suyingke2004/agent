#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AI助手交互模块
处理与北航AI助手的交互
"""

import time
import json
import re
import logging
from typing import Dict, List, Optional, Any, Union, Tuple
import uuid
from urllib.parse import urljoin

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup
from retry import retry

from src.auth import BUAAAuth, AuthError
from src.utils.logger import get_logger
from src.utils.http import HTTPClient
from src.models.message import Message, Conversation
import config

# 获取日志记录器
logger = get_logger()

class AssistantError(Exception):
    """AI助手错误"""
    pass

class AIAssistant:
    """北航AI助手交互类"""
    
    def __init__(self, username: str = None, password: str = None, assistant_type: str = None):
        """
        初始化AI助手
        
        Args:
            username (str, optional): 用户名，默认从配置中获取
            password (str, optional): 密码，默认从配置中获取
            assistant_type (str, optional): 助手类型，'xiaohang'或'tongyi'，默认从配置中获取
        """
        # 配置
        self.assistant_type = assistant_type or config.ASSISTANT_CONFIG.get('default_assistant', 'xiaohang')
        if self.assistant_type not in ('xiaohang', 'tongyi'):
            logger.warning(f"未知的助手类型: {self.assistant_type}，使用默认值: xiaohang")
            self.assistant_type = 'xiaohang'
        
        # URL
        self.base_url = 'https://chat.buaa.edu.cn/'
        self.api_base_path = config.ASSISTANT_CONFIG.get('api_base_path', '')
        
        if self.assistant_type == 'xiaohang':
            self.assistant_url = config.ASSISTANT_CONFIG.get('xiaohang_url', 'https://chat.buaa.edu.cn/page/site/newPc')
        else:
            self.assistant_url = config.ASSISTANT_CONFIG.get('tongyi_url', 'https://chat.buaa.edu.cn/page/app/tongyi')
        
        # 认证
        self.auth = BUAAAuth(username, password)
        self.http_client = HTTPClient(base_url=self.base_url, headers=config.ASSISTANT_CONFIG.get('headers', {}))
        
        # 会话状态
        self.conversation = Conversation()
        self.conversation_id = None
        self.driver = None
        self.is_ready = False
        
        # 初始化
        self._initialize()
    
    def _initialize(self) -> None:
        """初始化"""
        # 登录
        if not self.auth.login():
            raise AuthError("登录失败，请检查用户名和密码")
        
        # 更新HTTP客户端的会话和cookies
        self.http_client.session = self.auth.get_session()
        self.http_client.session.headers.update(self.auth.get_headers())
        
        # 初始化会话
        self._initialize_conversation()
        
        self.is_ready = True
        logger.info(f"AI助手初始化完成 (类型: {self.assistant_type})")
    
    def _initialize_conversation(self) -> None:
        """初始化会话"""
        logger.info("初始化AI助手会话")
        
        try:
            # 访问助手页面
            response = self.http_client.get(self.assistant_url)
            
            # 如果需要登录，重新登录
            if self.auth.is_login_required(self.assistant_url):
                logger.info("会话已过期，重新登录")
                self.auth.login()
                self.http_client.session = self.auth.get_session()
                self.http_client.session.headers.update(self.auth.get_headers())
                response = self.http_client.get(self.assistant_url)
            
            # 初始化会话ID
            self.conversation_id = f"conv_{int(time.time() * 1000)}"
            self.conversation = Conversation(
                conversation_id=self.conversation_id,
                title=f"对话 {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
        except Exception as e:
            logger.error(f"初始化会话失败: {str(e)}")
            raise AssistantError(f"初始化会话失败: {str(e)}")
    
    def _initialize_with_selenium(self) -> bool:
        """
        使用Selenium初始化
        
        Returns:
            bool: 初始化是否成功
        """
        logger.info("使用Selenium初始化AI助手")
        
        try:
            # 使用Selenium登录并获取会话信息
            self.auth.login_with_selenium()
            
            # 使用获取到的cookies更新http_client
            self.http_client.session.cookies.update(self.auth.session.cookies)
            
            # 初始化会话
            self._initialize_conversation()
            
            return True
            
        except Exception as e:
            logger.error(f"Selenium初始化失败: {str(e)}")
            return False
        finally:
            if hasattr(self.auth, 'driver') and self.auth.driver:
                self.auth.quit_driver()
    
    def _get_api_endpoint(self, path: str) -> str:
        """
        获取API端点URL
        
        Args:
            path (str): API路径
            
        Returns:
            str: 完整的API URL
        """
        # 根据不同的助手类型，可能有不同的API端点
        if self.assistant_type == 'xiaohang':
            # 小航AI助手的API端点
            api_base = f"{self.base_url}api/"
        else:
            # 通义千问的API端点
            api_base = f"{self.base_url}api/tongyi/"
        
        return urljoin(api_base, path)
    
    @retry(tries=3, delay=2, backoff=2, logger=logger)
    def chat(self, message: str) -> str:
        """
        发送消息并获取回复
        
        Args:
            message (str): 消息内容
            
        Returns:
            str: AI助手的回复
        """
        if not self.is_ready:
            self._initialize()
        
        # 检查消息长度
        max_length = config.MESSAGE_CONFIG.get('max_message_length', 2000)
        if len(message) > max_length:
            logger.warning(f"消息过长，将被截断 ({len(message)} > {max_length})")
            message = message[:max_length]
        
        # 添加用户消息到会话历史
        user_message = self.conversation.add_user_message(message)
        logger.info(f"发送消息: {message[:50]}{'...' if len(message) > 50 else ''}")
        
        try:
            # 根据不同助手类型，使用不同的API
            if self.assistant_type == 'xiaohang':
                response = self._xiaohang_chat(message)
            else:
                response = self._tongyi_chat(message)
            
            # 添加助手回复到会话历史
            self.conversation.add_assistant_message(response)
            
            # 保存会话历史
            self.conversation.save()
            
            return response
            
        except Exception as e:
            error_msg = f"发送消息失败: {str(e)}"
            logger.error(error_msg)
            
            # 添加错误消息到会话历史
            self.conversation.add_assistant_message(f"错误: {error_msg}")
            
            # 尝试使用Selenium重新初始化
            if not self.is_ready:
                logger.info("尝试使用Selenium重新初始化")
                if self._initialize_with_selenium():
                    logger.info("重新初始化成功，重试发送消息")
                    return self.chat(message)
            
            raise AssistantError(error_msg)
    
    def _xiaohang_chat(self, message: str) -> str:
        """
        与小航AI助手交互
        
        Args:
            message (str): 消息内容
            
        Returns:
            str: AI助手的回复
        """
        # 构造请求数据
        data = {
            "question": message,
            "history": [],
            "jsonFormat": False
        }
        
        # 发送请求
        api_url = self._get_api_endpoint("chat")
        response = self.http_client.post(api_url, json=data)
        
        # 解析响应
        try:
            result = response.json()
            if result.get('success'):
                return result.get('data', '')
            else:
                error_msg = result.get('message', '未知错误')
                logger.error(f"AI助手返回错误: {error_msg}")
                raise AssistantError(f"AI助手返回错误: {error_msg}")
        except Exception as e:
            logger.error(f"解析响应失败: {str(e)}")
            # 如果解析失败，尝试直接返回文本
            return response.text
    
    def _tongyi_chat(self, message: str) -> str:
        """
        与通义千问交互
        
        Args:
            message (str): 消息内容
            
        Returns:
            str: AI助手的回复
        """
        # 构造请求数据
        data = {
            "prompt": message,
            "history": [],
            "model": "tongyi-advance"
        }
        
        # 发送请求
        api_url = self._get_api_endpoint("chat")
        response = self.http_client.post(api_url, json=data)
        
        # 解析响应
        try:
            result = response.json()
            if result.get('success'):
                return result.get('data', {}).get('content', '')
            else:
                error_msg = result.get('message', '未知错误')
                logger.error(f"AI助手返回错误: {error_msg}")
                raise AssistantError(f"AI助手返回错误: {error_msg}")
        except Exception as e:
            logger.error(f"解析响应失败: {str(e)}")
            # 如果解析失败，尝试直接返回文本
            return response.text
    
    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """
        获取会话历史
        
        Returns:
            list: 会话历史列表
        """
        return [msg.to_dict() for msg in self.conversation.messages]
    
    def clear_conversation(self) -> None:
        """清除会话历史"""
        self.conversation.clear()
        logger.info("会话历史已清除")
    
    def close(self) -> None:
        """关闭会话"""
        try:
            # 保存会话历史
            self.conversation.save()
            
            # 关闭HTTP客户端
            self.http_client.close()
            
            # 关闭认证
            if hasattr(self.auth, 'driver') and self.auth.driver:
                self.auth.quit_driver()
            
            logger.info("AI助手会话已关闭")
            
        except Exception as e:
            logger.error(f"关闭会话失败: {str(e)}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close() 