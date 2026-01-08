"""
Token管理模块
负责管理K2Think的token池，实现轮询、负载均衡和失效标记
"""
import os
import json
import logging
import threading

from typing import List, Dict, Optional, Tuple, Callable
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 导入安全日志函数
try:
    from src.utils import safe_log_error, safe_log_info, safe_log_warning
except ImportError:
    # 如果导入失败，提供简单的替代函数
    def safe_log_error(logger, msg, exc=None):
        try:
            if exc:
                logger.error(f"{msg}: {str(exc)}")
            else:
                logger.error(msg)
        except:
            print(f"Log error: {msg}")
    
    def safe_log_info(logger, msg):
        try:
            logger.info(msg)
        except:
            print(f"Log info: {msg}")
    
    def safe_log_warning(logger, msg):
        try:
            logger.warning(msg)
        except:
            print(f"Log warning: {msg}")

class TokenManager:
    """Token管理器 - 支持轮询、负载均衡和失效标记（纯内存模式）"""
    
    def __init__(self, max_failures: int = 3, allow_empty: bool = True):
        """
        初始化token管理器
        
        Args:
            max_failures: 最大失败次数，超过后标记为失效
            allow_empty: 是否允许空的token（用于启动时等待刷新）
        """
        self.max_failures = max_failures
        self.tokens: List[Dict] = []
        self.current_index = 0
        self.lock = threading.Lock()
        self.allow_empty = allow_empty
        
        # 连续失效检测
        self.consecutive_failures = 0
        self.consecutive_failure_threshold = 2  # 连续失效阈值
        self.force_refresh_callback: Optional[Callable] = None  # 强制刷新回调函数
        
        # 上游服务连续报错检测
        self.consecutive_upstream_errors = 0
        self.upstream_error_threshold = 2  # 上游服务连续报错阈值
        self.last_upstream_error_time = None
        
        # 内存刷新回调（用于获取新tokens）
        self.memory_refresh_callback: Optional[Callable[[], List[str]]] = None
        
        safe_log_info(logger, "TokenManager初始化完成（纯内存模式）")
    
    def _set_tokens_internal(self, token_strings: List[str]) -> None:
        """
        内部方法：从token字符串列表设置tokens
        
        Args:
            token_strings: token字符串列表
        """
        self.tokens = []
        for idx, token in enumerate(token_strings):
            self.tokens.append({
                'token': token,
                'failures': 0,
                'is_active': True,
                'last_used': None,
                'last_failure': None,
                'index': idx
            })
        self.current_index = 0
    
    def set_tokens(self, token_strings: List[str]) -> None:
        """
        直接设置内存中的tokens（线程安全）
        
        Args:
            token_strings: token字符串列表
        """
        with self.lock:
            old_count = len(self.tokens)
            self._set_tokens_internal(token_strings)
            safe_log_info(logger, f"内存中设置了 {len(self.tokens)} 个token (原有: {old_count})")
            
            # 重置连续失败计数
            self.consecutive_failures = 0
            self.consecutive_upstream_errors = 0
    
    def get_tokens_list(self) -> List[str]:
        """
        获取当前所有tokens的字符串列表
        
        Returns:
            token字符串列表
        """
        with self.lock:
            return [t['token'] for t in self.tokens]
    
    def set_memory_refresh_callback(self, callback: Callable[[], List[str]]) -> None:
        """
        设置内存刷新回调函数
        
        Args:
            callback: 当需要刷新时调用的函数，应返回token字符串列表
        """
        self.memory_refresh_callback = callback
        safe_log_info(logger, "已设置内存刷新回调函数")

    def get_next_token(self) -> Optional[str]:
        """
        获取下一个可用的token（轮询算法）
        
        Returns:
            可用的token字符串，如果没有可用token则返回None
        """
        with self.lock:
            active_tokens = [t for t in self.tokens if t['is_active']]
            
            if not active_tokens:
                if self.allow_empty:
                    safe_log_warning(logger, "没有可用的token，可能正在等待刷新")
                else:
                    safe_log_warning(logger, "没有可用的token")
                return None
            
            # 轮询算法：从当前索引开始寻找下一个可用token
            attempts = 0
            while attempts < len(self.tokens):
                token_info = self.tokens[self.current_index]
                
                if token_info['is_active']:
                    # 更新使用时间
                    token_info['last_used'] = datetime.now()
                    token = token_info['token']
                    
                    # 移动到下一个索引
                    self.current_index = (self.current_index + 1) % len(self.tokens)
                    
                    logger.debug(f"分配token (索引: {token_info['index']}, 失败次数: {token_info['failures']})")
                    return token
                
                # 移动到下一个token
                self.current_index = (self.current_index + 1) % len(self.tokens)
                attempts += 1
            
            safe_log_warning(logger, "所有token都已失效")
            return None
    
    def mark_token_failure(self, token: str, error_message: str = "") -> bool:
        """
        标记token使用失败
        
        Args:
            token: 失败的token
            error_message: 错误信息
            
        Returns:
            如果token被标记为失效返回True，否则返回False
        """
        with self.lock:
            for token_info in self.tokens:
                if token_info['token'] == token:
                    token_info['failures'] += 1
                    token_info['last_failure'] = datetime.now()
                    
                    # 检查是否是上游服务错误（401等认证错误）
                    is_upstream_error = self._is_upstream_error(error_message)
                    
                    if is_upstream_error:
                        # 增加上游服务连续报错计数
                        self.consecutive_upstream_errors += 1
                        self.last_upstream_error_time = datetime.now()
                        
                        safe_log_warning(logger, f"🔒 上游服务认证错误 (索引: {token_info['index']}, "
                                     f"失败次数: {token_info['failures']}/{self.max_failures}, "
                                     f"连续上游错误: {self.consecutive_upstream_errors}): {error_message}")
                        
                        # 401错误立即触发强制刷新
                        if "401" in error_message and self.force_refresh_callback:
                            safe_log_warning(logger, f"🚨 检测到401认证错误，立即触发token强制刷新")
                            self._trigger_force_refresh("401认证失败")
                            self.consecutive_upstream_errors = 0
                        else:
                            self._check_consecutive_upstream_errors()
                    else:
                        # 增加连续失效计数
                        self.consecutive_failures += 1
                        
                        safe_log_warning(logger, f"Token失败 (索引: {token_info['index']}, "
                                     f"失败次数: {token_info['failures']}/{self.max_failures}, "
                                     f"连续失效: {self.consecutive_failures}): {error_message}")
                        
                        self._check_consecutive_failures()
                    
                    # 检查是否达到最大失败次数
                    if token_info['failures'] >= self.max_failures:
                        token_info['is_active'] = False
                        safe_log_error(logger, f"Token已失效 (索引: {token_info['index']}, "
                                   f"失败次数: {token_info['failures']})")
                        return True
                    
                    return False
            
            safe_log_warning(logger, "未找到匹配的token进行失败标记")
            return False
    
    def mark_token_success(self, token: str) -> None:
        """
        标记token使用成功（重置失败计数）
        
        Args:
            token: 成功的token
        """
        with self.lock:
            for token_info in self.tokens:
                if token_info['token'] == token:
                    if token_info['failures'] > 0:
                        safe_log_info(logger, f"Token恢复 (索引: {token_info['index']}, "
                                  f"重置失败次数: {token_info['failures']} -> 0)")
                        token_info['failures'] = 0
                    
                    # 成功请求重置上游服务错误计数
                    if self.consecutive_upstream_errors > 0:
                        safe_log_info(logger, f"重置上游服务连续错误计数: {self.consecutive_upstream_errors} -> 0")
                        self.consecutive_upstream_errors = 0
                    
                    return
    
    def get_token_stats(self) -> Dict:
        """
        获取token池统计信息
        
        Returns:
            包含统计信息的字典
        """
        with self.lock:
            total = len(self.tokens)
            active = sum(1 for t in self.tokens if t['is_active'])
            inactive = total - active
            
            failure_distribution = {}
            for token_info in self.tokens:
                failures = token_info['failures']
                failure_distribution[failures] = failure_distribution.get(failures, 0) + 1
            
            return {
                'total_tokens': total,
                'active_tokens': active,
                'inactive_tokens': inactive,
                'current_index': self.current_index,
                'failure_distribution': failure_distribution,
                'max_failures': self.max_failures,
                'consecutive_failures': self.consecutive_failures,
                'consecutive_failure_threshold': self.consecutive_failure_threshold,
                'consecutive_upstream_errors': self.consecutive_upstream_errors,
                'upstream_error_threshold': self.upstream_error_threshold
            }
    
    def reset_token(self, token_index: int) -> bool:
        """
        重置指定索引的token（清除失败计数，重新激活）
        
        Args:
            token_index: token索引
            
        Returns:
            重置成功返回True，否则返回False
        """
        with self.lock:
            if 0 <= token_index < len(self.tokens):
                token_info = self.tokens[token_index]
                old_failures = token_info['failures']
                old_active = token_info['is_active']
                
                token_info['failures'] = 0
                token_info['is_active'] = True
                token_info['last_failure'] = None
                
                safe_log_info(logger, f"Token重置 (索引: {token_index}, "
                           f"失败次数: {old_failures} -> 0, "
                           f"状态: {old_active} -> True)")
                return True
            
            safe_log_warning(logger, f"无效的token索引: {token_index}")
            return False
    
    def reset_all_tokens(self) -> None:
        """重置所有token（清除所有失败计数，重新激活所有token）"""
        with self.lock:
            reset_count = 0
            for token_info in self.tokens:
                if token_info['failures'] > 0 or not token_info['is_active']:
                    token_info['failures'] = 0
                    token_info['is_active'] = True
                    token_info['last_failure'] = None
                    reset_count += 1
            
            safe_log_info(logger, f"重置了 {reset_count} 个token，当前活跃token数: {len(self.tokens)}")
    
    def reload_tokens(self) -> None:
        """重新加载tokens（使用内存刷新回调）"""
        safe_log_info(logger, "重新加载tokens...")
        old_count = len(self.tokens)
        
        if self.memory_refresh_callback:
            try:
                new_tokens = self.memory_refresh_callback()
                if new_tokens:
                    self.set_tokens(new_tokens)
                    safe_log_info(logger, f"通过刷新回调重新加载完成: {old_count} -> {len(self.tokens)}")
                    return
            except Exception as e:
                safe_log_error(logger, "刷新回调执行失败", e)
        else:
            safe_log_warning(logger, "未设置刷新回调函数")
    
    def get_token_by_index(self, index: int) -> Optional[Dict]:
        """根据索引获取token信息"""
        with self.lock:
            if 0 <= index < len(self.tokens):
                return self.tokens[index].copy()
            return None
    
    def set_force_refresh_callback(self, callback: Callable) -> None:
        """
        设置强制刷新回调函数
        
        Args:
            callback: 当需要强制刷新时调用的函数
        """
        self.force_refresh_callback = callback
        safe_log_info(logger, "已设置强制刷新回调函数")
    
    def _is_upstream_error(self, error_message: str) -> bool:
        """判断是否为上游服务错误"""
        import re
        
        upstream_error_indicators = [
            "上游服务错误: 401",
            "上游服务错误: 403", 
            "401",
            "403",
            "unauthorized", 
            "forbidden",
            "invalid token",
            "authentication failed",
            "token expired",
            "authentication error",
            "invalid_request_error",
            "authentication_error"
        ]
        
        error_lower = error_message.lower()
        is_upstream = any(indicator.lower() in error_lower for indicator in upstream_error_indicators)
        
        status_code_pattern = r'(?:上游服务错误|http状态错误|状态码):\s*(?:40[13])'
        if re.search(status_code_pattern, error_lower):
            is_upstream = True
        
        if is_upstream:
            safe_log_info(logger, f"检测到上游服务认证错误: {error_message}")
        
        return is_upstream
    
    def _check_consecutive_upstream_errors(self):
        """检查上游服务连续报错情况，触发强制刷新机制"""
        if self.consecutive_upstream_errors >= self.upstream_error_threshold:
            safe_log_warning(logger, f"🚨 检测到连续{self.consecutive_upstream_errors}个上游服务认证错误，触发自动刷新token池")
            self.consecutive_upstream_errors = 0
            
            if self.force_refresh_callback:
                self._trigger_force_refresh("上游服务连续认证失败 (401/403)")
            else:
                safe_log_warning(logger, "⚠️ 未设置强制刷新回调函数，无法自动刷新token池")
    
    def _check_consecutive_failures(self):
        """检查连续失效情况，触发强制刷新机制"""
        if len(self.tokens) <= 2:
            logger.debug(f"Token池数量({len(self.tokens)})不足，跳过连续失效检查")
            return
        
        if self.consecutive_failures >= self.consecutive_failure_threshold:
            safe_log_warning(logger, f"检测到连续{self.consecutive_failures}个token失效，触发强制刷新机制")
            
            if self.force_refresh_callback:
                self._trigger_force_refresh("连续token失效")
            else:
                safe_log_warning(logger, "未设置强制刷新回调函数，无法自动刷新token池")
    
    def _trigger_force_refresh(self, reason: str):
        """触发强制刷新"""
        try:
            import threading
            
            def run_callback():
                try:
                    if self.force_refresh_callback:
                        self.force_refresh_callback()
                    safe_log_info(logger, f"🔄 强制刷新已触发 - 原因: {reason}")
                except Exception as e:
                    safe_log_error(logger, "执行强制刷新回调失败", e)
            
            # 在新线程中执行，避免阻塞当前操作
            refresh_thread = threading.Thread(target=run_callback, daemon=True)
            refresh_thread.start()
            
        except Exception as e:
            safe_log_error(logger, "启动强制刷新线程失败", e)
    
    def get_consecutive_failures(self) -> int:
        """获取当前连续失效次数"""
        return self.consecutive_failures
    
    def get_consecutive_upstream_errors(self) -> int:
        """获取当前上游服务连续错误次数"""
        return self.consecutive_upstream_errors
    
    def reset_consecutive_failures(self):
        """重置连续失效计数"""
        with self.lock:
            old_count = self.consecutive_failures
            old_upstream_count = self.consecutive_upstream_errors
            
            self.consecutive_failures = 0
            self.consecutive_upstream_errors = 0
            
            if old_count > 0:
                safe_log_info(logger, f"手动重置连续失效计数: {old_count} -> 0")
            if old_upstream_count > 0:
                safe_log_info(logger, f"手动重置上游服务连续错误计数: {old_upstream_count} -> 0")
