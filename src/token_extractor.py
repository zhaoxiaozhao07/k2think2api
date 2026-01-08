# -*- coding: utf-8 -*-
"""
Token提取模块
负责从K2Think登录并提取token，内置到项目中使用
"""
import os
import json
import logging
import threading
import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()


class TokenExtractor:
    """Token提取器 - 负责登录K2Think并提取token"""
    
    def __init__(self, proxy_url: Optional[str] = None):
        """
        初始化Token提取器
        
        Args:
            proxy_url: 代理URL，如果为None则从环境变量读取
        """
        self.base_url = "https://www.k2think.ai"
        self.login_url = f"{self.base_url}/api/v1/auths/signin"
        
        # 从环境变量读取代理配置
        if proxy_url is None:
            proxy_url = os.getenv("PROXY_URL", "")
        
        self.proxies = {}
        if proxy_url:
            self.proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
            logger.info(f"Token提取器使用代理: {proxy_url}")
        else:
            logger.debug("Token提取器未配置代理，直接连接")
        
        # 基于浏览器的请求头
        self.headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/json',
            'Origin': 'https://www.k2think.ai',
            'Priority': 'u=1, i',
            'Referer': 'https://www.k2think.ai/auth?mode=signin',
            'Sec-Ch-Ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Microsoft Edge";v="140"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0'
        }
        
        self.lock = threading.Lock()

    def _extract_token_from_set_cookie(self, response: requests.Response) -> Optional[str]:
        """从响应的Set-Cookie头中提取token"""
        set_cookie_headers = response.headers.get_list('Set-Cookie') if hasattr(response.headers, 'get_list') else [response.headers.get('Set-Cookie')]
        
        # 处理多个Set-Cookie头
        if set_cookie_headers:
            for cookie_header in set_cookie_headers:
                if cookie_header and 'token=' in cookie_header:
                    # 使用正则提取token值
                    match = re.search(r'token=([^;]+)', cookie_header)
                    if match:
                        return match.group(1)
        
        return None

    def login_and_get_token(self, email: str, password: str, retry_count: int = 3) -> Optional[str]:
        """
        登录并获取token，带重试机制
        
        Args:
            email: 邮箱
            password: 密码
            retry_count: 重试次数
            
        Returns:
            成功返回token字符串，失败返回None
        """
        import time
        
        login_data = {
            "email": email,
            "password": password
        }
        
        for attempt in range(retry_count):
            try:
                session = requests.Session()
                session.headers.update(self.headers)
                
                response = session.post(
                    self.login_url,
                    json=login_data,
                    proxies=self.proxies if self.proxies else None,
                    timeout=30
                )
                
                if response.status_code == 200:
                    token = self._extract_token_from_set_cookie(response)
                    if token:
                        return token
                
            except Exception as e:
                logger.debug(f"登录尝试 {attempt + 1}/{retry_count} 失败: {e}")
                if attempt == retry_count - 1:
                    return None
                time.sleep(2)  # 重试间隔2秒
                continue
                
        return None

    def load_accounts_from_file(self, file_path: str) -> List[Dict[str, str]]:
        """
        从文件加载账户信息
        
        Args:
            file_path: 账户文件路径
            
        Returns:
            账户列表，每个账户包含 email 和 password
        """
        accounts = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        account_data = json.loads(line)
                        if 'email' in account_data and 'k2_password' in account_data:
                            accounts.append({
                                'email': account_data['email'],
                                'password': account_data['k2_password']
                            })
                    except json.JSONDecodeError:
                        continue
            
            logger.info(f"从 {file_path} 加载了 {len(accounts)} 个账户")
            return accounts
            
        except FileNotFoundError:
            logger.error(f"账户文件不存在: {file_path}")
            return []
        except Exception as e:
            logger.error(f"加载账户文件失败: {e}")
            return []

    def _process_single_account(self, account: Dict[str, str]) -> Optional[str]:
        """处理单个账户，返回token或None"""
        token = self.login_and_get_token(account['email'], account['password'])
        return token

    def extract_tokens_from_accounts(self, 
                                      accounts: List[Dict[str, str]], 
                                      max_workers: int = 4) -> List[str]:
        """
        从账户列表批量提取tokens
        
        Args:
            accounts: 账户列表
            max_workers: 并发工作线程数
            
        Returns:
            成功提取的token列表
        """
        if not accounts:
            logger.warning("没有账户需要处理")
            return []
        
        logger.info(f"开始处理 {len(accounts)} 个账户，{max_workers}线程并发...")
        
        tokens = []
        success_count = 0
        failed_count = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_account = {
                executor.submit(self._process_single_account, account): account 
                for account in accounts
            }
            
            # 处理结果
            for future in as_completed(future_to_account):
                account = future_to_account[future]
                try:
                    token = future.result()
                    if token:
                        with self.lock:
                            tokens.append(token)
                        success_count += 1
                        logger.debug(f"✓ 获取token成功: {account['email']}")
                    else:
                        failed_count += 1
                        logger.warning(f"✗ 获取token失败: {account['email']}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"✗ 处理账户异常 {account['email']}: {e}")
        
        logger.info(f"Token提取完成: 成功 {success_count}, 失败 {failed_count}")
        
        return tokens

    def extract_tokens_from_file(self, 
                                  accounts_file: str, 
                                  max_workers: int = 4) -> List[str]:
        """
        从账户文件提取tokens的便捷方法
        
        Args:
            accounts_file: 账户文件路径
            max_workers: 并发工作线程数
            
        Returns:
            成功提取的token列表
        """
        accounts = self.load_accounts_from_file(accounts_file)
        if not accounts:
            return []
        
        return self.extract_tokens_from_accounts(accounts, max_workers)
