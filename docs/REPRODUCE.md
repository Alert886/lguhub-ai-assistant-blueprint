# 从零复现与扩展

## A. 默认路径：不联网、不配置 key

```bash
python -m assistant.pipeline --checkpoint build/template-checkpoint.jsonl
python -m assistant.server
python -m unittest discover -s tests -v
python -m scripts.evaluate
```

首条命令执行：读取合成 JSONL → 标准化 → 模板基线 → 追加断点 → SQLite/FTS。再次运行复用相同输入的断点。默认“模板”不是模型蒸馏，输出直接使用已有合成答案。

浏览器请求示例：

```json
{"question":"有哪些资料","page":"/course/DEMO1001","history":[]}
```

POST 到本地 `/api/assistant/query`，使用 `Content-Type: application/json`。响应包括 `answer / route / mode / sources / trace / elapsed_ms / synthetic`。展开界面中的实际执行轨迹可以看到课程号如何补足、候选得分和质量门判断。

## B. 可选真实向量路径

此路径需要用户自行准备模型和依赖；制作本仓库时未下载模型。推荐使用独立 Python 3.10–3.12 环境，按需安装：

```bash
python -m venv .venv
# 激活环境后：
python -m pip install -r requirements-vectors.txt
```

依赖版本取自原站记录：NumPy 2.2.6、FastEmbed 0.8.1、ONNX Runtime 1.23.2。它们不是本次在所有平台上验证的锁定环境；GPU 蒸馏依赖不包含在这里。

在可信环境中预置 FastEmbed 使用的 BGE-small-zh-v1.5 ONNX 快照，并设置 `CAMPUS_EMBED_MODEL_DIR` 为完整目录。须有 `model_optimized.onnx / tokenizer.json / config.json / tokenizer_config.json / special_tokens_map.json`。不要把权重提交到本仓库，也不要把目录指向原站内部数据。

PowerShell 示例：

```powershell
$env:CAMPUS_EMBED_MODEL_DIR = 'C:/models/bge-small-zh-v1.5'
$env:CAMPUS_EMBED_THREADS = '2'
python -m assistant.vectors build/knowledge.sqlite
python -m assistant.server --vectors
```

Linux/macOS 使用 `export CAMPUS_EMBED_MODEL_DIR=/path/to/model`。模型缺失时向量不会远程下载，在线检索继续词法路径；trace 的 `vector_status` 显示降级状态。构建向量时缺模型则报错，不能把未构建的向量当成已启用。

重新执行知识包构建会生成新 SQLite，因此须重新生成向量。替换向量模型后也要重建向量并重启服务，避免同维度但不同模型的向量被混用。当前提取模块不对模型版本自动做完整兼容校验。

## C. 可选模型兜底与离线蒸馏

配置只从进程环境读取。`.env.example` 只有空值；程序不自动读取 `.env`。在线服务与离线蒸馏可以分别在不同进程配置不同模型端点；GPU 模型应放在离线环境中。

必须设置：`DEMO_ENABLE_LLM=1`、`DEMO_LLM_BASE_URL`（兼容接口的 `/v1` 根地址）、`DEMO_LLM_MODEL`，以及服务需要时的 `DEMO_LLM_API_KEY`。支持 HTTPS；仅回环地址允许 HTTP。

不要将真实 key 写进源代码、示例文件、文档或终端命令参数。PowerShell 可用无回显输入为当前进程设置：

```powershell
$secret = Read-Host 'API key（不会显示）' -AsSecureString
$env:DEMO_LLM_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
# 其余地址和模型变量按自己的服务设置；准备好后才开启：
$env:DEMO_ENABLE_LLM = '1'
python -m assistant.server
```

停止后可用 `Remove-Item Env:DEMO_LLM_API_KEY` 清除当前 shell 的值。不要在截图、日志或提交中打印环境变量。浏览器界面没有 key 输入框，接口也不提供读取 key 的能力。

离线模型蒸馏命令：

```bash
python -m assistant.pipeline --llm --checkpoint build/model-checkpoint.jsonl
```

它会向你配置的服务发送**当前合成资料**，每个未完成记录一次调用。产物先校验再写断点；失败直接停止以便检查，不把失败响应覆盖到原知识包。默认模型生成参数是 temperature=0.2、蒸馏最多1200 tokens、在线回答最多800 tokens。温度不等于确定性保证；要复现真实模型结果需同时记录服务模型版本、输入哈希和产物。

## D. 真正接入其他站点时

先另建受控数据管道，在获得资料使用授权后，明确公开字段、来源许可与更新周期。不要通过删除 `synthetic` 检查直接把业务数据库导入公开演示仓库。

推荐实施顺序：数据契约 → 人工审核小样本 → 离线蒸馏与失败保留 → 版本化知识包 → 词法基线 → 可选向量与独立验证集 → 基于最终答案的质量门 → 模型兜底 → 登录/额度/权限集成 → 监控与回滚。

生产需补充身份鉴别、CSRF、访问速率与调用预算限制、业务事务语义、提示注入防护评估、输出来源核验、模型与知识包版本校验。原站权限语义不能由演示中的关键词隐私规则替代。本仓库没有部署公网服务。
