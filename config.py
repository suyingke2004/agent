"""
北航AI助手自动访问工具配置文件
"""
import os
from dotenv import load_dotenv

# 加载.env文件中的环境变量（如果存在）
load_dotenv()

# 北航统一身份认证
AUTH_CONFIG = {
    # 统一身份认证用户名和密码（优先从环境变量获取）
    'username': os.getenv('BUAA_USERNAME', ''),  # 学号
    'password': os.getenv('BUAA_PASSWORD', ''),  # 密码
    # 认证相关URL
    'login_url': 'https://sso.buaa.edu.cn/login',
    'redirect_url': 'https://chat.buaa.edu.cn/',
}

# AI助手配置
ASSISTANT_CONFIG = {
    # AI助手URL
    'xiaohang_url': 'https://chat.buaa.edu.cn/page/site/newPc',
    'tongyi_url': 'https://chat.buaa.edu.cn/page/app/tongyi',
    
    # 默认使用的助手类型: 'xiaohang' 或 'tongyi'
    'default_assistant': 'xiaohang',
    
    # 请求头
    'headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'https://chat.buaa.edu.cn',
        'Referer': 'https://chat.buaa.edu.cn/page/site/newPc',
    },
    
    # API端点
    'api_base_path': '',  # 从网页分析确定
    
    # 请求配置
    'timeout': 60,  # 请求超时时间（秒）
    'max_retries': 3,  # 最大重试次数
    'retry_delay': 2,  # 重试间隔（秒）
}

# 浏览器驱动配置（使用Selenium时）
WEBDRIVER_CONFIG = {
    'browser': 'chrome',  # 'chrome', 'firefox', 'edge'
    'headless': False,    # 是否使用无头模式（无界面）
    'implicit_wait': 10,  # 隐式等待时间（秒）
    'page_load_timeout': 30,  # 页面加载超时时间（秒）
    'download_path': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads'),
    'use_browser_first': True,  # API方式已禁用，强制使用浏览器模拟模式
    'wait_for_answer': 60,  # 等待AI回答的最大时间（秒）
    'keep_browser_open': False,  # 是否在程序结束时保持浏览器开启状态
    'element_selectors': {
        # 输入框选择器
        'input_selectors': [
            "textarea.n-input__textarea-el",
            ".chat-input",
            "[placeholder]",
            "textarea"
        ],
        # 发送按钮选择器
        'send_button_selectors': [
            "button[type='submit']",
            ".send-button",
            "button.n-button",
            "button"
        ],
        # 回复文本选择器
        'response_selectors': [
            ".chat-assistant .text",
            ".chat-message-text",
            ".assistant-message",
            ".reply .text"
        ]
    }
}

# 日志配置
LOG_CONFIG = {
    'log_level': 'INFO',  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    'log_file': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'assistant.log'),
    'max_log_size': 10 * 1024 * 1024,  # 10MB
    'backup_count': 5,
}

# 消息处理配置
MESSAGE_CONFIG = {
    'max_message_length': 2000,  # 单条消息最大长度
    'history_file': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'history.json'),
} 