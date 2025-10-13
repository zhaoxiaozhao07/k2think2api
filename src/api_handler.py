"""
API处理模块
处理主要的API路由逻辑
"""
import json
import time
import asyncio
import logging
from typing import Dict, List
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from src.config import Config
from src.constants import (
    APIConstants, ResponseConstants, LogMessages, 
    ErrorMessages, HeaderConstants
)
from src.exceptions import (
    AuthenticationError, SerializationError, 
    K2ThinkProxyError, UpstreamError
)
from src.models import ChatCompletionRequest, ModelsResponse, ModelInfo
from src.response_processor import ResponseProcessor
from src.token_manager import TokenManager
from src.utils import safe_log_error, safe_log_info, safe_log_warning
from src.toolify_handler import should_enable_toolify, prepare_toolify_request

logger = logging.getLogger(__name__)

class APIHandler:
    """API处理器"""
    
    def __init__(self, config: Config):
        self.config = config
        self.response_processor = ResponseProcessor(config)
        self.token_manager = config.get_token_manager()
    
    def validate_api_key(self, authorization: str) -> bool:
        """验证API密钥"""
        if not authorization or not authorization.startswith(APIConstants.BEARER_PREFIX):
            return False
        api_key = authorization[APIConstants.BEARER_PREFIX_LENGTH:]  # 移除 "Bearer " 前缀
        return api_key == self.config.VALID_API_KEY
    
    def should_output_thinking(self, model_name: str) -> bool:
        """根据模型名判断是否应该输出思考内容"""
        return model_name != APIConstants.MODEL_ID_NOTHINK
    
    def get_actual_model_id(self, model_name: str) -> str:
        """获取实际的模型ID（将nothink版本映射回原始模型）"""
        if model_name == APIConstants.MODEL_ID_NOTHINK:
            return APIConstants.MODEL_ID
        return model_name
    
    async def get_models(self) -> ModelsResponse:
        """获取模型列表"""
        model_info_standard = ModelInfo(
            id=APIConstants.MODEL_ID,
            created=int(time.time()),
            owned_by=APIConstants.MODEL_OWNER,
            root=APIConstants.MODEL_ROOT
        )
        model_info_nothink = ModelInfo(
            id=APIConstants.MODEL_ID_NOTHINK,
            created=int(time.time()),
            owned_by=APIConstants.MODEL_OWNER,
            root=APIConstants.MODEL_ROOT
        )
        return ModelsResponse(data=[model_info_standard, model_info_nothink])
    
    async def chat_completions(self, request: ChatCompletionRequest, auth_request: Request):
        """处理聊天补全请求"""
        # 验证API密钥
        authorization = auth_request.headers.get(HeaderConstants.AUTHORIZATION, "")
        if not self.validate_api_key(authorization):
            raise AuthenticationError()
        
        # 判断是否应该输出思考内容
        output_thinking = self.should_output_thinking(request.model)
        actual_model_id = self.get_actual_model_id(request.model)
        
        try:
            # 处理消息
            raw_messages = self._process_raw_messages(request.messages)
            
            # 检查是否需要启用工具调用
            request_dict = request.model_dump()
            enable_toolify = should_enable_toolify(request_dict)
            
            # 如果启用工具调用，预处理消息并注入提示词
            if enable_toolify:
                safe_log_info(logger, "[TOOLIFY] 工具调用功能已启用")
                raw_messages, _ = prepare_toolify_request(request_dict, raw_messages)
            
            self._log_request_info(raw_messages)
            
            # 构建K2Think请求
            k2think_payload = self._build_k2think_payload(
                request, raw_messages, actual_model_id
            )
            
            # 验证JSON序列化
            self._validate_json_serialization(k2think_payload)
            
            # 处理响应（带重试机制）
            if request.stream:
                return await self._handle_stream_response_with_retry(
                    request, k2think_payload, output_thinking, enable_toolify
                )
            else:
                return await self._handle_non_stream_response_with_retry(
                    request, k2think_payload, output_thinking, enable_toolify
                )
                
        except K2ThinkProxyError:
            # 重新抛出自定义异常
            raise
        except Exception as e:
            safe_log_error(logger, "API转发错误", e)
            raise HTTPException(
                status_code=APIConstants.HTTP_INTERNAL_ERROR,
                detail={
                    "error": {
                        "message": str(e),
                        "type": ErrorMessages.API_ERROR
                    }
                }
            )
    
    def _process_raw_messages(self, messages: List) -> List[Dict]:
        """处理原始消息"""
        raw_messages = []
        for msg in messages:
            try:
                raw_messages.append({
                    "role": msg.role, 
                    "content": msg.content  # 保持原始格式，稍后再转换
                })
            except Exception as e:
                safe_log_error(logger, f"处理消息时出错, 消息: {msg}", e)
                # 使用默认值
                raw_messages.append({
                    "role": msg.role, 
                    "content": str(msg.content) if msg.content else ""
                })
        return raw_messages
    
    def _log_request_info(self, raw_messages: List[Dict]):
        """记录请求信息"""
        safe_log_info(logger, LogMessages.MESSAGE_RECEIVED.format(len(raw_messages)))
        
        # 记录原始消息的角色分布
        role_count = {}
        for msg in raw_messages:
            role = msg.get("role", "unknown")
            role_count[role] = role_count.get(role, 0) + 1
        safe_log_info(logger, LogMessages.ROLE_DISTRIBUTION.format("原始", role_count))
    
    def _build_k2think_payload(
        self, 
        request: ChatCompletionRequest, 
        processed_messages: List[Dict],
        actual_model_id: str = None
    ) -> Dict:
        """构建K2Think请求负载"""
        # 构建K2Think格式的请求体 - 支持多模态内容
        k2think_messages = []
        for msg in processed_messages:
            try:
                # 使用多模态内容转换函数
                content = self.response_processor.content_to_multimodal(msg.get("content", ""))
                k2think_messages.append({
                    "role": msg["role"], 
                    "content": content
                })
            except Exception as e:
                safe_log_error(logger, f"构建K2Think消息时出错, 消息: {msg}", e)
                # 使用安全的默认值
                fallback_content = str(msg.get("content", ""))
                k2think_messages.append({
                    "role": msg.get("role", "user"), 
                    "content": fallback_content
                })
        
        # 使用实际的模型ID
        model_id = actual_model_id or APIConstants.MODEL_ID
        
        return {
            "stream": request.stream,
            "model": model_id,
            "messages": k2think_messages,
            "params": {},
            "tool_servers": [],
            "features": {
                "image_generation": False,
                "code_interpreter": False,
                "web_search": False
            },
            "variables": self.response_processor.get_current_datetime_info(),
            "model_item": {
                "id": model_id,
                "object": ResponseConstants.MODEL_OBJECT,
                "owned_by": APIConstants.MODEL_OWNER,
                "root": APIConstants.MODEL_ROOT,
                "parent": None,
                "status": "active",
                "connection_type": "external",
                "name": model_id
            },
            "background_tasks": {
                "title_generation": True,
                "tags_generation": True
            },
            "chat_id": self.response_processor.generate_chat_id(),
            "id": self.response_processor.generate_session_id(),
            "session_id": self.response_processor.generate_session_id()
        }
    
    def _validate_json_serialization(self, k2think_payload: Dict):
        """验证JSON序列化"""
        try:
            # 测试JSON序列化
            json.dumps(k2think_payload, ensure_ascii=False)
            safe_log_info(logger, LogMessages.JSON_VALIDATION_SUCCESS)
        except Exception as e:
            safe_log_error(logger, LogMessages.JSON_VALIDATION_FAILED.format(e))
            # 尝试修复序列化问题
            try:
                k2think_payload = json.loads(json.dumps(k2think_payload, default=str, ensure_ascii=False))
                safe_log_info(logger, LogMessages.JSON_FIXED)
            except Exception as fix_error:
                safe_log_error(logger, "无法修复序列化问题", fix_error)
                raise SerializationError()
    
    def _build_request_headers(self, request: ChatCompletionRequest, k2think_payload: Dict, token: str) -> Dict[str, str]:
        """构建请求头"""
        return {
            HeaderConstants.ACCEPT: (
                HeaderConstants.EVENT_STREAM_JSON if request.stream 
                else HeaderConstants.APPLICATION_JSON
            ),
            HeaderConstants.CONTENT_TYPE: HeaderConstants.APPLICATION_JSON,
            HeaderConstants.AUTHORIZATION: f"{APIConstants.BEARER_PREFIX}{token}",
            HeaderConstants.ORIGIN: "https://www.k2think.ai",
            HeaderConstants.REFERER: "https://www.k2think.ai/c/" + k2think_payload["chat_id"],
            HeaderConstants.USER_AGENT: HeaderConstants.DEFAULT_USER_AGENT
        }
    
    async def _handle_stream_response(
        self, 
        k2think_payload: Dict, 
        headers: Dict[str, str],
        output_thinking: bool = True,
        original_model: str = None
    ) -> StreamingResponse:
        """处理流式响应"""
        return StreamingResponse(
            self.response_processor.process_stream_response(
                k2think_payload, headers, output_thinking, original_model
            ),
            media_type=HeaderConstants.TEXT_EVENT_STREAM,
            headers={
                HeaderConstants.CACHE_CONTROL: HeaderConstants.NO_CACHE,
                HeaderConstants.CONNECTION: HeaderConstants.KEEP_ALIVE,
                HeaderConstants.X_ACCEL_BUFFERING: HeaderConstants.NO_BUFFERING
            }
        )
    
    async def _handle_non_stream_response(
        self, 
        k2think_payload: Dict, 
        headers: Dict[str, str],
        output_thinking: bool = True,
        original_model: str = None
    ) -> JSONResponse:
        """处理非流式响应"""
        full_content, token_info = await self.response_processor.process_non_stream_response(
            k2think_payload, headers, output_thinking
        )
        
        openai_response = self.response_processor.create_completion_response(
            full_content, token_info, original_model
        )
        
        return JSONResponse(content=openai_response)
    
    async def _handle_stream_response_with_retry(
        self, 
        request: ChatCompletionRequest,
        k2think_payload: Dict,
        output_thinking: bool = True,
        enable_toolify: bool = False,
        max_retries: int = 3
    ) -> StreamingResponse:
        """处理流式响应（带重试机制）"""
        last_exception = None
        
        for attempt in range(max_retries):
            # 获取下一个可用token
            token = self.token_manager.get_next_token()
            if not token:
                # 根据是否启用自动更新提供不同的错误信息
                if Config.ENABLE_TOKEN_AUTO_UPDATE:
                    error_message = "Token池暂时为空，可能正在自动更新中。请稍后重试或检查自动更新服务状态。"
                    safe_log_warning(logger, "没有可用的token，可能正在自动更新中")
                else:
                    error_message = "所有token都已失效，请检查token配置或重新加载token文件。"
                    safe_log_error(logger, "没有可用的token")
                
                raise HTTPException(
                    status_code=APIConstants.HTTP_SERVICE_UNAVAILABLE,
                    detail={
                        "error": {
                            "message": error_message,
                            "type": ErrorMessages.API_ERROR
                        }
                    }
                )
            
            # 构建请求头
            headers = self._build_request_headers(request, k2think_payload, token)
            
            try:
                safe_log_info(logger, f"尝试流式请求 (第{attempt + 1}次)")
                
                # 创建流式生成器，内部处理token成功/失败标记
                async def stream_generator():
                    try:
                        async for chunk in self.response_processor.process_stream_response(
                            k2think_payload, headers, output_thinking, request.model, enable_toolify
                        ):
                            yield chunk
                        # 流式响应成功完成，标记token成功
                        self.token_manager.mark_token_success(token)
                    except Exception as e:
                        # 流式响应过程中出现错误，标记token失败
                        safe_log_warning(logger, f"🔍 流式响应异常被捕获，准备标记token失败: {str(e)}")
                        
                        # 标记token失败（这会触发自动刷新逻辑）
                        token_failed = self.token_manager.mark_token_failure(token, str(e))
                        
                        # 特别处理401错误
                        if "401" in str(e) or "unauthorized" in str(e).lower():
                            safe_log_warning(logger, f"🔒 流式响应中检测到401认证错误，token标记失败: {token_failed}")
                            safe_log_info(logger, f"🚨 已调用mark_token_failure，应该触发自动刷新")
                        else:
                            safe_log_warning(logger, f"流式响应中检测到其他错误: {str(e)}")
                        
                        # 注意：不重新抛出异常，避免"response already started"错误
                        # 错误信息已经通过response_processor发送给客户端
                
                return StreamingResponse(
                    stream_generator(),
                    media_type=HeaderConstants.TEXT_EVENT_STREAM,
                    headers={
                        HeaderConstants.CACHE_CONTROL: HeaderConstants.NO_CACHE,
                        HeaderConstants.CONNECTION: HeaderConstants.KEEP_ALIVE,
                        HeaderConstants.X_ACCEL_BUFFERING: HeaderConstants.NO_BUFFERING
                    }
                )
            except (UpstreamError, Exception) as e:
                # 这里只处理流式响应启动前的异常（主要是连接错误）
                # 401等上游服务错误现在在流式响应内部处理，不会到达这里
                last_exception = e
                safe_log_warning(logger, f"流式请求启动失败 (第{attempt + 1}次): {e}")
                
                # 标记token失败
                token_failed = self.token_manager.mark_token_failure(token, str(e))
                if token_failed:
                    safe_log_error(logger, f"Token已被标记为失效")
                
                # 如果是最后一次尝试，抛出异常
                if attempt == max_retries - 1:
                    break
                
                # 短暂延迟后重试
                await asyncio.sleep(0.5)
        
        # 所有重试都失败了
        safe_log_error(logger, "所有流式请求重试都失败了，最后错误", last_exception)
        raise HTTPException(
            status_code=APIConstants.HTTP_INTERNAL_ERROR,
            detail={
                "error": {
                    "message": f"流式请求失败: {str(last_exception)}",
                    "type": ErrorMessages.API_ERROR
                }
            }
        )
    
    async def _handle_non_stream_response_with_retry(
        self, 
        request: ChatCompletionRequest,
        k2think_payload: Dict,
        output_thinking: bool = True,
        enable_toolify: bool = False,
        max_retries: int = 3
    ) -> JSONResponse:
        """处理非流式响应（带重试机制）"""
        last_exception = None
        
        for attempt in range(max_retries):
            # 获取下一个可用token
            token = self.token_manager.get_next_token()
            if not token:
                # 根据是否启用自动更新提供不同的错误信息
                if Config.ENABLE_TOKEN_AUTO_UPDATE:
                    error_message = "Token池暂时为空，可能正在自动更新中。请稍后重试或检查自动更新服务状态。"
                    safe_log_warning(logger, "没有可用的token，可能正在自动更新中")
                else:
                    error_message = "所有token都已失效，请检查token配置或重新加载token文件。"
                    safe_log_error(logger, "没有可用的token")
                
                raise HTTPException(
                    status_code=APIConstants.HTTP_SERVICE_UNAVAILABLE,
                    detail={
                        "error": {
                            "message": error_message,
                            "type": ErrorMessages.API_ERROR
                        }
                    }
                )
            
            # 构建请求头
            headers = self._build_request_headers(request, k2think_payload, token)
            
            try:
                safe_log_info(logger, f"尝试非流式请求 (第{attempt + 1}次)")
                
                # 处理响应
                full_content, token_info = await self.response_processor.process_non_stream_response(
                    k2think_payload, headers, output_thinking
                )
                
                # 标记token成功
                self.token_manager.mark_token_success(token)
                
                # 检查是否有工具调用
                tool_response = None
                if enable_toolify:
                    from src.toolify_handler import parse_toolify_response
                    tool_response = parse_toolify_response(full_content, request.model)
                
                if tool_response:
                    # 返回包含tool_calls的响应
                    openai_response = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": ResponseConstants.CHAT_COMPLETION_OBJECT,
                        "created": int(time.time()),
                        "model": request.model,
                        "choices": [{
                            "index": 0,
                            "message": tool_response,
                            "finish_reason": "tool_calls"
                        }],
                        "usage": token_info or {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0
                        }
                    }
                else:
                    openai_response = self.response_processor.create_completion_response(
                        full_content, token_info, request.model
                    )
                
                return JSONResponse(content=openai_response)
                
            except (UpstreamError, Exception) as e:
                last_exception = e
                
                # 特别处理401错误
                if "401" in str(e) or "unauthorized" in str(e).lower():
                    safe_log_warning(logger, f"🔒 非流式请求遇到401认证错误 (第{attempt + 1}次): {e}")
                    
                    # 对于401错误，如果是第一次尝试，返回友好消息而不重试
                    if attempt == 0:
                        # 标记token失败以触发自动刷新
                        self.token_manager.mark_token_failure(token, str(e))
                        
                        # 返回友好的刷新提示消息
                        openai_response = self.response_processor.create_completion_response(
                            content="🔄 tokens强制刷新已启动，请稍后再试",
                            token_info={
                                "prompt_tokens": 0,
                                "completion_tokens": 10,
                                "total_tokens": 10
                            },
                            model=request.model
                        )
                        return JSONResponse(content=openai_response)
                else:
                    safe_log_warning(logger, f"非流式请求失败 (第{attempt + 1}次): {e}")
                
                # 标记token失败
                token_failed = self.token_manager.mark_token_failure(token, str(e))
                if token_failed:
                    safe_log_error(logger, f"Token已被标记为失效")
                
                # 如果是最后一次尝试，抛出异常
                if attempt == max_retries - 1:
                    break
                
                # 短暂延迟后重试
                await asyncio.sleep(0.5)
        
        # 所有重试都失败了
        safe_log_error(logger, "所有非流式请求重试都失败了，最后错误", last_exception)
        raise HTTPException(
            status_code=APIConstants.HTTP_INTERNAL_ERROR,
            detail={
                "error": {
                    "message": f"非流式请求失败: {str(last_exception)}",
                    "type": ErrorMessages.API_ERROR
                }
            }
        )