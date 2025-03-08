# 北航AI助手自动访问工具

## 项目介绍
本项目用于自动访问北航AI助手（小航AI助手/北航通义千问），提供自动登录、发送消息、获取回复等功能，方便用户批量处理或自动化交互。

## 功能特性
- 自动完成校内统一认证登录
- 访问小航AI助手和北航通义千问
- 自动发送消息并获取回复
- 支持批量处理问题
- 支持导出对话记录
- 提供重试机制，确保稳定连接

## 环境要求
- Python 3.8+
- 依赖库：见requirements.txt

## 项目结构
```
.
├── README.md                 # 项目说明文档
├── requirements.txt          # 项目依赖
├── config.py                 # 配置文件
├── main.py                   # 主程序入口
├── websites/                 # 北航AI助手网页源码（参考用）
├── src/                      # 源代码
│   ├── __init__.py           
│   ├── auth.py               # 校内统一认证模块
│   ├── assistant.py          # AI助手交互模块
│   ├── utils/                # 工具函数
│   │   ├── __init__.py
│   │   ├── http.py           # HTTP请求工具
│   │   └── logger.py         # 日志工具
│   └── models/               # 数据模型
│       ├── __init__.py
│       └── message.py        # 消息模型
└── examples/                 # 使用示例
    ├── simple_chat.py        # 简单对话示例  
    └── batch_process.py      # 批量处理示例
```

## 安装方法
1. 确保已安装Python 3.8或更高版本
2. 克隆本项目到本地
3. 安装依赖：
```bash
pip install -r requirements.txt
```
4. 配置config.py中的个人信息或使用.env文件配置个人信息
   .env文件示例：
   ```
   BUAA_USERNAME=你的学号
   BUAA_PASSWORD=你的密码
   ```

## 使用方法

### 1. 基本使用
```python
from src.assistant import AIAssistant

# 创建助手实例（会自动完成登录）
assistant = AIAssistant(username="你的学号", password="你的密码")

# 发送消息并获取回复
response = assistant.chat("请介绍一下北航的历史")
print(response)

# 关闭会话
assistant.close()
```

### 2. 批量处理
```python
from src.assistant import AIAssistant
import csv

# 创建助手实例
assistant = AIAssistant(username="你的学号", password="你的密码")

# 从CSV文件读取问题并处理
with open('questions.csv', 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    next(reader)  # 跳过表头
    
    results = []
    for row in reader:
        question = row[0]
        response = assistant.chat(question)
        results.append([question, response])

# 保存结果
with open('results.csv', 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['问题', '回答'])
    writer.writerows(results)

# 关闭会话
assistant.close()
```

## 注意事项
1. 请合理使用该工具，避免频繁请求对服务器造成压力
2. 密码等敏感信息建议通过环境变量或配置文件提供，避免硬编码在代码中
3. 本工具仅用于学习和研究，请勿用于任何非法用途

## 维护与更新
- 如遇到问题或有新需求，请提交Issue
- 欢迎提交Pull Request贡献代码 

## 已知问题：
