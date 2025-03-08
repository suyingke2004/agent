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
        level_name = config.LOGGING_CONFIG.get('level', 'INFO')
        level = getattr(logging, level_name)
    
    # 创建日志记录器
    logger = logging.getLogger('buaa_assistant')
    logger.setLevel(level)
    
    # 清除已有的处理器
    if logger.handlers:
        logger.handlers.clear()
    
    # 创建格式化器
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 根据配置决定是否添加控制台处理器
    console_output = config.LOG_CONFIG.get('console_output', True)
    if console_output:
        # 创建控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # 根据配置决定是否添加控制台处理器
    if config.LOGGING_CONFIG.get('console_output_enabled', False):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # 根据配置决定是否添加文件处理器
    if config.LOGGING_CONFIG.get('file_output_enabled', True):
        log_file = config.LOGGING_CONFIG.get('log_file', 'buaa_assistant.log')
        
        # 确保日志目录存在
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 如果不存在以日期为名的日志文件，则创建
        date_str = datetime.now().strftime('%Y%m%d')
        log_file_path = os.path.join(log_dir, f'{log_file.split(".")[0]}_{date_str}.log')
        
        # 默认10MB，最多5个备份
        max_bytes = 10 * 1024 * 1024
        backup_count = 5
        
        file_handler = RotatingFileHandler(
            log_file_path, 
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
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

def enable_console_output(enable=True):
    """
    启用或禁用控制台日志输出
    
    Args:
        enable: 是否启用控制台输出，默认为True
    """
    # 修改配置
    config.LOGGING_CONFIG['console_output_enabled'] = enable
    
    # 重新设置日志器
    setup_logger()
    
    logger = get_logger()
    if enable:
        logger.info("控制台日志输出已启用")
    else:
        # 这条日志会输出到文件，但不会显示在控制台
        logger.info("控制台日志输出已禁用")

def set_log_level(level_name):
    """
    设置日志级别
    
    Args:
        level_name: 日志级别名称，如'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    """
    if level_name not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
        raise ValueError(f"无效的日志级别: {level_name}")
    
    # 修改配置
    config.LOGGING_CONFIG['level'] = level_name
    
    # 获取日志级别
    level = getattr(logging, level_name)
    
    # 获取logger并设置级别
    logger = logging.getLogger('buaa_assistant')
    logger.setLevel(level)
    
    # 更新所有处理器的级别
    for handler in logger.handlers:
        handler.setLevel(level)
    
    logger.info(f"日志级别已设置为: {level_name}") 