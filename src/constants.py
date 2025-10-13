"""
常量定义模块
统一管理所有魔法数字和硬编码字符串
"""

# API相关常量
class APIConstants:
    MODEL_ID = "MBZUAI-IFM/K2-Think"
    MODEL_ID_NOTHINK = "MBZUAI-IFM/K2-Think-nothink"
    MODEL_OWNER = "MBZUAI"
    MODEL_ROOT = "mbzuai-k2-think-2508"
    
    # HTTP状态码
    HTTP_OK = 200
    HTTP_UNAUTHORIZED = 401
    HTTP_NOT_FOUND = 404
    HTTP_INTERNAL_ERROR = 500
    HTTP_GATEWAY_TIMEOUT = 504
    
    # 认证相关
    BEARER_PREFIX = "Bearer "
    BEARER_PREFIX_LENGTH = 7

# 响应相关常量
class ResponseConstants:
    CHAT_COMPLETION_OBJECT = "chat.completion"
    CHAT_COMPLETION_CHUNK_OBJECT = "chat.completion.chunk"
    MODEL_OBJECT = "model"
    LIST_OBJECT = "list"
    
    # 完成原因
    FINISH_REASON_STOP = "stop"
    FINISH_REASON_ERROR = "error"
    
    # 流式响应标记
    STREAM_DONE_MARKER = "data: [DONE]\n\n"
    STREAM_DATA_PREFIX = "data: "

# 内容处理相关常量
class ContentConstants:
    # XML标签
    THINK_START_TAG = "<think>"
    THINK_END_TAG = "</think>"
    ANSWER_START_TAG = "<answer>"
    ANSWER_END_TAG = "</answer>"
    
    # 内容类型
    TEXT_TYPE = "text"
    IMAGE_URL_TYPE = "image_url"
    
    # 图像占位符
    IMAGE_PLACEHOLDER = "[图像内容]"
    
    # 默认值
    DEFAULT_USER_NAME = "User"
    DEFAULT_USER_LOCATION = "Unknown"
    DEFAULT_USER_LANGUAGE = "en-US"
    DEFAULT_TIMEZONE = "Asia/Shanghai"

# 错误消息常量
class ErrorMessages:
    INVALID_API_KEY = "Invalid API key provided"
    AUTHENTICATION_ERROR = "authentication_error"
    UPSTREAM_ERROR = "upstream_error"
    TIMEOUT_ERROR = "timeout_error"
    API_ERROR = "api_error"
    
    # 中文错误消息
    REQUEST_TIMEOUT = "请求超时"
    SERIALIZATION_FAILED = "请求数据序列化失败"
    UPSTREAM_SERVICE_ERROR = "上游服务错误"

# 日志消息常量
class LogMessages:
    MESSAGE_RECEIVED = "📥 接收到的原始消息数: {}"
    ROLE_DISTRIBUTION = "📊 {}消息角色分布: {}"
    JSON_VALIDATION_SUCCESS = "✅ K2Think请求体JSON序列化验证通过"
    JSON_VALIDATION_FAILED = "❌ K2Think请求体JSON序列化失败: {}"
    JSON_FIXED = "🔧 使用default=str修复了序列化问题"
    
    # 动态chunk计算日志
    DYNAMIC_CHUNK_CALC = "动态chunk_size计算: 内容长度={}, 计算值={}, 最终值={}"

# HTTP头常量
class HeaderConstants:
    AUTHORIZATION = "Authorization"
    CONTENT_TYPE = "Content-Type"
    ACCEPT = "Accept"
    ORIGIN = "Origin"
    REFERER = "Referer"
    USER_AGENT = "User-Agent"
    CACHE_CONTROL = "Cache-Control"
    CONNECTION = "Connection"
    X_ACCEL_BUFFERING = "X-Accel-Buffering"
    
    # 值
    APPLICATION_JSON = "application/json"
    TEXT_EVENT_STREAM = "text/event-stream"
    EVENT_STREAM_JSON = "text/event-stream,application/json"
    NO_CACHE = "no-cache"
    KEEP_ALIVE = "keep-alive"
    NO_BUFFERING = "no"
    
    # User-Agent值
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"

# 时间相关常量
class TimeConstants:
    # 时间格式
    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    DATE_FORMAT = "%Y-%m-%d"
    TIME_FORMAT = "%H:%M:%S"
    WEEKDAY_FORMAT = "%A"
    
    # 微秒转换
    MICROSECONDS_MULTIPLIER = 1000000

# 数值常量
class NumericConstants:
    # chunk大小限制
    MIN_CHUNK_SIZE = 50
    
    # 内容预览长度
    CONTENT_PREVIEW_LENGTH = 200
    CONTENT_PREVIEW_SUFFIX = "..."
    
    # 默认token使用量
    DEFAULT_PROMPT_TOKENS = 0
    DEFAULT_COMPLETION_TOKENS = 0
    DEFAULT_TOTAL_TOKENS = 0