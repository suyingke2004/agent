#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
HTTP请求工具模块
"""

import requests
import time
import json
from retry import retry
from urllib.parse import urljoin
from fake_useragent import UserAgent
import logging

from src.utils.logger import get_logger
import config

# 获取日志记录器
logger = get_logger()

class HTTPClient:
    """HTTP请求客户端"""
    
    def __init__(self, base_url=None, headers=None, timeout=None, max_retries=None, retry_delay=None):
        """
        初始化HTTP客户端
        
        Args:
            base_url (str, optional): 基础URL，所有请求都会以此为前缀
            headers (dict, optional): 请求头
            timeout (int, optional): 超时时间(秒)
            max_retries (int, optional): 最大重试次数
            retry_delay (int, optional): 重试间隔(秒)
        """
        # 设置默认值
        self.base_url = base_url or ''
        self.headers = headers or {}
        self.timeout = timeout or config.ASSISTANT_CONFIG.get('timeout', 60)
        self.max_retries = max_retries or config.ASSISTANT_CONFIG.get('max_retries', 3) 
        self.retry_delay = retry_delay or config.ASSISTANT_CONFIG.get('retry_delay', 2)
        
        # 创建会话
        self.session = requests.Session()
        
        # 如果没有设置User-Agent，则随机生成一个
        if 'User-Agent' not in self.headers:
            try:
                self.headers['User-Agent'] = UserAgent().random
            except Exception:
                self.headers['User-Agent'] = config.ASSISTANT_CONFIG.get('headers', {}).get(
                    'User-Agent', 
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
        
        # 更新会话的headers
        self.session.headers.update(self.headers)
    
    def _get_full_url(self, url):
        """
        获取完整URL
        
        Args:
            url (str): 相对或绝对URL
            
        Returns:
            str: 完整URL
        """
        if url.startswith(('http://', 'https://')):
            return url
        return urljoin(self.base_url, url)
    
    def _log_request(self, method, url, **kwargs):
        """
        记录请求日志
        
        Args:
            method (str): 请求方法
            url (str): 请求URL
            **kwargs: 其他参数
        """
        logger.debug(f"{method.upper()} {url}")
        if 'params' in kwargs and kwargs['params']:
            logger.debug(f"Params: {kwargs['params']}")
        if 'data' in kwargs and kwargs['data']:
            logger.debug(f"Data: {kwargs.get('data')}")
        if 'json' in kwargs and kwargs['json']:
            logger.debug(f"JSON: {json.dumps(kwargs['json'], ensure_ascii=False)}")
    
    def _log_response(self, response):
        """
        记录响应日志
        
        Args:
            response (requests.Response): 响应对象
        """
        logger.debug(f"Status: {response.status_code}")
        logger.debug(f"Headers: {dict(response.headers)}")
        
        # 尝试解析响应内容
        try:
            if response.headers.get('Content-Type', '').startswith('application/json'):
                logger.debug(f"Response: {json.dumps(response.json(), ensure_ascii=False)}")
            else:
                logger.debug(f"Response: {response.text[:200]}{'...' if len(response.text) > 200 else ''}")
        except Exception as e:
            logger.debug(f"Failed to parse response: {str(e)}")
    
    @retry(tries=3, delay=2, backoff=2, logger=logger)
    def request(self, method, url, **kwargs):
        """
        发送HTTP请求
        
        Args:
            method (str): 请求方法
            url (str): 请求URL
            **kwargs: 其他参数
            
        Returns:
            requests.Response: 响应对象
        """
        # 获取完整URL
        full_url = self._get_full_url(url)
        
        # 设置超时时间
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout
        
        # 记录请求日志
        self._log_request(method, full_url, **kwargs)
        
        # 发送请求
        try:
            response = self.session.request(method, full_url, **kwargs)
            
            # 记录响应日志
            self._log_response(response)
            
            # 检查响应状态码
            response.raise_for_status()
            
            return response
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {method.upper()} {full_url}, error: {str(e)}")
            raise
    
    def get(self, url, params=None, **kwargs):
        """
        发送GET请求
        
        Args:
            url (str): 请求URL
            params (dict, optional): 查询参数
            **kwargs: 其他参数
            
        Returns:
            requests.Response: 响应对象
        """
        return self.request('get', url, params=params, **kwargs)
    
    def post(self, url, data=None, json=None, **kwargs):
        """
        发送POST请求
        
        Args:
            url (str): 请求URL
            data (dict, optional): 表单数据
            json (dict, optional): JSON数据
            **kwargs: 其他参数
            
        Returns:
            requests.Response: 响应对象
        """
        return self.request('post', url, data=data, json=json, **kwargs)
    
    def put(self, url, data=None, **kwargs):
        """
        发送PUT请求
        
        Args:
            url (str): 请求URL
            data (dict, optional): 请求数据
            **kwargs: 其他参数
            
        Returns:
            requests.Response: 响应对象
        """
        return self.request('put', url, data=data, **kwargs)
    
    def delete(self, url, **kwargs):
        """
        发送DELETE请求
        
        Args:
            url (str): 请求URL
            **kwargs: 其他参数
            
        Returns:
            requests.Response: 响应对象
        """
        return self.request('delete', url, **kwargs)
    
    def close(self):
        """关闭会话"""
        self.session.close() 