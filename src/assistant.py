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
        
        # if self.assistant_type == 'xiaohang':
        #     self.assistant_url = config.ASSISTANT_CONFIG.get('xiaohang_url', 'https://chat.buaa.edu.cn/page/site/')
        # else:
        #     self.assistant_url = config.ASSISTANT_CONFIG.get('tongyi_url', 'https://chat.buaa.edu.cn/page/app/tongyi')
        
        if self.assistant_type == 'xiaohang':
            self.assistant_url = config.ASSISTANT_CONFIG.get('xiaohang_url', 'https://chat.buaa.edu.cn/page/site/newPc?app=2')
        else:
            self.assistant_url = config.ASSISTANT_CONFIG.get('tongyi_url', 'https://chat.buaa.edu.cn/page/site/newPc?app=9')#我寻思这么改能行

        
        # 认证
        self.auth = BUAAAuth(username, password, shared_driver=shared_driver)
        self.http_client = HTTPClient(base_url=self.base_url, headers=config.ASSISTANT_CONFIG.get('headers', {}))
        
        # 会话状态
        self.conversation = Conversation()
        self.conversation_id = None
        self.driver = shared_driver  # 使用共享的浏览器实例
        if shared_driver:
            logger.info(f"已接收全局共享浏览器实例，ID: {id(shared_driver)}")
        else:
            logger.warning("未接收到全局共享浏览器实例")
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
    
    def _initialize_browser(self) -> bool:
        """
        初始化浏览器，如果已存在共享实例则使用共享实例
        
        Returns:
            bool: 是否成功初始化
        """
        # 如果已有共享的浏览器实例，直接使用
        if self.driver:
            logger.info(f"使用已存在的共享浏览器实例，ID: {id(self.driver)}")
            
            # 如果使用共享的浏览器，需要检查页面状态
            try:
                current_url = self.driver.current_url
                logger.info(f"共享浏览器当前URL: {current_url}")
                
                # 如果当前不在助手页面，跳转到助手页面
                if self.assistant_url not in current_url and 'sso.buaa.edu.cn' not in current_url:
                    logger.info(f"浏览器当前不在助手页面，跳转到: {self.assistant_url}")
                    self.driver.get(self.assistant_url)
                    
                # 判断是否需要登录
                if 'sso.buaa.edu.cn' in self.driver.current_url:
                    logger.info("检测到需要登录")
                    self._browser_login()
                else:
                    logger.info("浏览器会话已处于登录状态")
                    self.browser_logged_in = True
                    
                # 暂时禁用模型选择功能
                # self._handle_model_selection()
                logger.info("模型选择功能已暂时禁用")
                
            except Exception as e:
                logger.warning(f"检查共享浏览器状态时出错: {str(e)}")
            
            return True
        
        # 只有在没有共享实例时才创建新实例
        logger.warning("没有共享浏览器实例，创建新的浏览器实例可能导致会话问题！")
        
        # 使用全局配置，不重新创建
        browser_type = config.WEBDRIVER_CONFIG.get('browser', 'chrome').lower()
        headless = config.WEBDRIVER_CONFIG.get('headless', False)
        
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
                options.add_argument('--log-level=3')  # 禁用日志输出
                service = Service(ChromeDriverManager().install())
                
                # 记录日志，标明正在创建新实例
                logger.warning("创建新的Chrome浏览器实例（注意：应该使用全局共享实例）")
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
                logger.warning("创建新的Firefox浏览器实例（注意：应该使用全局共享实例）")
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
                logger.warning("创建新的Edge浏览器实例（注意：应该使用全局共享实例）")
                self.driver = webdriver.Edge(service=service, options=options)
                self.owns_driver = True  # 标记为自己创建的浏览器实例
                
            else:
                logger.error(f"不支持的浏览器类型: {browser_type}")
                return False
            
            # 设置浏览器窗口大小和等待时间
            self.driver.set_window_size(1280, 800)  # 设置合理的窗口大小，避免元素不可见
            self.driver.implicitly_wait(config.WEBDRIVER_CONFIG.get('implicit_wait', 10))
            self.driver.set_page_load_timeout(config.WEBDRIVER_CONFIG.get('page_load_timeout', 30))
            
            # 访问目标页面
            logger.info(f"访问AI助手页面: {self.assistant_url}")
            self.driver.get(self.assistant_url)
            
            # 检查是否需要登录
            if 'sso.buaa.edu.cn' in self.driver.current_url:
                self._browser_login()
            else:
                self.browser_logged_in = True
                logger.info("浏览器已处于登录状态")
            
            # 处理模型选择界面
            # self._handle_model_selection()
            logger.info("模型选择功能已暂时禁用")
            
            return True
            
        except Exception as e:
            logger.error(f"初始化浏览器失败: {str(e)}")
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
                self.owns_driver = False
            return False
    
    def _browser_login(self) -> bool:
        """
        使用浏览器登录统一身份认证
        
        Returns:
            bool: 登录是否成功
        """
        logger.info("开始浏览器登录流程")
        
        # 确保浏览器实例存在
        if not self.driver:
            logger.error("浏览器实例不存在，无法执行登录")
            return False
        
        try:
            # 确保在登录页面
            current_url = self.driver.current_url
            if 'sso.buaa.edu.cn' not in current_url:
                logger.info(f"当前不在登录页面，访问登录页面: {self.auth.login_url}")
                self.driver.get(self.auth.login_url)
            
            # 等待重定向到登录页面
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: 'sso.buaa.edu.cn' in d.current_url
                )
            except Exception as e:
                logger.warning(f"等待重定向到登录页面超时: {str(e)}")
            
            # 等待登录表单加载
            username_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            password_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "password"))
            )
            
            # 清空并输入用户名密码
            username_input.clear()
            username_input.send_keys(self.auth.username)
            password_input.clear()
            password_input.send_keys(self.auth.password)
            
            # 点击登录按钮
            login_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.NAME, "submit"))
            )
            login_button.click()
            
            # 等待登录完成并重定向到目标页面
            # 定义一个函数，检查是否已重定向到目标页面
            def check_redirect():
                current_url = self.driver.current_url
                if 'sso.buaa.edu.cn' not in current_url:
                    logger.info(f"登录成功，已重定向到: {current_url}")
                    return True
                return False
            
            # 等待重定向，最长等待20秒
            try:
                WebDriverWait(self.driver, 20).until(lambda d: check_redirect())
            except Exception as e:
                logger.warning(f"等待重定向超时: {str(e)}")
                # 检查是否仍在登录页面，可能是密码错误
                if 'sso.buaa.edu.cn' in self.driver.current_url:
                    error_messages = self.driver.find_elements(By.CLASS_NAME, "auth_error")
                    if error_messages:
                        for msg in error_messages:
                            if msg.is_displayed():
                                logger.error(f"登录失败: {msg.text}")
                                return False
                    logger.error("登录失败，仍在登录页面")
                    return False
            
            # 设置登录状态
            if 'sso.buaa.edu.cn' not in self.driver.current_url:
                self.browser_logged_in = True
                logger.info("浏览器登录成功")
                
                # 登录成功后等待页面完全加载
                WebDriverWait(self.driver, 20).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                
                # 如果没有重定向到目标助手页面，手动导航
                if self.assistant_url not in self.driver.current_url:
                    logger.info(f"重定向到其他页面，手动导航到助手页面: {self.assistant_url}")
                    self.driver.get(self.assistant_url)
                    WebDriverWait(self.driver, 20).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                
                return True
            else:
                logger.error("登录后仍在SSO页面，登录可能失败")
                return False
            
        except Exception as e:
            logger.error(f"浏览器登录出错: {str(e)}")
            return False
    
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
            if not self.driver:
                logger.warning("浏览器实例不存在，这可能表明全局共享浏览器实例未正确传递")
                self._initialize_browser()
            else:
                logger.info("使用现有的浏览器实例")
            
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
            if not self._initialize_browser():
                raise AssistantError("无法初始化浏览器")
        else:
            logger.info(f"使用已初始化的浏览器实例，ID: {id(self.driver)}")
        
        # 检查会话状态并修复如果需要
        try:
            current_url = self.driver.current_url
            logger.info(f"当前URL: {current_url}")
            
            # 如果不在正确的页面上，或者发现需要登录
            if 'sso.buaa.edu.cn' in current_url:
                logger.info("检测到登录页面，需要重新登录")
                self.browser_logged_in = False
                self._browser_login()
                # 登录后可能需要处理模型选择
                # self._handle_model_selection()
            elif self.assistant_url not in current_url and "chat.buaa.edu.cn" in current_url:
                logger.info(f"不在正确的页面，导航到: {self.assistant_url}")
                self.driver.get(self.assistant_url)
                # 等待页面加载完成
                WebDriverWait(self.driver, 20).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                # 可能需要处理模型选择
                # self._handle_model_selection()
        except Exception as e:
            logger.warning(f"检查会话状态时出错: {str(e)}")
        
        try:
            # 使用全局配置参数，不重新获取config.WEBDRIVER_CONFIG
            # 获取选择器配置
            element_selectors = config.WEBDRIVER_CONFIG.get('element_selectors', {})
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
            max_wait_time = config.WEBDRIVER_CONFIG.get('wait_for_answer', 60)
            
            # 查看当前是否已有对话框
            try:
                # 检查是否有输入框
                textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
                if not any(textarea.is_displayed() for textarea in textareas):
                    logger.info("未找到可见的输入框，可能需要选择模型")
                    # self._handle_model_selection()
                else:
                    logger.info("找到可见的输入框")
            except Exception as e:
                logger.warning(f"检查输入框时出错: {str(e)}")
            
            # 查找输入框
            input_area = None
            
            # 1. 首先使用精确的JavaScript路径
            try:
                specific_input = self.driver.execute_script("""
                    // 尝试使用精确的选择器路径
                    const input = document.querySelector("#send_body_id > div.bottom > div.left > div.input_box > div > div.n-input-wrapper > div.n-input__textarea.n-scrollbar > textarea");
                    if (input && input.offsetParent !== null) {
                        return input;
                    }
                    
                    // 如果没找到，尝试查找容器并获取其中的textarea
                    const container = document.querySelector("#send_body_id > div.bottom > div.left > div.input_box");
                    if (container) {
                        const textarea = container.querySelector("textarea");
                        if (textarea && textarea.offsetParent !== null) {
                            return textarea;
                        }
                    }
                    
                    return null;
                """)
                if specific_input:
                    input_area = specific_input
                    logger.info("使用精确的JavaScript路径找到输入框")
            except Exception as e:
                logger.debug(f"使用精确的JavaScript路径查找输入框时出错: {e}")
            
            # 2. 如果没找到，尝试其他选择器
            if not input_area:
                for selector in input_selectors:
                    try:
                        input_areas = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in input_areas:
                            if element.is_displayed() and element.is_enabled():
                                input_area = element
                                logger.info(f"找到输入框，选择器: {selector}")
                                break
                        if input_area:
                            break
                    except Exception as e:
                        logger.debug(f"使用选择器 {selector} 查找输入框时出错: {e}")
            
            # 3. 如果还是没找到，尝试使用更广泛的JavaScript查询
            if not input_area:
                try:
                    input_area = self.driver.execute_script("""
                        // 尝试查找所有可能的输入元素
                        const selectors = [
                            "#send_body_id > div.bottom > div.left > div.input_box > div > div.n-input-wrapper > div.n-input__textarea.n-scrollbar > textarea",
                            "#send_body_id > div.bottom > div.left > div.input_box",
                            "textarea",
                            "[contenteditable='true']",
                            ".input-box",
                            ".chat-input"
                        ];
                        
                        // 精确选择器优先
                        const preciseInput = document.querySelector("#send_body_id > div.bottom > div.left > div.input_box > div > div.n-input-wrapper > div.n-input__textarea.n-scrollbar > textarea");
                        if (preciseInput && preciseInput.offsetParent !== null) {
                            return preciseInput;
                        }
                        
                        // 遍历所有可能的选择器
                        for (const selector of selectors) {
                            const elements = document.querySelectorAll(selector);
                            for (const el of elements) {
                                if (el.offsetParent !== null && 
                                    (el.tagName.toLowerCase() === 'textarea' || 
                                     el.getAttribute('contenteditable') === 'true' ||
                                     el.classList.contains('input-box'))) {
                                    return el;
                                }
                            }
                        }
                        
                        // 最后尝试查找任何可见的textarea
                        const allTextareas = document.querySelectorAll('textarea');
                        for (const textarea of allTextareas) {
                            if (textarea.offsetParent !== null && textarea.style.display !== 'none') {
                                return textarea;
                            }
                        }
                        
                        return null;
                    """)
                    if input_area:
                        logger.info("通过JavaScript查询找到输入框")
                except Exception as e:
                    logger.debug(f"使用JavaScript查询查找输入框时出错: {e}")
            
            if not input_area:
                raise AssistantError("无法找到输入框")
            
            # 验证找到的输入框是否为可输入元素
            try:
                # 检查元素类型和可编辑状态
                is_valid_input = self.driver.execute_script("""
                    const el = arguments[0];
                    // 检查是否为textarea或可编辑div
                    return (el.tagName.toLowerCase() === 'textarea' || 
                           el.getAttribute('contenteditable') === 'true') &&
                           el.offsetParent !== null && !el.disabled;
                """, input_area)
                
                if not is_valid_input:
                    logger.warning("找到的元素不是有效的输入框，尝试查找其中的textarea")
                    # 如果不是有效输入框，尝试在其中查找textarea
                    try:
                        textarea = self.driver.execute_script("""
                            const container = arguments[0];
                            return container.querySelector('textarea') || 
                                  container.querySelector('[contenteditable="true"]');
                        """, input_area)
                        
                        if textarea:
                            input_area = textarea
                            logger.info("在容器中找到了有效的输入框")
                    except Exception as e:
                        logger.debug(f"尝试在容器中查找输入框时出错: {e}")
            except Exception as e:
                logger.debug(f"验证输入框时出错: {e}")
            
            # 修改消息，添加结束标志词提示
            message_with_prompt = message + "。请在完成回答后回复结束标志词'我的回答完毕'"
            logger.debug(f"添加结束标志词提示后的消息: {message_with_prompt}")
            
            # 清空输入框并输入消息
            try:
                input_area.clear()
                # 确保输入框清空
                self.driver.execute_script("arguments[0].value = '';", input_area)
                input_area.send_keys(Keys.CONTROL + "a")
                input_area.send_keys(Keys.DELETE)
                # 输入消息
                input_area.send_keys(message_with_prompt)
                logger.info("已在输入框中输入消息")
            except Exception as e:
                logger.warning(f"通过常规方法输入消息失败: {e}")
                # 尝试使用JavaScript设置值
                try:
                    self.driver.execute_script("arguments[0].value = arguments[1];", input_area, message_with_prompt)
                    logger.info("已通过JavaScript在输入框中输入消息")
                except Exception as e:
                    logger.error(f"通过JavaScript输入消息也失败: {e}")
                    raise AssistantError(f"无法在输入框中输入消息: {e}")
            
            # 查找发送按钮并点击
            send_button = None
            
            # 1. 首先使用精确的JavaScript路径
            try:
                # 使用用户提供的精确路径
                specific_button = self.driver.find_element(By.CSS_SELECTOR, "#send_body_id > div.bottom > div.right > div")
                if specific_button.is_displayed() and specific_button.is_enabled():
                    send_button = specific_button
                    logger.info("使用精确的JavaScript路径找到发送按钮")
            except Exception as e:
                logger.debug(f"使用精确的JavaScript路径查找按钮时出错: {e}")
            
            # 2. 尝试查找特定的send_botton类（注意之前的拼写错误：send_bottom -> send_botton）
            if not send_button:
                try:
                    specific_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".send_botton")
                    for button in specific_buttons:
                        if button.is_displayed() and button.is_enabled():
                            send_button = button
                            logger.info("找到特定的send_botton类发送按钮")
                            break
                except Exception as e:
                    logger.debug(f"查找特定send_botton类按钮时出错: {e}")
            
            # 3. 如果没找到特定类，使用配置中的选择器列表
            if not send_button:
                for selector in send_button_selectors:
                    try:
                        buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for button in buttons:
                            if button.is_displayed() and button.is_enabled():
                                send_button = button
                                logger.info(f"找到发送按钮，选择器: {selector}")
                                break
                        if send_button:
                            break
                    except Exception as e:
                        logger.debug(f"查找发送按钮时出错 (选择器: {selector}): {e}")
                        continue
            
            # 备用方案：通过XPath查找含有"send"或"发送"文本或属性值的按钮
            if not send_button:
                try:
                    # 通过文本或属性查找发送按钮
                    xpath_buttons = self.driver.find_elements(By.XPATH, 
                        "//*[contains(text(), 'send') or contains(text(), '发送') or contains(@class, 'send') or @type='submit']")
                    for button in xpath_buttons:
                        if button.is_displayed() and button.is_enabled():
                            send_button = button
                            logger.info("通过XPath找到发送按钮")
                            break
                except Exception as e:
                    logger.debug(f"通过XPath查找发送按钮时出错: {e}")
            
            # 最终保障：通过JavaScript尝试查找按钮
            if not send_button:
                try:
                    # 使用JavaScript查找所有可能的按钮
                    js_buttons = self.driver.execute_script("""
                        // 先尝试精确的路径
                        const preciseButton = document.querySelector("#send_body_id > div.bottom > div.right > div");
                        if (preciseButton && preciseButton.offsetParent !== null) {
                            return [preciseButton];
                        }
                        
                        // 如果精确路径没找到，尝试其他选择器
                        return Array.from(document.querySelectorAll('button, [role="button"], .button, .btn, .send, .send_botton'))
                            .filter(el => el.offsetParent !== null);
                    """)
                    if js_buttons and len(js_buttons) > 0:
                        # 如果有多个按钮，尝试找右下角位置的那个（通常是发送按钮）
                        if len(js_buttons) > 1:
                            # 获取输入框位置，找最靠近输入框的按钮
                            input_rect = input_area.rect
                            closest_button = None
                            min_distance = float('inf')
                            
                            for btn in js_buttons:
                                btn_rect = btn.rect
                                # 计算按钮与输入框的距离，优先选择输入框右侧的按钮
                                if btn_rect['x'] >= input_rect['x']: # 在输入框右侧
                                    distance = ((btn_rect['x'] - input_rect['x'] - input_rect['width']) ** 2 + 
                                                (btn_rect['y'] - input_rect['y']) ** 2) ** 0.5
                                    if distance < min_distance:
                                        min_distance = distance
                                        closest_button = btn
                            
                            if closest_button:
                                send_button = closest_button
                                logger.info("通过JavaScript和位置关系找到最可能的发送按钮")
                        else:
                            send_button = js_buttons[0]
                            logger.info("通过JavaScript找到发送按钮")
                except Exception as e:
                    logger.debug(f"通过JavaScript查找发送按钮时出错: {e}")
            
            # 如果找到了按钮，尝试点击
            if send_button:
                try:
                    logger.info(f"尝试点击发送按钮 (class: {send_button.get_attribute('class')})")
                    send_button.click()
                    logger.info("成功点击发送按钮")
                except Exception as e:
                    logger.warning(f"直接点击发送按钮失败: {e}")
                    try:
                        # 尝试使用JavaScript点击
                        self.driver.execute_script("arguments[0].click();", send_button)
                        logger.info("使用JavaScript成功点击发送按钮")
                    except Exception as e:
                        logger.warning(f"使用JavaScript点击发送按钮失败: {e}")
                        # 最后的尝试：通过精确路径直接执行点击
                        try:
                            self.driver.execute_script("""
                                const btn = document.querySelector("#send_body_id > div.bottom > div.right > div");
                                if (btn) btn.click();
                            """)
                            logger.info("使用精确路径的JavaScript点击成功")
                        except Exception as e:
                            logger.warning(f"所有点击方法都失败，将使用回车键发送: {e}")
                            input_area.send_keys(Keys.ENTER)
            else:
                # 如果找不到发送按钮，尝试通过回车键发送
                logger.warning("未找到任何发送按钮，使用回车键发送")
                input_area.send_keys(Keys.RETURN)
                logger.info("已通过回车键发送消息")
            
            # 等待回复出现并稳定
            response_text = ""
            previous_response_length = 0
            stable_count = 0
            wait_time = 0
            wait_increment = 0.5
            max_wait_time = 180  # 最长等待3分钟
            
            logger.info("等待AI助手回复...")
            while wait_time < max_wait_time:
                # 1. 首先尝试从md-editor元素获取回复
                try:
                    md_editor_elements = self.driver.execute_script("""
                        return Array.from(document.querySelectorAll('[id^="md-editor-v3_"][id$="-preview"]'))
                            .filter(el => el.offsetParent !== null && el.textContent.trim().length > 0);
                    """)
                    
                    for element in md_editor_elements:
                        try:
                            if element.is_displayed():
                                element_text = element.text
                                if element_text and len(element_text) > len(response_text):
                                    response_text = element_text
                                    logger.debug(f"从md-editor元素获取到中间回复，长度: {len(response_text)}")
                        except Exception:
                            continue
                except Exception:
                    # 如果JavaScript方法失败，继续尝试其他选择器
                    pass
                
                # 2. 如果md-editor元素未找到回复，尝试其他选择器
                if not response_text:
                    for selector in response_selectors:
                        try:
                            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            for element in elements:
                                if not element.is_displayed():
                                    continue
                                element_text = element.text
                                if element_text and len(element_text) > len(response_text):
                                    response_text = element_text
                        except Exception:
                            continue
                
                # 检查回复是否稳定（不再变化）
                if len(response_text) > 0:
                    # 检查是否有结束标志词，如"希望我的回答对你有所帮助"等
                    completion_phrases = [
                        "我的回答完毕",  # 自定义结束标志词（优先检测）
                        "希望我的回答对你有所帮助",
                        "希望这个回答能够帮助到你",
                        "有任何其他问题随时问我",
                        "如有其他问题，请继续提问",
                        "还有其他问题吗"
                    ]
                    
                    # 检查回复文本是否包含完成标志
                    has_completion_phrase = any(phrase in response_text for phrase in completion_phrases)
                    if has_completion_phrase:
                        # 找出匹配的标志词
                        matched_phrase = next((phrase for phrase in completion_phrases if phrase in response_text), None)
                        logger.info(f"检测到回复完成标志词: '{matched_phrase}'，提前结束等待")
                        break
                        
                    # 检查长度是否稳定
                    if len(response_text) == previous_response_length:
                        stable_count += 1
                        if stable_count >= 6:  # 连续3秒没有变化视为回复结束
                            logger.info("回复文本长度已稳定3秒，结束等待")
                            break
                    else:
                        stable_count = 0
                        previous_response_length = len(response_text)
                
                time.sleep(wait_increment)
                wait_time += wait_increment
                
                # 每15秒输出一次等待状态
                if int(wait_time) % 15 == 0 and int(wait_time) > 0:
                    logger.info(f"已等待 {int(wait_time)} 秒，当前回复长度: {len(response_text)}")
            
            # 获取最终回复
            final_response = ""
            response_elements = []
            
            # 1. 首先尝试使用JavaScript查找md-editor动态ID元素（最精确的方法）
            try:
                md_editor_elements = self.driver.execute_script("""
                    // 查找所有以'md-editor-v3_'开头且以'-preview'结尾的元素
                    return Array.from(document.querySelectorAll('[id^="md-editor-v3_"][id$="-preview"]'))
                        .filter(el => el.offsetParent !== null && el.textContent.trim().length > 0);
                """)
                
                if md_editor_elements:
                    logger.info(f"找到 {len(md_editor_elements)} 个md-editor预览元素")
                    for element in md_editor_elements:
                        try:
                            element_text = element.text
                            if element_text and len(element_text) > len(final_response):
                                final_response = element_text
                                logger.debug(f"从md-editor元素获取到长度为{len(element_text)}的回复")
                        except Exception as e:
                            logger.debug(f"提取md-editor元素文本时出错: {e}")
            except Exception as e:
                logger.debug(f"使用JavaScript查找md-editor元素时出错: {e}")
            
            # 2. 如果没有找到回复，使用传统的CSS选择器方法作为备份
            if not final_response:
                for selector in response_selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            response_elements.extend(elements)
                    except Exception as e:
                        logger.debug(f"使用选择器 {selector} 查找元素时出错: {e}")
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
            
            # 3. 最后尝试使用更广泛的XPath查询作为最终备份
            if not final_response:
                try:
                    # 尝试查找带有"preview"或"content"或"response"相关的元素
                    xpath_elements = self.driver.find_elements(By.XPATH, 
                        "//*[contains(@id, 'preview') or contains(@class, 'preview') or contains(@class, 'content') or contains(@class, 'response')]")
                    
                    for element in xpath_elements:
                        try:
                            if element.is_displayed():
                                element_text = element.text
                                if element_text and len(element_text) > len(final_response):
                                    final_response = element_text
                                    logger.debug(f"从XPath元素获取到长度为{len(element_text)}的回复")
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"使用XPath查找元素时出错: {e}")
            
            # 4. 检查iframe中是否存在回复内容
            if not final_response or len(final_response.strip()) < 10:  # 如果回复为空或太短
                try:
                    # 查找所有iframe
                    iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                    
                    if iframes:
                        logger.info(f"找到 {len(iframes)} 个iframe，尝试从中获取回复内容")
                        
                        # 记住当前窗口句柄
                        current_window = self.driver.current_window_handle
                        
                        for i, iframe in enumerate(iframes):
                            try:
                                # 切换到iframe
                                self.driver.switch_to.frame(iframe)
                                logger.debug(f"已切换到iframe {i+1}")
                                
                                # 在iframe中查找md-editor元素
                                iframe_content = self.driver.execute_script("""
                                    // 尝试查找md-editor元素
                                    const editorElements = document.querySelectorAll('[id^="md-editor-v3_"][id$="-preview"]');
                                    if (editorElements.length > 0) {
                                        return Array.from(editorElements)
                                            .map(el => el.textContent)
                                            .join('\\n\\n')
                                            .trim();
                                    }
                                    // 如果没找到特定元素，尝试获取整个body内容
                                    return document.body.textContent.trim();
                                """)
                                
                                if iframe_content and len(iframe_content) > len(final_response):
                                    final_response = iframe_content
                                    logger.info(f"从iframe {i+1}中获取到回复，长度为{len(iframe_content)}")
                                
                                # 返回主文档
                                self.driver.switch_to.default_content()
                            except Exception as e:
                                logger.debug(f"处理iframe {i+1}时出错: {e}")
                                try:
                                    # 确保返回主文档
                                    self.driver.switch_to.default_content()
                                except:
                                    pass
                except Exception as e:
                    logger.debug(f"尝试从iframe获取内容时出错: {e}")
                    # 确保返回主文档
                    try:
                        self.driver.switch_to.default_content()
                    except:
                        pass
            
            logger.info(f"获取到的最终回复长度: {len(final_response)}")
            
            if not final_response:
                raise AssistantError("无法获取AI助手的回复")
                
            # 处理最终响应，移除结束标志词
            end_marker = "我的回答完毕"
            if end_marker in final_response:
                # 找到标记的位置并截取
                marker_index = final_response.find(end_marker)
                # 只保留到标记之前的内容
                final_response = final_response[:marker_index].strip()
                logger.info(f"已从回复中移除结束标志词，处理后的回复长度: {len(final_response)}")
            
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
    
    def _handle_model_selection(self) -> bool:
        """
        处理模型选择界面。在AI助手初始化后，检查是否处于模型选择界面，如果是则选择默认模型。
        
        Returns:
            bool: 是否成功处理了模型选择
        """
        logger.info("检查是否需要选择模型")
        
        # 确保浏览器实例存在
        if not self.driver:
            logger.error("浏览器实例不存在，无法处理模型选择")
            return False
        
        try:
            # 等待页面加载完成
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # 检查当前URL是否在助手页面
            current_url = self.driver.current_url
            if self.assistant_url not in current_url and "chat.buaa.edu.cn" not in current_url:
                logger.warning(f"当前不在AI助手页面: {current_url}")
                return False
            
            # 检查是否存在模型选择元素
            try:
                # 查找可能的模型按钮 - 尝试多种选择器
                model_buttons = []
                model_buttons.extend(self.driver.find_elements(By.CSS_SELECTOR, ".model-card, .model-option, .model-button"))
                model_buttons.extend(self.driver.find_elements(By.XPATH, "//div[contains(@class, 'model')]"))
                model_buttons.extend(self.driver.find_elements(By.XPATH, "//div[contains(text(), 'GPT') or contains(text(), '模型')]"))
                
                # 显示找到的按钮数量
                logger.info(f"找到 {len(model_buttons)} 个可能的模型按钮")
                
                # 尝试点击第一个可见的按钮 (默认选择)
                if model_buttons:
                    for button in model_buttons:
                        if button.is_displayed() and button.is_enabled():
                            logger.info(f"点击模型按钮: {button.text}")
                            # 使用JavaScript点击，避免可能的定位问题
                            self.driver.execute_script("arguments[0].click();", button)
                            time.sleep(2)  # 等待页面响应
                            
                            # 检查是否已进入对话界面
                            textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
                            if any(textarea.is_displayed() for textarea in textareas):
                                logger.info("已进入对话界面")
                                return True
                
                    # 如果循环后仍未进入对话界面，等待更长时间
                    time.sleep(3)
                    
                    # 再次检查是否已进入对话界面
                    textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
                    return any(textarea.is_displayed() for textarea in textareas)
                
                else:
                    # 没有找到模型按钮，可能已经在对话界面
                    logger.info("未找到模型按钮，可能已经在对话界面")
                    textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
                    return any(textarea.is_displayed() for textarea in textareas)
                
            except Exception as e:
                logger.warning(f"处理模型选择界面时出错: {str(e)}")
                return False
            
        except Exception as e:
            logger.warning(f"处理模型选择时发生异常: {str(e)}")
            return False 