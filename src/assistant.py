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
    
    def __init__(self, username: str = None, password: str = None, assistant_type: str = None, shared_driver=None):
        """
        初始化AI助手
        
        Args:
            username (str, optional): 用户名，默认从配置中获取
            password (str, optional): 密码，默认从配置中获取
            assistant_type (str, optional): 助手类型，'xiaohang'或'tongyi'，默认从配置中获取
            shared_driver (WebDriver, optional): 共享的浏览器实例，如果提供则使用该实例
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
        self.auth = BUAAAuth(username, password, shared_driver=shared_driver)
        self.http_client = HTTPClient(base_url=self.base_url, headers=config.ASSISTANT_CONFIG.get('headers', {}))
        
        # 会话状态
        self.conversation = Conversation()
        self.conversation_id = None
        self.driver = shared_driver  # 使用共享的浏览器实例
        self.owns_driver = False  # 标记是否拥有浏览器实例
        self.is_ready = False
        self.browser_logged_in = False  # 记录浏览器是否已登录
        
        # 初始化
        self._initialize()
    
    def _initialize(self) -> None:
        """初始化"""
        # 检查是否需要优先使用浏览器模式
        use_browser_first = config.WEBDRIVER_CONFIG.get('use_browser_first', True)
        
        # 登录
        if not self.auth.login():
            raise AuthError("登录失败，请检查用户名和密码")
        
        # 更新HTTP客户端的会话和cookies
        self.http_client.session = self.auth.get_session()
        self.http_client.session.headers.update(self.auth.get_headers())
        
        # 初始化会话
        self._initialize_conversation()
        
        # 如果配置为优先使用浏览器，则初始化浏览器
        if use_browser_first:
            try:
                self._initialize_browser()
            except Exception as e:
                logger.warning(f"浏览器初始化失败: {str(e)}，将在需要时重试")
                self.driver = None
                self.browser_logged_in = False
        else:
            # 如果不优先使用浏览器，标记为未初始化状态
            logger.info("未配置为优先使用浏览器，浏览器将在需要时初始化")
            self.driver = None
            self.browser_logged_in = False
        
        self.is_ready = True
        logger.info(f"AI助手初始化完成 (类型: {self.assistant_type})")
    
    def _initialize_browser(self) -> None:
        """初始化浏览器"""
        if self.driver:
            logger.info("使用共享的浏览器实例，跳过初始化")
            
            # 如果使用共享的浏览器，需要检查页面状态
            try:
                current_url = self.driver.current_url
                logger.info(f"当前浏览器URL: {current_url}")
                
                # 如果当前不在助手页面，跳转到助手页面
                if self.assistant_url not in current_url and 'sso.buaa.edu.cn' not in current_url:
                    logger.info(f"浏览器当前不在助手页面，跳转到: {self.assistant_url}")
                    self.driver.get(self.assistant_url)
                    
                # 判断是否需要登录
                if 'sso.buaa.edu.cn' in self.driver.current_url:
                    logger.info("检测到需要登录")
                    self._browser_login()
                else:
                    logger.info("浏览器会话已登录状态")
                    self.browser_logged_in = True
            except Exception as e:
                logger.warning(f"检查共享浏览器状态时出错: {str(e)}")
            
            return
            
        logger.info("初始化新的浏览器实例")
        
        # 配置浏览器
        browser_config = config.WEBDRIVER_CONFIG
        browser_type = browser_config.get('browser', 'chrome').lower()
        headless = browser_config.get('headless', False)
        
        # 初始化WebDriver
        try:
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
                self.driver = webdriver.Chrome(service=service, options=options)
                self.owns_driver = True  # 标记为自己创建的浏览器实例
            
            elif browser_type == 'firefox':
                from selenium.webdriver.firefox.options import Options
                from selenium.webdriver.firefox.service import Service
                from webdriver_manager.firefox import GeckoDriverManager
                options = Options()
                if headless:
                    options.add_argument('--headless')
                service = Service(GeckoDriverManager().install())
                self.driver = webdriver.Firefox(service=service, options=options)
                self.owns_driver = True  # 标记为自己创建的浏览器实例
            
            elif browser_type == 'edge':
                from selenium.webdriver.edge.options import Options
                from selenium.webdriver.edge.service import Service
                from webdriver_manager.microsoft import EdgeChromiumDriverManager
                options = Options()
                if headless:
                    options.add_argument('--headless')
                service = Service(EdgeChromiumDriverManager().install())
                self.driver = webdriver.Edge(service=service, options=options)
                self.owns_driver = True  # 标记为自己创建的浏览器实例
            
            else:
                raise AssistantError(f"不支持的浏览器类型: {browser_type}")
            
            # 设置浏览器等待时间
            self.driver.implicitly_wait(browser_config.get('implicit_wait', 10))
            self.driver.set_page_load_timeout(browser_config.get('page_load_timeout', 30))
            
            # 访问AI助手页面
            logger.info(f"访问AI助手页面: {self.assistant_url}")
            self.driver.get(self.assistant_url)
            
            # 检查是否需要登录
            current_url = self.driver.current_url
            if 'sso.buaa.edu.cn' in current_url:
                logger.info("浏览器会话需要登录，正在执行登录操作")
                self._browser_login()
            else:
                logger.info("浏览器会话已登录状态")
                self.browser_logged_in = True
            
            # 等待页面加载完成
            WebDriverWait(self.driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            logger.info("浏览器初始化完成")
            return True
            
        except Exception as e:
            if self.driver:
                self.driver.quit()
                self.driver = None
            logger.error(f"浏览器初始化失败: {str(e)}")
            raise
    
    def _browser_login(self) -> None:
        """使用浏览器执行登录操作"""
        if not self.driver:
            raise AssistantError("浏览器未初始化")
        
        try:
            # 尝试找到iframe
            try:
                iframe = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "loginIframe"))
                )
                self.driver.switch_to.frame(iframe)
            except Exception:
                # 如果找不到iframe，继续在主页面查找
                pass
            
            # 查找用户名和密码输入框
            username_input = None
            password_input = None
            
            # 尝试查找不同的用户名输入框IDs
            for username_id in ["unPassword", "username"]:
                try:
                    username_input = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.ID, username_id))
                    )
                    break
                except Exception:
                    continue
            
            # 尝试查找不同的密码输入框IDs
            for password_id in ["pwPassword", "password"]:
                try:
                    password_input = WebDriverWait(self.driver, 5).until(
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
                submit_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".submit-btn, .btn-login, [type='submit']")
            except Exception:
                pass
            
            if not submit_buttons:
                # 尝试通过name属性查找
                try:
                    submit_buttons = self.driver.find_elements(By.NAME, "submit")
                except Exception:
                    pass
            
            if submit_buttons:
                submit_buttons[0].click()
            else:
                # 如果找不到提交按钮，尝试通过回车键提交
                password_input.send_keys(Keys.RETURN)
            
            # 等待登录完成，页面跳转
            WebDriverWait(self.driver, 20).until(
                lambda d: "sso.buaa.edu.cn" not in d.current_url
            )
            
            logger.info("浏览器登录成功")
            self.browser_logged_in = True
            
            # 如果登录后没有自动跳转到目标页面，手动导航
            if self.assistant_url not in self.driver.current_url:
                self.driver.get(self.assistant_url)
                
            # 等待页面加载完成
            WebDriverWait(self.driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
        except Exception as e:
            self.browser_logged_in = False
            raise AssistantError(f"浏览器登录失败: {str(e)}")
    
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
            # 暂时禁用API调用方式，强制使用浏览器模拟方式
            logger.info("使用浏览器模拟方式发送消息（已禁用API方式）")
            
            # 确保浏览器已初始化，避免每次都重新创建
            if not self.driver and not self.browser_logged_in:
                self._initialize_browser()
            
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
                if self._initialize_browser():
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
        
        # 确保浏览器已初始化，但避免重复初始化
        if not self.driver:
            logger.info("浏览器未初始化，开始初始化")
            self._initialize_browser()
        else:
            logger.info("使用已初始化的浏览器实例")
        
        # 检查会话状态并修复如果需要
        current_url = self.driver.current_url
        # 如果不在正确的页面上，或者发现需要登录
        if ('sso.buaa.edu.cn' in current_url) or (self.assistant_url not in current_url and "chat.buaa.edu.cn" in current_url):
            logger.info("检测到会话状态异常，正在修复")
            # 如果在登录页面，需要重新登录
            if 'sso.buaa.edu.cn' in current_url:
                self.browser_logged_in = False
        
        # 如果浏览器未登录，尝试重新登录
        if not self.browser_logged_in:
            logger.info("浏览器未登录或会话已过期，尝试登录")
            # 访问AI助手页面
            self.driver.get(self.assistant_url)
            
            # 检查是否需要登录
            if 'sso.buaa.edu.cn' in self.driver.current_url:
                self._browser_login()
            else:
                self.browser_logged_in = True
                logger.info("浏览器已处于登录状态")
        
        try:
            # 配置浏览器
            browser_config = config.WEBDRIVER_CONFIG
            
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
            
            # 检查是否在正确的页面上
            current_url = self.driver.current_url
            if self.assistant_url not in current_url and "chat.buaa.edu.cn" in current_url:
                logger.info(f"不在正确的页面，导航到: {self.assistant_url}")
                self.driver.get(self.assistant_url)
                
                # 等待页面加载完成
                WebDriverWait(self.driver, 20).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            
            # 等待输入框加载完成
            input_area = None
            for selector in input_selectors:
                try:
                    input_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in input_elements:
                        if element.is_displayed() and element.is_enabled():
                            input_area = element
                            break
                    if input_area:
                        break
                except Exception:
                    continue
            
            if not input_area:
                # 尝试使用更通用的方法查找输入框
                try:
                    # 查找所有可见的输入框
                    all_inputs = self.driver.find_elements(By.TAG_NAME, "textarea")
                    for element in all_inputs:
                        if element.is_displayed() and element.is_enabled():
                            input_area = element
                            break
                            
                    if not input_area:
                        # 如果仍然找不到，尝试查找含有placeholder的元素
                        placeholders = self.driver.find_elements(By.XPATH, "//*[@placeholder]")
                        for element in placeholders:
                            if element.is_displayed() and element.is_enabled():
                                input_area = element
                                break
                except Exception as e:
                    logger.warning(f"尝试查找输入框时出错: {e}")
                
            if not input_area:
                # 如果仍然找不到，尝试使用JavaScript查找
                try:
                    textareas = self.driver.execute_script("""
                        return Array.from(document.querySelectorAll('textarea, [contenteditable="true"]'))
                            .filter(el => el.offsetParent !== null);
                    """)
                    if textareas and len(textareas) > 0:
                        input_area = textareas[0]
                except Exception as e:
                    logger.warning(f"使用JavaScript查找输入框时出错: {e}")
            
            if not input_area:
                raise AssistantError("无法找到消息输入框")
            
            # 清空输入框并输入消息
            try:
                # 首先尝试清空
                input_area.clear()
                # 有时clear()不起作用，使用Ctrl+A和Delete
                input_area.send_keys(Keys.CONTROL + "a")
                input_area.send_keys(Keys.DELETE)
                # 输入消息
                input_area.send_keys(message)
                logger.info("已在输入框中输入消息")
            except Exception as e:
                logger.warning(f"通过常规方法输入消息失败: {e}")
                # 尝试使用JavaScript设置值
                try:
                    self.driver.execute_script("arguments[0].value = arguments[1];", input_area, message)
                    logger.info("已通过JavaScript在输入框中输入消息")
                except Exception as e:
                    logger.error(f"通过JavaScript输入消息也失败: {e}")
                    raise AssistantError(f"无法在输入框中输入消息: {e}")
            
            # 查找发送按钮并点击
            send_button = None
            for selector in send_button_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            send_button = button
                            break
                    if send_button:
                        break
                except Exception:
                    continue
            
            if send_button:
                try:
                    # 尝试直接点击
                    send_button.click()
                    logger.info("已点击发送按钮")
                except Exception as e:
                    logger.warning(f"直接点击发送按钮失败: {e}")
                    # 尝试使用JavaScript点击
                    try:
                        self.driver.execute_script("arguments[0].click();", send_button)
                        logger.info("已通过JavaScript点击发送按钮")
                    except Exception as e:
                        logger.error(f"通过JavaScript点击发送按钮也失败: {e}")
                        # 如果点击失败，尝试通过回车键发送
                        input_area.send_keys(Keys.RETURN)
                        logger.info("已通过回车键发送消息")
            else:
                # 如果找不到发送按钮，尝试通过回车键发送
                input_area.send_keys(Keys.RETURN)
                logger.info("未找到发送按钮，已通过回车键发送消息")
            
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
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
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
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
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
    
    def close(self, keep_browser_open=False) -> None:
        """
        关闭会话
        
        Args:
            keep_browser_open (bool): 是否保持浏览器开启状态，默认为False
        """
        try:
            # 保存会话历史
            self.conversation.save()
            
            # 关闭HTTP客户端
            self.http_client.close()
            
            # 关闭浏览器，除非指定保持开启或是共享实例
            if self.driver and self.owns_driver and not keep_browser_open:
                try:
                    logger.info("正在关闭浏览器会话（由助手创建）")
                    self.driver.quit()
                    self.driver = None
                    self.browser_logged_in = False
                except Exception as e:
                    logger.error(f"关闭浏览器失败: {str(e)}")
            elif self.driver and keep_browser_open:
                logger.info("保持浏览器会话开启")
            elif self.driver and not self.owns_driver:
                logger.info("跳过关闭共享的浏览器实例")
            
            # 关闭认证，除非指定保持浏览器开启
            if not keep_browser_open and hasattr(self.auth, 'driver') and self.auth.driver:
                # 如果认证模块使用的是共享浏览器实例，不会真正关闭浏览器
                self.auth.quit_driver()
            
            # 重置状态，但若保持浏览器开启则保留浏览器状态
            if not keep_browser_open:
                self.is_ready = False
            
            logger.info("AI助手会话已关闭" + (" (浏览器保持开启)" if keep_browser_open else ""))
            
        except Exception as e:
            logger.error(f"关闭会话失败: {str(e)}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        # 检查配置，决定是否保持浏览器开启
        keep_browser_open = config.WEBDRIVER_CONFIG.get('keep_browser_open', False)
        self.close(keep_browser_open=keep_browser_open) 