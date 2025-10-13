"""
K2Think API Proxy 工具调用示例
演示如何使用工具调用功能
"""
import json
from openai import OpenAI

# 配置客户端
client = OpenAI(
    base_url="http://localhost:8001/v1",
    api_key="sk-123456"
)

# 定义工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如：北京、上海、深圳"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位",
                        "default": "celsius"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "在互联网上搜索信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "执行数学计算",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如：2+2, 10*5, sqrt(16)"
                    }
                },
                "required": ["expression"]
            }
        }
    }
]

def example_basic_tool_call():
    """基础工具调用示例"""
    print("\n=== 基础工具调用示例 ===\n")
    
    response = client.chat.completions.create(
        model="MBZUAI-IFM/K2-Think",
        messages=[
            {"role": "user", "content": "北京今天天气怎么样？"}
        ],
        tools=tools,
        tool_choice="auto"
    )
    
    # 处理响应
    message = response.choices[0].message
    
    if message.tool_calls:
        print("模型请求调用工具：")
        for tool_call in message.tool_calls:
            print(f"\n工具名称: {tool_call.function.name}")
            print(f"工具参数: {tool_call.function.arguments}")
            
            # 模拟执行工具并返回结果
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            # 模拟工具执行结果
            if function_name == "get_weather":
                result = {
                    "city": function_args.get("city"),
                    "temperature": 22,
                    "condition": "晴天",
                    "humidity": 45,
                    "unit": function_args.get("unit", "celsius")
                }
            else:
                result = {"status": "success", "data": "模拟数据"}
            
            print(f"工具执行结果: {json.dumps(result, ensure_ascii=False)}")
    else:
        print("模型直接回答：")
        print(message.content)


def example_multi_turn_conversation():
    """多轮对话示例（包含工具调用）"""
    print("\n=== 多轮对话示例 ===\n")
    
    messages = [
        {"role": "user", "content": "查一下上海的天气，然后搜索关于上海的旅游景点"}
    ]
    
    response = client.chat.completions.create(
        model="MBZUAI-IFM/K2-Think",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
    
    message = response.choices[0].message
    
    if message.tool_calls:
        print("第一轮 - 模型请求调用工具：")
        messages.append(message)  # 添加助手的响应
        
        # 处理每个工具调用
        for tool_call in message.tool_calls:
            print(f"\n调用工具: {tool_call.function.name}")
            print(f"参数: {tool_call.function.arguments}")
            
            # 模拟工具执行并返回结果
            function_name = tool_call.function.name
            
            if function_name == "get_weather":
                result = '{"temperature": 25, "condition": "多云", "city": "上海"}'
            elif function_name == "search_web":
                result = '{"results": ["外滩", "东方明珠", "豫园", "南京路"]}'
            else:
                result = '{"status": "success"}'
            
            # 添加工具结果到消息历史
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })
        
        # 发送工具结果给模型，获取最终回答
        print("\n第二轮 - 发送工具结果给模型...")
        
        final_response = client.chat.completions.create(
            model="MBZUAI-IFM/K2-Think",
            messages=messages,
            tools=tools
        )
        
        print("\n模型的最终回答：")
        print(final_response.choices[0].message.content)


def example_forced_tool_call():
    """强制使用特定工具的示例"""
    print("\n=== 强制工具调用示例 ===\n")
    
    response = client.chat.completions.create(
        model="MBZUAI-IFM/K2-Think",
        messages=[
            {"role": "user", "content": "计算 123 * 456"}
        ],
        tools=tools,
        tool_choice={
            "type": "function",
            "function": {"name": "calculate"}
        }
    )
    
    message = response.choices[0].message
    
    if message.tool_calls:
        print("模型被强制使用工具：")
        for tool_call in message.tool_calls:
            print(f"工具: {tool_call.function.name}")
            print(f"参数: {tool_call.function.arguments}")


def example_stream_with_tools():
    """流式响应中的工具调用示例"""
    print("\n=== 流式工具调用示例 ===\n")
    
    stream = client.chat.completions.create(
        model="MBZUAI-IFM/K2-Think",
        messages=[
            {"role": "user", "content": "帮我搜索一下人工智能的最新发展"}
        ],
        tools=tools,
        stream=True
    )
    
    print("流式响应：")
    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
        
        # 检查是否有工具调用
        if hasattr(chunk.choices[0].delta, 'tool_calls') and chunk.choices[0].delta.tool_calls:
            print("\n检测到工具调用：")
            for tool_call in chunk.choices[0].delta.tool_calls:
                if hasattr(tool_call, 'function'):
                    print(f"\n工具: {tool_call.function.name if hasattr(tool_call.function, 'name') else '未知'}")
        
        # 检查结束原因
        if chunk.choices[0].finish_reason == "tool_calls":
            print("\n[流结束 - 需要工具调用]")
            break
        elif chunk.choices[0].finish_reason == "stop":
            print("\n[流结束]")
            break
    
    print()


def example_disable_tools():
    """禁用工具调用的示例"""
    print("\n=== 禁用工具调用示例 ===\n")
    
    response = client.chat.completions.create(
        model="MBZUAI-IFM/K2-Think",
        messages=[
            {"role": "user", "content": "北京今天天气怎么样？"}
        ],
        tools=tools,
        tool_choice="none"  # 禁用工具调用
    )
    
    print("模型直接回答（未使用工具）：")
    print(response.choices[0].message.content)


if __name__ == "__main__":
    print("=" * 60)
    print("K2Think API Proxy - 工具调用功能示例")
    print("=" * 60)
    
    try:
        # 运行示例
        example_basic_tool_call()
        example_forced_tool_call()
        example_stream_with_tools()
        example_disable_tools()
        example_multi_turn_conversation()
        
        print("\n" + "=" * 60)
        print("示例运行完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n错误: {e}")
        print("\n请确保：")
        print("1. K2Think API Proxy 服务正在运行（http://localhost:8001）")
        print("2. 环境变量 ENABLE_TOOLIFY=true")
        print("3. API密钥配置正确")

