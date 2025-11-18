"""
title: EnergyProxy
author: you
version: 0.1.0
description: A strict proxy tool that forwards raw user input to the backend energy API without any modification.
"""

import requests
import urllib.parse


class Tools:
    def __init__(self):
        # 禁用 llm 在 tool 返回内容中的引用标记
        self.citation = False

    def query_energy(self, message: str, __user__=None, __metadata__=None) -> dict:
        """
        严格原样将用户输入转发给能源查询 API，同时打印 __user__ 和 __metadata__ 内容。

        :param message: 用户原始输入文本
        :param __user__: OpenWebUI 自动传入的用户信息字典（可选）
        :param __metadata__: OpenWebUI 自动传入的上下文或元数据字典（可选）
        :return: 后端 reply 字段内容或错误信息
        """
        if not message:
            return "输入为空"

        # 打印 __user__ 和 __metadata__ 内容，查看有哪些字段可用
        print("当前 __user__ 信息:", __user__)
        print("当前 __metadata__ 信息:", __metadata__)

        # 优先使用 __user__ 中的 id，如果没有传入则用默认值
        user_id = None
        # if __user__:
        #     user_id = __user__.get("id")  # 文档示例通常用 id 字段作为唯一标识
        # if not user_id:
        #     user_id = "unknown_user"
        if __metadata__:
            user_id = __metadata__.get("chat_id")  # 文档示例通常用 id 字段作为唯一标识
        if not user_id:
            user_id = "unknown_chat"

        # URL 编码，保留中文符号
        encoded_msg = urllib.parse.quote(message, safe="")

        url = f"http://localhost:9001/chat?user_id={user_id}&message={encoded_msg}"

        try:
            resp = requests.get(url, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            # 对openwebui屏蔽返回细节
            return {"reply": data.get("reply") or "服务繁忙，请稍后再试"}
        except Exception as e:
            return f"服务异常，请联系管理员:{e}"
