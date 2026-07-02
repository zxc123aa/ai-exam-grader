# PaddleOCR GPU cu130 部署记录

更新时间：2026-07-02

## 本机结论

- GPU：NVIDIA GeForce RTX 5060 Laptop，8GB 显存。
- 驱动：596.49，`nvidia-smi` 显示 CUDA 13.2。
- 系统：WSL2 Ubuntu 26.04。
- 当前 backend Python：3.13.13，不适合直接承载 PaddleOCR GPU 依赖。
- Docker：Windows Docker CLI 可用，Docker runtime 已包含 `nvidia`。

结论：本机适合部署独立 `ocr-service`，使用 PaddleOCR GPU cu130。主 backend 继续保持 Python 3.13，Worker 通过 HTTP 调用 OCR 服务。当前镜像基于 `nvidia/cuda:13.0.0-base-ubuntu22.04`，容器内使用 Ubuntu 22.04 自带 Python 3.10。

## 架构

```text
worker
  -> OCR_ENGINE=paddle_http
  -> POST http://ocr-service:8010/ocr
  -> ocr-service: Python 3.10 + paddlepaddle-gpu cu130 + PaddleOCR
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

当前临时 workaround 是从 WSL 调 PowerShell 时补 PATH：

```bash
"/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" -NoProfile -Command \
'$env:PATH += ";C:\Program Files\Docker\Docker\resources\bin"; & "C:\Program Files\Docker\Docker\resources\bin\docker.exe" compose --profile ocr-gpu up -d ocr-service'
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

## 已验证

- `docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu22.04 nvidia-smi` 通过，容器内可见 RTX 5060 Laptop。
- `docker compose --profile ocr-gpu up -d ocr-service` 可启动，容器状态为 `healthy`。
- `GET http://localhost:8010/health` 返回 `{"status":"ok","engine":"paddleocr-gpu-cu130"}`。
- 容器内 `paddlepaddle-gpu==3.3.0`、`paddle.device.get_device()` 为 `gpu:0`，`paddle.utils.run_check()` 通过。
- `POST /ocr` 使用 `materials/English/processed/test1/page_1_left.jpg` 返回真实试卷文本，`confidence` 约 `0.989`，`engine` 为 `paddleocr-gpu-cu130`。
- 后端 Worker 已有回归测试覆盖 `OCR_ENGINE=paddle_http` 时把 HTTP OCR 结果写入 `SubmissionAnnotation`。

## 后续验证

1. 打开教师复核页，运行处理任务，确认 OCR draft 不再是 `not configured`。
2. 用更多真实题区 PNG 记录识别质量，决定是否需要图像增强、语言模型、或 Kimi 低置信度复核。
3. 给 `ocr-service` 增加模型缓存卷，避免容器重建后重复下载 PaddleOCR 模型权重。

## 注意

- `ocr-service` 是 compose profile，不会默认启动。
- 不要把 PaddleOCR GPU 依赖装进当前 backend 镜像。
- 如果 cu130 构建失败，再降级试 cu129/cu126；优先保留独立服务边界。
