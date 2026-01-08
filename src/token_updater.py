# -*- coding: utf-8 -*-
"""
Token更新服务模块
定期使用内置TokenExtractor来更新token池（纯内存模式）
"""
import os
import time
import logging
import threading
from typing import Optional, List
from datetime import datetime, timedelta
from src.utils import safe_log_error, safe_log_info, safe_log_warning
from src.token_extractor import TokenExtractor

logger = logging.getLogger(__name__)


class TokenUpdater:
    """Token更新服务 - 定期更新token池（纯内存模式）"""
    
    def __init__(self, 
                 update_interval: int = 86400,  # 默认24小时更新一次
                 accounts_file: str = "accounts.txt",
                 max_workers: int = 4):
        """
        初始化Token更新器
        
        Args:
            update_interval: 更新间隔（秒）
            accounts_file: 账户文件路径
            max_workers: 并发获取token的线程数
        """
        self.update_interval = update_interval
        self.accounts_file = accounts_file
        self.max_workers = max_workers
        
        self.is_running = False
        self.update_thread: Optional[threading.Thread] = None
        self.last_update: Optional[datetime] = None
        self.update_count = 0
        self.error_count = 0
        self.is_updating = False
        self.last_error: Optional[str] = None
        
        # 内置的Token提取器
        self.token_extractor = TokenExtractor()
        
        # Token管理器引用（稍后设置）
        self.token_manager = None
        
        # 最近获取的tokens缓存
        self._cached_tokens: List[str] = []
        
        safe_log_info(logger, f"Token更新器初始化完成 - 更新间隔: {update_interval}秒, 并发线程: {max_workers}")
    
    def set_token_manager(self, token_manager) -> None:
        """
        设置Token管理器引用
        
        Args:
            token_manager: TokenManager实例
        """
        self.token_manager = token_manager
        safe_log_info(logger, "Token更新器已关联Token管理器")
    
    def _check_accounts_file_exist(self) -> bool:
        """检查账户文件是否存在"""
        if not os.path.exists(self.accounts_file):
            safe_log_error(logger, f"账户文件不存在: {self.accounts_file}")
            return False
        return True
    
    def _run_token_update(self) -> bool:
        """
        运行token更新（纯内存模式）
        
        Returns:
            更新成功返回True，否则返回False
        """
        if self.is_updating:
            safe_log_warning(logger, "Token更新已在进行中，跳过此次更新")
            return False
            
        self.is_updating = True
        self.last_error = None
        
        try:
            safe_log_info(logger, "开始更新token池...")
            
            # 使用内置的TokenExtractor获取tokens
            tokens = self.token_extractor.extract_tokens_from_file(
                self.accounts_file, 
                self.max_workers
            )
            
            if tokens:
                # 缓存获取的tokens
                self._cached_tokens = tokens.copy()
                
                # 直接更新TokenManager的内存
                if self.token_manager:
                    self.token_manager.set_tokens(tokens)
                    safe_log_info(logger, f"Token更新成功，内存中设置了 {len(tokens)} 个token")
                else:
                    safe_log_warning(logger, "TokenManager未设置，tokens仅保存在缓存中")
                
                self.update_count += 1
                self.last_update = datetime.now()
                return True
            else:
                error_msg = "Token更新失败 - 未能获取任何有效token"
                safe_log_error(logger, error_msg)
                self.last_error = error_msg
                self.error_count += 1
                return False
                
        except Exception as e:
            error_msg = f"Token更新异常: {e}"
            safe_log_error(logger, error_msg, e)
            self.last_error = error_msg
            self.error_count += 1
            return False
        finally:
            self.is_updating = False
    
    def get_cached_tokens(self) -> List[str]:
        """
        获取缓存的tokens
        
        Returns:
            缓存的token列表
        """
        return self._cached_tokens.copy()
    
    def refresh_tokens(self) -> List[str]:
        """
        刷新并返回tokens
        用于TokenManager的内存刷新回调
        
        Returns:
            新获取的token列表
        """
        if not self._check_accounts_file_exist():
            return []
        
        tokens = self.token_extractor.extract_tokens_from_file(
            self.accounts_file,
            self.max_workers
        )
        
        if tokens:
            self._cached_tokens = tokens.copy()
            
        return tokens

    def _update_loop(self):
        """更新循环"""
        safe_log_info(logger, "Token更新服务启动")
        
        while self.is_running:
            try:
                time.sleep(self.update_interval)
                
                if not self.is_running:
                    break
                
                if self._check_accounts_file_exist():
                    self._run_token_update()
                else:
                    safe_log_warning(logger, "跳过此次更新 - 账户文件不存在")
                    
            except Exception as e:
                safe_log_error(logger, "更新循环异常", e)
                time.sleep(60)  # 异常时等待1分钟再继续
    
    def start(self) -> bool:
        """启动token更新服务"""
        if self.is_running:
            safe_log_warning(logger, "Token更新服务已在运行")
            return False
        
        if not self._check_accounts_file_exist():
            safe_log_error(logger, "启动失败 - 账户文件不存在")
            return False
        
        self.is_running = True
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()
        
        safe_log_info(logger, "Token更新服务已启动")
        return True
    
    def stop(self):
        """停止token更新服务"""
        if not self.is_running:
            safe_log_warning(logger, "Token更新服务未在运行")
            return
        
        self.is_running = False
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=5)
        
        safe_log_info(logger, "Token更新服务已停止")
    
    def force_update(self) -> bool:
        """强制立即更新token"""
        if not self._check_accounts_file_exist():
            safe_log_error(logger, "强制更新失败 - 账户文件不存在")
            return False
        
        safe_log_info(logger, "执行强制token更新")
        return self._run_token_update()
    
    async def force_update_async(self) -> bool:
        """异步强制立即更新token"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.force_update)
    
    def initial_refresh(self) -> bool:
        """
        初始刷新 - 启动时获取tokens
        
        Returns:
            成功返回True，否则返回False
        """
        if not self._check_accounts_file_exist():
            safe_log_error(logger, "初始刷新失败 - 账户文件不存在")
            return False
        
        safe_log_info(logger, "执行初始token刷新...")
        return self._run_token_update()
    
    def get_status(self) -> dict:
        """获取更新服务状态"""
        return {
            "is_running": self.is_running,
            "is_updating": self.is_updating,
            "update_interval": self.update_interval,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "update_count": self.update_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "cached_tokens_count": len(self._cached_tokens),
            "next_update": (
                (self.last_update + timedelta(seconds=self.update_interval)).isoformat()
                if self.last_update else None
            ),
            "accounts_file_exists": os.path.exists(self.accounts_file),
            "mode": "纯内存模式"
        }