"""
K2Think API 代理服务 - 重构版本
提供OpenAI兼容的API接口，代理到K2Think服务
"""
import os
import sys
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

# 确保使用UTF-8编码
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONLEGACYWINDOWSSTDIO', '0')

# 强制设置UTF-8编码
import locale
try:
    locale.setlocale(locale.LC_ALL, 'C.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        pass  # 如果设置失败，继续使用默认设置

# 重新配置标准输入输出流
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')

from src.config import Config
from src.constants import APIConstants
from src.exceptions import K2ThinkProxyError
from src.models import ChatCompletionRequest
from src.api_handler import APIHandler

# 初始化配置
try:
    Config.validate()
    Config.setup_logging()
except Exception as e:
    print(f"配置错误: {e}")
    exit(1)

logger = logging.getLogger(__name__)

# 全局HTTP客户端管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("K2Think API Proxy 启动中...")
    
    # 启动时初始化tokens（从accounts.txt获取最新tokens）
    if Config.ENABLE_TOKEN_AUTO_UPDATE:
        logger.info("🚀 正在从账户获取最新tokens...")
        if Config.initialize_tokens():
            logger.info("✅ Tokens初始化成功")
            
            # 启动定期更新服务
            token_updater = Config.get_token_updater()
            if token_updater.start():
                logger.info(f"✅ Token自动更新服务已启动 - 更新间隔: {Config.TOKEN_UPDATE_INTERVAL}秒")
            else:
                logger.warning("Token自动更新服务启动失败，但初始tokens已就绪")
        else:
            logger.error("❌ Token初始化失败，服务可能无法正常工作")
    else:
        logger.info("Token自动更新服务未启用，使用文件中的tokens")
    
    yield
    
    # 关闭token更新服务
    if Config.ENABLE_TOKEN_AUTO_UPDATE and Config._token_updater:
        Config._token_updater.stop()
        logger.info("Token自动更新服务已停止")
    
    logger.info("K2Think API Proxy 关闭中...")


# 创建FastAPI应用
app = FastAPI(
    title="K2Think API Proxy", 
    description="OpenAI兼容的K2Think API代理服务",
    version="2.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化API处理器
api_handler = APIHandler(Config)

@app.get("/")
async def homepage():
    """首页 - 返回服务状态"""
    return JSONResponse(content={
        "status": "success",
        "message": "K2Think API Proxy is running",
        "service": "K2Think API Gateway", 
        "model": APIConstants.MODEL_ID,
        "version": "2.2.0",
        "features": [
            "Token轮询和负载均衡",
            "自动失效检测和重试",
            "Token池管理",
            "启动即刷新（内存优先）",
            "OpenAI Function Calling 工具调用"
        ],
        "endpoints": {
            "chat": "/v1/chat/completions",
            "models": "/v1/models",
            "health": "/health",
            "admin": {
                "token_stats": "/admin/tokens/stats",
                "reset_token": "/admin/tokens/reset/{token_index}",
                "reset_all": "/admin/tokens/reset-all", 
                "reload_tokens": "/admin/tokens/reload",
                "consecutive_failures": "/admin/tokens/consecutive-failures",
                "reset_consecutive": "/admin/tokens/reset-consecutive",
                "updater_status": "/admin/tokens/updater/status",
                "force_update": "/admin/tokens/updater/force-update"
            }
        }
    })

@app.get("/health")
async def health_check():
    """健康检查"""
    token_manager = Config.get_token_manager()
    token_stats = token_manager.get_token_stats()
    
    return JSONResponse(content={
        "status": "healthy",
        "timestamp": int(time.time()),
        "config": {
            "debug_logging": Config.DEBUG_LOGGING,
            "toolify_enabled": Config.ENABLE_TOOLIFY,
            "note": "思考内容输出现在通过模型名控制"
        },
        "tokens": {
            "total": token_stats["total_tokens"],
            "active": token_stats["active_tokens"],
            "inactive": token_stats["inactive_tokens"],
            "consecutive_failures": token_manager.get_consecutive_failures(),
            "auto_update_enabled": Config.ENABLE_TOKEN_AUTO_UPDATE
        }
    })

@app.get("/favicon.ico")
async def favicon():
    """返回favicon"""
    return Response(content="", media_type="image/x-icon")

@app.get("/v1/models")
async def get_models():
    """获取模型列表"""
    return await api_handler.get_models()

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, auth_request: Request):
    """处理聊天补全请求"""
    return await api_handler.chat_completions(request, auth_request)

@app.get("/admin/tokens/stats")
async def get_token_stats():
    """获取token池统计信息"""
    token_manager = Config.get_token_manager()
    stats = token_manager.get_token_stats()
    # 添加连续失效信息
    stats["consecutive_failures"] = token_manager.get_consecutive_failures()
    stats["consecutive_failure_threshold"] = token_manager.consecutive_failure_threshold
    # 添加上游服务错误信息
    stats["consecutive_upstream_errors"] = token_manager.get_consecutive_upstream_errors()
    stats["upstream_error_threshold"] = token_manager.upstream_error_threshold
    return JSONResponse(content={
        "status": "success",
        "data": stats
    })

@app.post("/admin/tokens/reset/{token_index}")
async def reset_token(token_index: int):
    """重置指定索引的token"""
    token_manager = Config.get_token_manager()
    success = token_manager.reset_token(token_index)
    if success:
        return JSONResponse(content={
            "status": "success",
            "message": f"Token {token_index} 已重置"
        })
    else:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": f"无效的token索引: {token_index}"
            }
        )

@app.post("/admin/tokens/reset-all")
async def reset_all_tokens():
    """重置所有token"""
    token_manager = Config.get_token_manager()
    token_manager.reset_all_tokens()
    return JSONResponse(content={
        "status": "success",
        "message": "所有token已重置"
    })

@app.post("/admin/tokens/reload")
async def reload_tokens():
    """重新加载token文件"""
    try:
        Config.reload_tokens()
        token_manager = Config.get_token_manager()
        stats = token_manager.get_token_stats()
        return JSONResponse(content={
            "status": "success",
            "message": "Token文件已重新加载",
            "data": stats
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"重新加载失败: {str(e)}"
            }
        )

@app.get("/admin/tokens/consecutive-failures")
async def get_consecutive_failures():
    """获取连续失效信息"""
    token_manager = Config.get_token_manager()
    return JSONResponse(content={
        "status": "success",
        "data": {
            "consecutive_failures": token_manager.get_consecutive_failures(),
            "threshold": token_manager.consecutive_failure_threshold,
            "consecutive_upstream_errors": token_manager.get_consecutive_upstream_errors(),
            "upstream_error_threshold": token_manager.upstream_error_threshold,
            "last_upstream_error_time": token_manager.last_upstream_error_time.isoformat() if token_manager.last_upstream_error_time else None,
            "token_pool_size": len(token_manager.tokens),
            "auto_refresh_enabled": Config.ENABLE_TOKEN_AUTO_UPDATE and len(token_manager.tokens) > 2,
            "last_check": "实时检测"
        }
    })

@app.post("/admin/tokens/reset-consecutive")
async def reset_consecutive_failures():
    """重置连续失效计数"""
    token_manager = Config.get_token_manager()
    old_count = token_manager.get_consecutive_failures()
    token_manager.reset_consecutive_failures()
    return JSONResponse(content={
        "status": "success",
        "message": f"连续失效计数已重置: {old_count} -> 0",
        "data": {
            "previous_count": old_count,
            "current_count": 0
        }
    })

@app.get("/admin/tokens/updater/status")
async def get_updater_status():
    """获取token更新器状态"""
    if not Config.ENABLE_TOKEN_AUTO_UPDATE:
        return JSONResponse(content={
            "status": "disabled",
            "message": "Token自动更新未启用"
        })
    
    token_updater = Config.get_token_updater()
    status = token_updater.get_status()
    return JSONResponse(content={
        "status": "success",
        "data": status
    })

@app.post("/admin/tokens/updater/force-update")
async def force_update_tokens():
    """强制更新tokens"""
    if not Config.ENABLE_TOKEN_AUTO_UPDATE:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Token自动更新未启用"
            }
        )
    
    token_updater = Config.get_token_updater()
    success = await token_updater.force_update_async()
    
    if success:
        # 更新成功后重新加载token管理器
        Config.reload_tokens()
        token_manager = Config.get_token_manager()
        stats = token_manager.get_token_stats()
        
        return JSONResponse(content={
            "status": "success",
            "message": "Token强制更新成功",
            "data": stats
        })
    else:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Token强制更新失败"
            }
        )

@app.exception_handler(K2ThinkProxyError)
async def proxy_exception_handler(request: Request, exc: K2ThinkProxyError):
    """处理自定义代理异常"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "type": exc.error_type
            }
        }
    )

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """处理404错误"""
    return JSONResponse(
        status_code=404,
        content={"error": "Not Found"}
    )

if __name__ == "__main__":
    import uvicorn
    
    # 配置日志级别
    log_level = "debug" if Config.DEBUG_LOGGING else "info"
    
    logger.info(f"启动服务器: {Config.HOST}:{Config.PORT}")
    logger.info("思考内容输出: 通过模型名控制 (MBZUAI-IFM/K2-Think vs MBZUAI-IFM/K2-Think-nothink)")
    
    uvicorn.run(
        app, 
        host=Config.HOST, 
        port=Config.PORT, 
        access_log=Config.ENABLE_ACCESS_LOG,
        log_level=log_level
    )