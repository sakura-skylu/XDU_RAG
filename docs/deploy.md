# 服务器部署说明

推荐用 Docker Compose 部署。本项目会启动两个服务：

- `api`：FastAPI 后端，默认端口 `8000`
- `web`：Streamlit 前端，默认端口 `8501`

## 1. 准备服务器

以 Ubuntu/Debian 为例，安装 Docker：

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

如果当前用户还不能运行 Docker：

```bash
sudo usermod -aG docker "$USER"
```

然后重新登录服务器。

## 2. 上传项目

在服务器上创建目录：

```bash
sudo mkdir -p /opt/xidian-rag
sudo chown -R "$USER":"$USER" /opt/xidian-rag
cd /opt/xidian-rag
```

把项目代码上传到 `/opt/xidian-rag`。如果用 Git，拉取仓库即可；如果直接从本机传，至少需要这些内容：

```text
app/
config/
src/
data/
.env
.env.example
Dockerfile
docker-compose.yml
pyproject.toml
requirements.txt
README.md
```

注意：`data/` 里要包含已经构建好的 `documents.jsonl`、`chunks.jsonl` 和 `index/local_vectors.json`。如果服务器上重新建库，也可以上传原始资料后在容器里运行索引命令。

## 3. 配置环境变量

服务器目录下需要 `.env`。可以从 `.env.example` 复制：

```bash
cp .env.example .env
nano .env
```

确认以下配置：

```text
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_CHAT_MODEL=deepseek-v4-flash
ZHIPU_API_KEY=你的智谱APIKey
OPENAI_EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
OPENAI_EMBEDDING_MODEL=embedding-3
OPENAI_EMBEDDING_DIMENSIONS=2048
USE_API_EMBEDDINGS=true
USE_API_CHAT=true
USE_DIRECT_API_CHAT=false
VECTOR_STORE=local
```

## 4. 启动

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f
```

访问：

- 前端：`http://服务器IP:8501`
- API 文档：`http://服务器IP:8000/docs`

如果只是自己使用，建议先只在防火墙里开放 `8501`；`8000` 可以留给内网或后续通过 Nginx 做反向代理。

## 5. 常用维护命令

重启：

```bash
docker compose restart
```

停止：

```bash
docker compose down
```

更新代码后重建：

```bash
docker compose up -d --build
```

如果要在服务器上重新生成索引：

```bash
docker compose run --rm api xidian-rag index
docker compose restart
```
