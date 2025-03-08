#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日志工具模块
"""

import os
import logging
from logging.handlers import RotatingFileHandler
import sys
from datetime import datetime
import config

def setup_logger(level=None):
    """
    设置日志记录器
    
    Args:
        level: 日志级别，默认为None，将使用配置文件中的设置
        
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    # 从配置中获取日志级别
    if level is None:
        level_name = config.LOG_CONFIG.get('log_level', 'INFO')
        level = getattr(logging, level_name)
    
    # 创建日志记录器
    logger = logging.getLogger('buaa_assistant')
    logger.setLevel(level)
    
    # 清除已有的处理器
    if logger.handlers:
        logger.handlers.clear()
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # 创建文件处理器
    log_file = config.LOG_CONFIG.get('log_file')
    
    # 确保日志目录存在
    if log_file:
        log_dir = os.path.dirname(log_file)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 如果不存在以日期为名的日志文件，则创建
        date_str = datetime.now().strftime('%Y%m%d')
        log_file_path = os.path.join(log_dir, f'assistant_{date_str}.log')
        
        max_bytes = config.LOG_CONFIG.get('max_log_size', 10 * 1024 * 1024)  # 默认10MB
        backup_count = config.LOG_CONFIG.get('backup_count', 5)
        
        file_handler = RotatingFileHandler(
            log_file_path, 
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        
        # 将文件处理器添加到日志记录器
        logger.addHandler(file_handler)
    
    # 创建格式化器
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 设置格式化器
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    if log_file and 'file_handler' in locals():
        file_handler.setFormatter(formatter)
    
    return logger

def get_logger():
    """
    获取配置好的日志记录器
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger('buaa_assistant')
    
    # 如果logger没有处理器，则初始化
    if not logger.handlers:
        logger = setup_logger()
        
    return logger 