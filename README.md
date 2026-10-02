# Solidus

固相线。温度低于这条线，混合物才全部变成固体。这个系统用同一条边界：Telegram 里还没定下来的对话是液相；人看着账本点头之后，才固化成 skill 或脚本。

服务器只从 Telegram 读命令。测试客户端也只向同一个聊天发命令，不直连服务器。成不成功由人回复 `1`、`2` 或 `3`，没有自动分数，退出码也不代表测试结论。

## 安装

需要 Python 3.11 或以上。设计目标是 3.12；代码没有用 3.12 专有语法。

```powershell
py -3.11 -m pip install uv
uv sync --extra dev
Copy-Item .env.example .env
```

要填的 token、聊天 id、用户会话和模型地址都在 [docs/配置.md](docs/配置.md)。

## 走一遍教学例子

开三个终端，都在仓库根目录。

```powershell
uv run solidus practice
```

浏览器打开 http://127.0.0.1:8765 ，可以自己点注册、登录和表单。页面不宣布结果。

```powershell
uv run solidus server
```

在 Telegram 里给机器人发：

```text
/run practice
```

之后按卡片回复 `1`、`2` 或 `3`。机械命令是：

```text
注册 tester 测试员
登录
填表 桥 2 多伦多 true 只要名字
```

提交结果、是否允许接上 Chrome、JSON 能不能用，这三处必须由人决定。回复别的内容不会关掉卡片。

记录留在服务器里。在聊天里发送 `/export`，或在本机运行：

```powershell
uv run solidus ledger export
```

文件在 `ledger/practice-001.jsonl`。用 Cursor 按这份记录写 script。仓库里有一份对照：`clients/scripts/practice.txt`。

检查并接受之后，客户端才会发：

```powershell
uv run solidus script check clients/scripts/practice.txt
uv run solidus script accept clients/scripts/practice.txt
uv run solidus client run clients/scripts/practice.txt
```

客户端遇到「须由人决定」就停发。你在手机上回复 `1`、`2` 或 `3` 之后，它再继续后面的机械步骤。`3` 会把聊天交还你。脚本走不通就停，不会自己改脚本。

`solidus accepted` 可以查看哪份 script、哪个 skill 是你接受的。

## 换 DeepSeek

改 `.env` 里的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`。说明见 [docs/配置.md](docs/配置.md)。

## 目录

```text
fixtures/practice/          练习页
src/solidus/server/         Telegram 入站、卡片、workflow
src/solidus/skills/         练习页、调试 Chrome、Gemini
src/solidus/agent/          只起草，不晋升
src/solidus/client/         按 script 发 Telegram
skills/promoted/            你晋升之后的 skill
skills/drafts/              草稿，不会被加载
clients/scripts/            你接受之后的脚本
clients/drafts/             脚本草稿
ledger/                     导出的记录，不含密码
```

## 测试

```powershell
uv run pytest
uv run ruff check src tests
```
