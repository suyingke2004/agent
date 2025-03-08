#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
校内统一认证模块
处理北航统一身份认证登录
"""

import time
import re
import json
import logging
from typing import Dict, Optional, Tuple, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from src.utils.logger import get_logger
from src.utils.http import HTTPClient
import config

# 获取日志记录器
logger = get_logger()

class AuthError(Exception):
    """认证错误"""
    pass

class BUAAAuth:
    """北航统一身份认证"""
    
    def __init__(self, username: str = None, password: str = None):
        """
        初始化北航统一身份认证
        
        Args:
            username (str, optional): 用户名，默认从配置中获取
            password (str, optional): 密码，默认从配置中获取
        """
        self.username = username or config.AUTH_CONFIG.get('username', '')
        self.password = password or config.AUTH_CONFIG.get('password', '')
        self.login_url = config.AUTH_CONFIG.get('login_url', 'https://sso.buaa.edu.cn/login')
        self.redirect_url = config.AUTH_CONFIG.get('redirect_url', 'https://chat.buaa.edu.cn/')
        
        self.http_client = HTTPClient()
        self.session = requests.Session()
        self.cookies = {}
        self.is_authenticated = False
        self.driver = None
    
    def login_with_requests(self) -> bool:
        """
        使用requests库登录
        
        Returns:
            bool: 登录是否成功
        """
        logger.info(f"使用requests登录统一身份认证 (用户: {self.username})")
        
        try:
            # 访问登录页面获取CSRF令牌
            response = self.session.get(self.login_url)
            response.raise_for_status()
            
            # 提取CSRF令牌
            csrf_token_match = re.search(r'name="_csrf" value="([^"]+)"', response.text)
            if not csrf_token_match:
                logger.error("无法提取CSRF令牌")
                return False
            
            csrf_token = csrf_token_match.group(1)
            
            # 构造登录数据
            login_data = {
                'username': self.username,
                'password': self.password,
                '_csrf': csrf_token,
                'execution': 'e1s1',  # 可能需要动态获取
                '_eventId': 'submit',
                'geolocation': ''
            }
            
            # 发送登录请求
            response = self.session.post(self.login_url, data=login_data, allow_redirects=True)
            
            # 检查登录是否成功
            if "认证失败" in response.text or "Authentication Failure" in response.text:
                logger.error("统一身份认证登录失败：用户名或密码错误")
                return False
            
            # 更新cookies
            self.cookies = dict(self.session.cookies)
            
            # 如果有重定向URL，尝试访问
            if self.redirect_url:
                response = self.session.get(self.redirect_url)
                response.raise_for_status()
            
            self.is_authenticated = True
            logger.info("统一身份认证登录成功")
            return True
            
        except Exception as e:
            logger.error(f"统一身份认证登录失败: {str(e)}")
            return False
    
    def login_with_selenium(self) -> bool:
        """
        使用Selenium库登录
        
        Returns:
            bool: 登录是否成功
        """
        logger.info(f"使用Selenium登录统一身份认证 (用户: {self.username})")
        
        try:
            # 配置浏览器
            browser_config = config.WEBDRIVER_CONFIG
            browser_type = browser_config.get('browser', 'chrome').lower()
            headless = browser_config.get('headless', False)
            
            # 初始化WebDriver
            options = None
            if browser_type == 'chrome':
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.chrome.service import Service
                options = Options()
                if headless:
                    options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                options.add_experimental_option('excludeSwitches', ['enable-logging'])
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
            
            elif browser_type == 'firefox':
                from selenium.webdriver.firefox.options import Options
                from selenium.webdriver.firefox.service import Service
                options = Options()
                if headless:
                    options.add_argument('--headless')
                service = Service(GeckoDriverManager().install())
                self.driver = webdriver.Firefox(service=service, options=options)
            
            elif browser_type == 'edge':
                from selenium.webdriver.edge.options import Options
                from selenium.webdriver.edge.service import Service
                options = Options()
                if headless:
                    options.add_argument('--headless')
                service = Service(EdgeChromiumDriverManager().install())
                self.driver = webdriver.Edge(service=service, options=options)
            
            else:
                logger.error(f"不支持的浏览器类型: {browser_type}")
                return False
            
            # 设置浏览器等待时间
            self.driver.implicitly_wait(browser_config.get('implicit_wait', 10))
            self.driver.set_page_load_timeout(browser_config.get('page_load_timeout', 30))
            
            # 访问登录页面
            self.driver.get(self.login_url)
            
            # 填写登录表单
            username_input = self.driver.find_element(By.ID, 'username')
            password_input = self.driver.find_element(By.ID, 'password')
            
            username_input.clear()
            username_input.send_keys(self.username)
            password_input.clear()
            password_input.send_keys(self.password)
            
            # 提交表单
            submit_button = self.driver.find_element(By.NAME, 'submit')
            submit_button.click()
            
            # 等待登录完成
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda driver: "认证失败" in driver.page_source or 
                    "Authentication Failure" in driver.page_source or
                    driver.current_url != self.login_url
                )
            except TimeoutException:
                logger.error("登录超时")
                self.quit_driver()
                return False
            
            # 检查登录是否成功
            if "认证失败" in self.driver.page_source or "Authentication Failure" in self.driver.page_source:
                logger.error("统一身份认证登录失败：用户名或密码错误")
                self.quit_driver()
                return False
            
            # 获取cookies
            selenium_cookies = self.driver.get_cookies()
            for cookie in selenium_cookies:
                self.cookies[cookie['name']] = cookie['value']
                self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            
            # 如果有重定向URL，尝试访问
            if self.redirect_url:
                self.driver.get(self.redirect_url)
                # 等待页面加载完成
                WebDriverWait(self.driver, 10).until(
                    lambda driver: driver.current_url.startswith(self.redirect_url)
                )
                
                # 更新cookies
                selenium_cookies = self.driver.get_cookies()
                for cookie in selenium_cookies:
                    self.cookies[cookie['name']] = cookie['value']
                    self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            
            self.is_authenticated = True
            logger.info("统一身份认证登录成功")
            return True
            
        except Exception as e:
            logger.error(f"统一身份认证登录失败: {str(e)}")
            return False
        finally:
            # 关闭浏览器
            self.quit_driver()
    
    def login(self) -> bool:
        """
        登录统一身份认证
        
        Returns:
            bool: 登录是否成功
        """
        # 先尝试使用requests登录
        if self.login_with_requests():
            return True
        
        logger.info("使用requests登录失败，尝试使用Selenium登录")
        # 如果失败，尝试使用Selenium登录
        return self.login_with_selenium()
    
    def get_cookies(self) -> Dict[str, str]:
        """
        获取cookies
        
        Returns:
            dict: cookies字典
        """
        if not self.is_authenticated:
            self.login()
        
        return self.cookies
    
    def get_headers(self) -> Dict[str, str]:
        """
        获取请求头
        
        Returns:
            dict: 请求头字典
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Origin': 'https://chat.buaa.edu.cn',
            'Referer': 'https://chat.buaa.edu.cn/'
        }
        
        if self.cookies:
            # 添加cookie字符串到请求头
            cookie_str = '; '.join([f"{k}={v}" for k, v in self.cookies.items()])
            headers['Cookie'] = cookie_str
        
        return headers
    
    def get_session(self) -> requests.Session:
        """
        获取会话
        
        Returns:
            requests.Session: 会话对象
        """
        if not self.is_authenticated:
            self.login()
        
        return self.session
    
    def is_login_required(self, url: str) -> bool:
        """
        检查是否需要登录
        
        Args:
            url (str): 要检查的URL
            
        Returns:
            bool: 是否需要登录
        """
        try:
            response = self.session.get(url, allow_redirects=False)
            # 如果状态码是302或301，检查是否重定向到登录页面
            if response.status_code in (301, 302):
                location = response.headers.get('Location', '')
                if 'login' in location or 'sso.buaa.edu.cn' in location:
                    return True
            return False
        except Exception as e:
            logger.error(f"检查登录状态失败: {str(e)}")
            return True
    
    def quit_driver(self) -> None:
        """关闭WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"关闭WebDriver失败: {str(e)}")
            finally:
                self.driver = None 