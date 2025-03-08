#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
消息模型模块
定义AI助手对话中的消息数据结构
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
import os

import config

class Message:
    """AI助手消息模型"""
    
    def __init__(
        self,
        role: str,
        content: str,
        message_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        初始化消息
        
        Args:
            role (str): 消息角色，'user'或'assistant'
            content (str): 消息内容
            message_id (str, optional): 消息ID，默认为None自动生成
            timestamp (float, optional): 时间戳，默认为当前时间
            metadata (dict, optional): 元数据，默认为空字典
        """
        self.role = role
        self.content = content
        self.message_id = message_id or f"{int(time.time() * 1000)}_{id(self)}"
        self.timestamp = timestamp or time.time()
        self.metadata = metadata or {}
    
    @property
    def formatted_time(self) -> str:
        """
        获取格式化的时间
        
        Returns:
            str: 格式化的时间字符串
        """
        return datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            dict: 消息字典
        """
        return {
            'role': self.role,
            'content': self.content,
            'message_id': self.message_id,
            'timestamp': self.timestamp,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """
        从字典创建消息
        
        Args:
            data (dict): 消息字典
            
        Returns:
            Message: 消息对象
        """
        return cls(
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            message_id=data.get('message_id'),
            timestamp=data.get('timestamp'),
            metadata=data.get('metadata', {})
        )
    
    def __str__(self) -> str:
        """
        字符串表示
        
        Returns:
            str: 消息字符串表示
        """
        return f"[{self.formatted_time}] {self.role.title()}: {self.content[:50]}{'...' if len(self.content) > 50 else ''}"


class Conversation:
    """对话历史管理"""
    
    def __init__(self, conversation_id: Optional[str] = None, title: Optional[str] = None):
        """
        初始化对话
        
        Args:
            conversation_id (str, optional): 对话ID，默认为None自动生成
            title (str, optional): 对话标题，默认为None
        """
        self.conversation_id = conversation_id or f"conv_{int(time.time() * 1000)}"
        self.title = title or f"对话 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.messages: List[Message] = []
        self.created_at = time.time()
        self.updated_at = time.time()
        self.metadata: Dict[str, Any] = {}
    
    def add_message(self, message: Union[Message, Dict[str, Any]]) -> Message:
        """
        添加消息
        
        Args:
            message (Message or dict): 消息对象或字典
            
        Returns:
            Message: 添加的消息对象
        """
        if isinstance(message, dict):
            message = Message.from_dict(message)
        
        self.messages.append(message)
        self.updated_at = time.time()
        return message
    
    def add_user_message(self, content: str, **kwargs) -> Message:
        """
        添加用户消息
        
        Args:
            content (str): 消息内容
            **kwargs: 其他参数
            
        Returns:
            Message: 添加的消息对象
        """
        message = Message(role='user', content=content, **kwargs)
        return self.add_message(message)
    
    def add_assistant_message(self, content: str, **kwargs) -> Message:
        """
        添加助手消息
        
        Args:
            content (str): 消息内容
            **kwargs: 其他参数
            
        Returns:
            Message: 添加的消息对象
        """
        message = Message(role='assistant', content=content, **kwargs)
        return self.add_message(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            dict: 对话字典
        """
        return {
            'conversation_id': self.conversation_id,
            'title': self.title,
            'messages': [msg.to_dict() for msg in self.messages],
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Conversation':
        """
        从字典创建对话
        
        Args:
            data (dict): 对话字典
            
        Returns:
            Conversation: 对话对象
        """
        conversation = cls(
            conversation_id=data.get('conversation_id'),
            title=data.get('title')
        )
        conversation.created_at = data.get('created_at', time.time())
        conversation.updated_at = data.get('updated_at', time.time())
        conversation.metadata = data.get('metadata', {})
        
        for msg_data in data.get('messages', []):
            conversation.add_message(Message.from_dict(msg_data))
        
        return conversation
    
    def clear(self) -> None:
        """清空对话历史"""
        self.messages = []
        self.updated_at = time.time()
    
    def save(self, file_path: Optional[str] = None) -> str:
        """
        保存对话到文件
        
        Args:
            file_path (str, optional): 文件路径，默认为None使用配置中的历史文件
            
        Returns:
            str: 保存的文件路径
        """
        if file_path is None:
            file_path = config.MESSAGE_CONFIG.get('history_file')
        
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # 读取现有历史记录
        histories = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    histories = json.load(f)
            except Exception:
                pass
        
        # 更新对话
        histories[self.conversation_id] = self.to_dict()
        
        # 保存到文件
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(histories, f, ensure_ascii=False, indent=2)
        
        return file_path
    
    @classmethod
    def load(cls, conversation_id: str, file_path: Optional[str] = None) -> Optional['Conversation']:
        """
        从文件加载对话
        
        Args:
            conversation_id (str): 对话ID
            file_path (str, optional): 文件路径，默认为None使用配置中的历史文件
            
        Returns:
            Conversation or None: 加载的对话对象，如果不存在则返回None
        """
        if file_path is None:
            file_path = config.MESSAGE_CONFIG.get('history_file')
        
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                histories = json.load(f)
            
            conversation_data = histories.get(conversation_id)
            if conversation_data:
                return cls.from_dict(conversation_data)
        except Exception:
            pass
        
        return None
    
    def __len__(self) -> int:
        """获取消息数量"""
        return len(self.messages)
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"Conversation '{self.title}' ({len(self.messages)} messages)" 