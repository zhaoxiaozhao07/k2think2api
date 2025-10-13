"""
数据模型定义
定义所有API请求和响应的数据模型
"""
from pydantic import BaseModel
from typing import List, Dict, Optional, Union, Any

class ImageUrl(BaseModel):
    """Image URL model for vision content"""
    url: str
    detail: Optional[str] = "auto"

class ContentPart(BaseModel):
    """Content part model for OpenAI's new content format"""
    type: str
    text: Optional[str] = None
    image_url: Optional[ImageUrl] = None

class Message(BaseModel):
    role: str
    content: Optional[Union[str, List[ContentPart]]] = None
    tool_call_id: Optional[str] = None  # 用于tool消息
    tool_calls: Optional[List[Dict[str, Any]]] = None  # 用于assistant消息

class FunctionParameters(BaseModel):
    """Function parameters schema"""
    type: str = "object"
    properties: Dict[str, Any] = {}
    required: Optional[List[str]] = None
    
class FunctionDefinition(BaseModel):
    """Function definition"""
    name: str
    description: Optional[str] = None
    parameters: Optional[FunctionParameters] = None

class ToolDefinition(BaseModel):
    """Tool definition"""
    type: str = "function"
    function: FunctionDefinition

class ToolChoice(BaseModel):
    """Tool choice specification"""
    type: str = "function"
    function: Dict[str, str]  # {"name": "tool_name"}

class ChatCompletionRequest(BaseModel):
    model: str = "MBZUAI-IFM/K2-Think"
    messages: List[Message]
    stream: bool = False
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    # 工具调用相关字段
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, ToolChoice]] = None  # "auto", "none", 或指定工具

class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str
    permission: List[Dict] = []
    root: str
    parent: Optional[str] = None

class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelInfo]