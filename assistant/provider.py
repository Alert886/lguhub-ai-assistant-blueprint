"""Optional OpenAI-compatible client. No network calls unless explicitly enabled."""
import json
import os
import urllib.request
from urllib.parse import urlparse


def complete(messages, *, purpose="answer"):
    if os.getenv("DEMO_ENABLE_LLM") != "1":
        raise RuntimeError("模型调用未启用")
    base = os.environ["DEMO_LLM_BASE_URL"].rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("模型地址必须使用 HTTPS，本地服务除外")
    body = {"model": os.environ["DEMO_LLM_MODEL"], "messages": messages,
            "temperature": 0.2, "max_tokens": 1200 if purpose == "distill" else 800}
    req = urllib.request.Request(base + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.getenv("DEMO_LLM_API_KEY", "")})
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    answer = result["choices"][0]["message"]["content"]
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("模型返回空内容")
    return answer.strip()
