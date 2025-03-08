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
from bs4 import BeautifulSoup
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
            username (str, optional): 用户名（学号），默认从配置中获取
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
        
        # 设置请求头
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Referer': 'https://sso.buaa.edu.cn/login',
        }
        self.session.headers.update(self.headers)
    
    def login_with_requests(self) -> bool:
        """
        使用requests库登录
        
        Returns:
            bool: 登录是否成功
        """
        logger.info(f"使用requests登录统一身份认证 (用户: {self.username})")
        
        try:
            # 第一步：访问登录页面获取必要参数
            logger.debug("访问登录页面获取参数")
            login_response = self.session.get(self.login_url, allow_redirects=True)
            login_response.raise_for_status()
            
            # 解析HTML
            soup = BeautifulSoup(login_response.text, 'html.parser')
            
            # 提取execution值
            execution_input = soup.find('input', {'name': 'execution'})
            if not execution_input:
                logger.error("无法提取execution参数")
                return False
            execution = execution_input.get('value', '')
            
            # 提取_csrf值
            csrf_input = soup.find('input', {'name': '_csrf'})
            if not csrf_input:
                logger.error("无法提取_csrf参数")
                return False
            csrf_token = csrf_input.get('value', '')
            
            # 检查是否需要验证码
            captcha_parent = soup.find('div', {'id': 'captchaParent'})
            need_captcha = captcha_parent and 'display: none;' not in captcha_parent.get('style', '')
            captcha = ''
            
            if need_captcha:
                logger.warning("登录需要验证码，直接使用requests方式可能会失败")
                # 这里可以尝试处理验证码，但更建议使用Selenium方式
            
            # 第二步：构造登录数据
            login_data = {
                'username': self.username,
                'password': self.password,
                '_csrf': csrf_token,
                'execution': execution,
                '_eventId': 'submit',
                'type': 'username_password',
                'geolocation': ''
            }
            
            if need_captcha and captcha:
                login_data['captcha'] = captcha
            
            # 第三步：提交登录请求
            logger.debug("提交登录表单")
            login_submit_response = self.session.post(
                self.login_url,
                data=login_data,
                allow_redirects=True
            )
            
            # 第四步：检查登录是否成功
            if "统一身份认证" in login_submit_response.text and "登录" in login_submit_response.text:
                if "认证信息无效" in login_submit_response.text or "Invalid credentials" in login_submit_response.text:
                    logger.error("统一身份认证登录失败：用户名或密码错误")
                    return False
                elif "验证码错误" in login_submit_response.text:
                    logger.error("统一身份认证登录失败：验证码错误")
                    return False
                else:
                    logger.error("统一身份认证登录失败：未知原因")
                    return False
            
            # 登录成功，更新cookies
            self.cookies = dict(self.session.cookies)
            
            # 第五步：如果有重定向URL，尝试访问
            if self.redirect_url:
                logger.debug(f"访问重定向URL: {self.redirect_url}")
                redirect_response = self.session.get(self.redirect_url, allow_redirects=True)
                redirect_response.raise_for_status()
                self.cookies.update(dict(self.session.cookies))
            
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
            logger.debug(f"访问登录页面: {self.login_url}")
            self.driver.get(self.login_url)
            
            # 等待登录表单加载完成
            try:
                # 等待登录页面中的iframe加载完成
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "loginIframe"))
                )
                
                # 切换到iframe内部
                iframe = self.driver.find_element(By.ID, "loginIframe")
                self.driver.switch_to.frame(iframe)
                
                # 等待用户名输入框加载完成
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "unPassword"))
                )
            except TimeoutException:
                # 如果无法找到iframe或者iframe中的元素，尝试直接查找表单元素
                logger.warning("未找到iframe或iframe中的元素，尝试直接查找表单元素")
                try:
                    # 等待用户名输入框加载完成
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.NAME, "username"))
                    )
                except TimeoutException:
                    logger.error("登录表单未正确加载")
                    self.quit_driver()
                    return False
            
            # 尝试在iframe中填写表单
            try:
                username_input = self.driver.find_element(By.ID, "unPassword")
                password_input = self.driver.find_element(By.ID, "pwPassword")
                
                username_input.clear()
                username_input.send_keys(self.username)
                password_input.clear()
                password_input.send_keys(self.password)
                
                # 检查是否需要输入验证码
                try:
                    captcha_div = self.driver.find_element(By.ID, "captchaPasswor")
                    if captcha_div.is_displayed():
                        logger.info("需要输入验证码")
                        # 等待用户手动输入验证码
                        if not headless:
                            logger.info("请在浏览器窗口中手动输入验证码，然后等待自动提交")
                            # 等待用户输入验证码
                            time.sleep(15)
                except NoSuchElementException:
                    logger.debug("无需输入验证码")
                
                # 提交表单
                login_button = self.driver.find_element(By.CSS_SELECTOR, ".submit-btn")
                login_button.click()
            except NoSuchElementException:
                # 如果无法在iframe中找到元素，切回主文档尝试
                self.driver.switch_to.default_content()
                
                # 尝试在主文档中填写表单
                try:
                    username_input = self.driver.find_element(By.NAME, "username")
                    password_input = self.driver.find_element(By.NAME, "password")
                    
                    username_input.clear()
                    username_input.send_keys(self.username)
                    password_input.clear()
                    password_input.send_keys(self.password)
                    
                    # 检查是否需要输入验证码
                    try:
                        captcha_div = self.driver.find_element(By.ID, "captchaParent")
                        if captcha_div.is_displayed():
                            logger.info("需要输入验证码")
                            # 等待用户手动输入验证码
                            if not headless:
                                logger.info("请在浏览器窗口中手动输入验证码，然后等待自动提交")
                                # 等待用户输入验证码
                                time.sleep(15)
                    except NoSuchElementException:
                        logger.debug("无需输入验证码")
                    
                    # 提交表单
                    submit_button = self.driver.find_element(By.NAME, "submit")
                    submit_button.click()
                except NoSuchElementException as e:
                    logger.error(f"找不到登录表单元素: {str(e)}")
                    self.quit_driver()
                    return False
            
            # 等待登录完成
            try:
                # 等待重定向完成
                WebDriverWait(self.driver, 15).until(
                    lambda driver: "sso.buaa.edu.cn/login" not in driver.current_url
                )
            except TimeoutException:
                # 检查是否失败
                if "认证信息无效" in self.driver.page_source or "Invalid credentials" in self.driver.page_source:
                    logger.error("统一身份认证登录失败：用户名或密码错误")
                    self.quit_driver()
                    return False
                elif "验证码错误" in self.driver.page_source:
                    logger.error("统一身份认证登录失败：验证码错误")
                    self.quit_driver()
                    return False
                else:
                    logger.error("统一身份认证登录超时")
                    self.quit_driver()
                    return False
            
            # 获取cookies
            selenium_cookies = self.driver.get_cookies()
            for cookie in selenium_cookies:
                self.cookies[cookie['name']] = cookie['value']
                self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            
            # 如果有重定向URL，尝试访问
            if self.redirect_url:
                logger.debug(f"访问重定向URL: {self.redirect_url}")
                self.driver.get(self.redirect_url)
                
                # 等待页面加载完成
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda driver: driver.execute_script("return document.readyState") == "complete"
                    )
                    
                    # 更新cookies
                    selenium_cookies = self.driver.get_cookies()
                    for cookie in selenium_cookies:
                        self.cookies[cookie['name']] = cookie['value']
                        self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                except TimeoutException:
                    logger.warning("重定向页面加载超时")
            
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
            # 检查页面内容中是否有登录表单的特征
            elif response.status_code == 200:
                if 'sso.buaa.edu.cn/login' in response.url or '统一身份认证' in response.text and '登录' in response.text:
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