# PaddleOCR GPU cu130 部署记录

更新时间：2026-07-02

## 本机结论

- GPU：NVIDIA GeForce RTX 5060 Laptop，8GB 显存。
- 驱动：596.49，`nvidia-smi` 显示 CUDA 13.2。
- 系统：WSL2 Ubuntu 26.04。
- 当前 backend Python：3.13.13，不适合直接承载 PaddleOCR GPU 依赖。
- Docker：Windows Docker CLI 可用，Docker runtime 已包含 `nvidia`。

结论：本机适合部署独立 `ocr-service`，使用 PaddleOCR GPU cu130。主 backend 继续保持 Python 3.13，Worker 通过 HTTP 调用 OCR 服务。

## 架构

```text
worker
  -> OCR_ENGINE=paddle_http
  -> POST http://ocr-service:8010/ocr
  -> ocr-service: Python 3.11 + paddlepaddle-gpu cu130 + PaddleOCR
  -> 返回 text/confidence/engine
```

## 启动方式

先修复 WSL 调用 Windows Docker CLI 时的 credential helper PATH 问题。当前错误形态：

```text
docker-credential-desktop: executable file not found in %PATH%
```

这个 helper 文件实际存在于：

```text
C:\Program Files\Docker\Docker\resources\bin\docker-credential-desktop.exe
```

但 Windows 侧 PATH 当前找不到它。需要在 Windows 环境变量 PATH 中加入：

```text
C:\Program Files\Docker\Docker\resources\bin
```

加完后重开终端，在 Windows PowerShell 验证：

```powershell
where.exe docker-credential-desktop
docker run --rm hello-world
```

验证 Docker GPU：

```bash
"/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu22.04 nvidia-smi
```

启动 OCR 服务：

```bash
OCR_ENGINE=paddle_http \
OCR_HTTP_URL=http://ocr-service:8010/ocr \
"/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose --profile ocr-gpu up --build ocr-service worker
```

本地单独测试 OCR 服务：

```bash
"/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose --profile ocr-gpu up --build ocr-service
curl http://localhost:8010/health
```

## 后续验证

1. 用真实题区 PNG 调 `/ocr`，确认 `text` 非空。
2. 打开教师复核页，运行处理任务，确认 OCR draft 不再是 `not configured`。
3. 记录真实样本识别质量，决定是否需要图像增强、语言模型、或 Kimi 低置信度复核。

## 注意

- `ocr-service` 是 compose profile，不会默认启动。
- 不要把 PaddleOCR GPU 依赖装进当前 backend 镜像。
- 如果 cu130 构建失败，再降级试 cu129/cu126；优先保留独立服务边界。
