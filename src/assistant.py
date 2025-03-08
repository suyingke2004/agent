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
from selenium.webdriver.common.keys import Keys

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
        # 根据不同的助手类型，构造不同的API端点
        if self.assistant_type == 'xiaohang':
            # 小航AI助手的API端点
            api_endpoint = f"{self.base_url}api/site/chat"
        else:
            # 通义千问的API端点
            api_endpoint = f"{self.base_url}api/app/tongyi/chat"
        
        return api_endpoint
    
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
            # 根据配置决定是否优先使用浏览器模拟模式
            use_browser_first = config.WEBDRIVER_CONFIG.get('use_browser_first', True)
            
            if use_browser_first:
                # 优先使用浏览器模拟方式
                try:
                    logger.info("尝试使用浏览器模拟方式发送消息")
                    response = self._browser_chat(message)
                    logger.info("浏览器模拟方式成功获取回复")
                except Exception as e:
                    logger.warning(f"浏览器模拟方式失败: {str(e)}，回退到API方式")
                    # 如果浏览器模拟失败，回退到API方式
                    if self.assistant_type == 'xiaohang':
                        response = self._xiaohang_chat(message)
                    else:
                        response = self._tongyi_chat(message)
            else:
                # 优先使用API方式
                try:
                    logger.info("尝试使用API方式发送消息")
                    if self.assistant_type == 'xiaohang':
                        response = self._xiaohang_chat(message)
                    else:
                        response = self._tongyi_chat(message)
                except Exception as e:
                    logger.warning(f"API方式失败: {str(e)}，尝试使用浏览器模拟方式")
                    # 如果API方式失败，尝试浏览器模拟方式
                    response = self._browser_chat(message)
                    logger.info("浏览器模拟方式成功获取回复")
            
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
    
    def _browser_chat(self, message: str) -> str:
        """
        使用浏览器模拟方式与AI助手交互
        
        Args:
            message (str): 消息内容
            
        Returns:
            str: AI助手的回复
        """
        logger.info("使用浏览器模拟方式发送消息")
        
        # 配置浏览器
        browser_config = config.WEBDRIVER_CONFIG
        browser_type = browser_config.get('browser', 'chrome').lower()
        headless = browser_config.get('headless', False)
        
        # 获取选择器配置
        element_selectors = browser_config.get('element_selectors', {})
        input_selectors = element_selectors.get('input_selectors', [
            "textarea.n-input__textarea-el", 
            ".chat-input", 
            "[placeholder]", 
            "textarea"
        ])
        send_button_selectors = element_selectors.get('send_button_selectors', [
            "button[type='submit']",
            ".send-button",
            "button.n-button",
            "button"
        ])
        response_selectors = element_selectors.get('response_selectors', [
            ".chat-assistant .text",
            ".chat-message-text",
            ".assistant-message",
            ".reply .text"
        ])
        
        # 设置等待时间
        max_wait_time = browser_config.get('wait_for_answer', 60)
        
        driver = None
        try:
            # 初始化WebDriver
            if browser_type == 'chrome':
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                options = Options()
                if headless:
                    options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                options.add_experimental_option('excludeSwitches', ['enable-logging'])
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
            
            elif browser_type == 'firefox':
                from selenium.webdriver.firefox.options import Options
                from selenium.webdriver.firefox.service import Service
                from webdriver_manager.firefox import GeckoDriverManager
                options = Options()
                if headless:
                    options.add_argument('--headless')
                service = Service(GeckoDriverManager().install())
                driver = webdriver.Firefox(service=service, options=options)
            
            elif browser_type == 'edge':
                from selenium.webdriver.edge.options import Options
                from selenium.webdriver.edge.service import Service
                from webdriver_manager.microsoft import EdgeChromiumDriverManager
                options = Options()
                if headless:
                    options.add_argument('--headless')
                service = Service(EdgeChromiumDriverManager().install())
                driver = webdriver.Edge(service=service, options=options)
            
            else:
                raise AssistantError(f"不支持的浏览器类型: {browser_type}")
            
            # 设置浏览器等待时间
            driver.implicitly_wait(browser_config.get('implicit_wait', 10))
            driver.set_page_load_timeout(browser_config.get('page_load_timeout', 30))
            
            # 登录并访问助手页面
            logger.info("访问AI助手页面")
            if self.assistant_type == 'xiaohang':
                target_url = config.ASSISTANT_CONFIG.get('xiaohang_url', 'https://chat.buaa.edu.cn/page/site/newPc')
            else:
                target_url = config.ASSISTANT_CONFIG.get('tongyi_url', 'https://chat.buaa.edu.cn/page/app/tongyi')
            
            driver.get(target_url)
            
            # 检查是否需要登录
            current_url = driver.current_url
            if 'sso.buaa.edu.cn' in current_url:
                logger.info("需要登录，正在执行登录操作")
                
                # 等待用户名输入框加载
                try:
                    # 尝试找到iframe
                    try:
                        iframe = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "loginIframe"))
                        )
                        driver.switch_to.frame(iframe)
                    except Exception:
                        # 如果找不到iframe，继续在主页面查找
                        pass
                    
                    # 查找用户名和密码输入框
                    username_input = None
                    password_input = None
                    
                    # 尝试查找不同的用户名输入框IDs
                    for username_id in ["unPassword", "username"]:
                        try:
                            username_input = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.ID, username_id))
                            )
                            break
                        except Exception:
                            continue
                    
                    # 尝试查找不同的密码输入框IDs
                    for password_id in ["pwPassword", "password"]:
                        try:
                            password_input = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.ID, password_id))
                            )
                            break
                        except Exception:
                            continue
                    
                    if not username_input or not password_input:
                        raise AssistantError("无法找到用户名或密码输入框")
                    
                    # 填写登录表单
                    username_input.clear()
                    username_input.send_keys(self.auth.username)
                    password_input.clear()
                    password_input.send_keys(self.auth.password)
                    
                    # 查找并点击登录按钮
                    submit_buttons = []
                    try:
                        # 尝试通过CSS类名查找
                        submit_buttons = driver.find_elements(By.CSS_SELECTOR, ".submit-btn, .btn-login, [type='submit']")
                    except Exception:
                        pass
                    
                    if not submit_buttons:
                        # 尝试通过name属性查找
                        try:
                            submit_buttons = driver.find_elements(By.NAME, "submit")
                        except Exception:
                            pass
                    
                    if submit_buttons:
                        submit_buttons[0].click()
                    else:
                        # 如果找不到提交按钮，尝试通过回车键提交
                        password_input.send_keys(Keys.RETURN)
                    
                    # 等待登录完成，页面跳转
                    WebDriverWait(driver, 20).until(
                        lambda d: "sso.buaa.edu.cn" not in d.current_url
                    )
                    
                    logger.info("登录成功")
                    
                    # 如果登录后没有自动跳转到目标页面，手动导航
                    if target_url not in driver.current_url:
                        driver.get(target_url)
                    
                except Exception as e:
                    raise AssistantError(f"自动登录失败: {str(e)}")
            
            # 等待页面加载完成
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # 等待输入框加载完成
            input_area = None
            for selector in input_selectors:
                try:
                    input_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in input_elements:
                        if element.is_displayed() and element.is_enabled():
                            input_area = element
                            break
                    if input_area:
                        break
                except Exception:
                    continue
            
            if not input_area:
                raise AssistantError("无法找到消息输入框")
            
            # 清空输入框并输入消息
            input_area.clear()
            input_area.send_keys(message)
            
            # 查找发送按钮并点击
            send_button = None
            for selector in send_button_selectors:
                try:
                    buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            send_button = button
                            break
                    if send_button:
                        break
                except Exception:
                    continue
            
            if send_button:
                send_button.click()
            else:
                # 如果找不到发送按钮，尝试通过回车键发送
                input_area.send_keys(Keys.RETURN)
            
            # 等待回复完成
            # 通过观察元素变化判断AI是否在回复
            time.sleep(2)  # 等待一小段时间让回复开始
            
            # 等待回复结束（通过检测加载指示器消失或回复元素出现）
            max_wait_time = browser_config.get('wait_for_answer', 60)  # 从配置获取最大等待时间
            wait_increment = 0.5  # 每次检查的间隔时间（秒）
            wait_time = 0
            
            previous_response_length = 0
            stable_count = 0
            
            # 等待回复稳定（不再变化）
            while wait_time < max_wait_time:
                # 寻找回复元素
                response_elements = []
                for selector in response_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            response_elements.extend(elements)
                    except Exception:
                        continue
                
                # 查找最新的回复
                response_text = ""
                for element in response_elements:
                    try:
                        if element.is_displayed():
                            element_text = element.text
                            if element_text and len(element_text) > len(response_text):
                                response_text = element_text
                    except Exception:
                        continue
                
                # 检查回复是否稳定（不再变化）
                if len(response_text) > 0:
                    if len(response_text) == previous_response_length:
                        stable_count += 1
                        if stable_count >= 6:  # 连续3秒没有变化视为回复结束
                            break
                    else:
                        stable_count = 0
                        previous_response_length = len(response_text)
                
                time.sleep(wait_increment)
                wait_time += wait_increment
            
            # 获取最终回复
            final_response = ""
            response_elements = []
            for selector in response_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        response_elements.extend(elements)
                except Exception:
                    continue
            
            # 获取最新最长的回复
            for element in response_elements:
                try:
                    if element.is_displayed():
                        element_text = element.text
                        if element_text and len(element_text) > len(final_response):
                            final_response = element_text
                except Exception:
                    continue
            
            if not final_response:
                raise AssistantError("无法获取AI助手的回复")
            
            logger.info(f"成功获取回复: {final_response[:50]}{'...' if len(final_response) > 50 else ''}")
            return final_response
            
        except Exception as e:
            raise AssistantError(f"浏览器模拟交互失败: {str(e)}")
        
        finally:
            # 关闭浏览器
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.error(f"关闭浏览器失败: {str(e)}")
    
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
            "jsonFormat": False,
            "search": True  # 启用联网搜索
        }
        
        # 获取API端点并发送请求
        api_url = self._get_api_endpoint("")
        
        # 记录API请求
        logger.debug(f"发送请求到: {api_url}")
        logger.debug(f"请求数据: {data}")
        
        response = self.http_client.post(api_url, json=data)
        
        # 解析响应
        try:
            result = response.json()
            logger.debug(f"响应数据: {result}")
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
            "model": "tongyi-advance",
            "search": True  # 启用联网搜索
        }
        
        # 获取API端点并发送请求
        api_url = self._get_api_endpoint("")
        
        # 记录API请求
        logger.debug(f"发送请求到: {api_url}")
        logger.debug(f"请求数据: {data}")
        
        response = self.http_client.post(api_url, json=data)
        
        # 解析响应
        try:
            result = response.json()
            logger.debug(f"响应数据: {result}")
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