# 新服务器部署交接

本目录用于点凡阅卷的新服务器部署。进入本目录工作的 Codex 应先完整阅读：

1. `新服务器登录说明.md`
2. 本目录本地凭据文件 `.env`（已被仓库 `.gitignore` 忽略）
3. 项目根目录 `AGENTS.md`
4. 项目根目录 `docs/production-operations.md`

## 服务器边界

- 新服务器：`155.94.192.143`，SSH 端口 `22022`，用户 `root`。公网 `22` 已关闭。
- 旧服务器：`104.129.51.171:22080`。除非用户明确要求，不要连接或修改旧服务器。
- 已知 RackNerd 面板账号只管理旧服务器，不是新服务器控制面板；该账号已从本目录 `.env` 移除，禁止用它对新服务器执行重启。
- 新服务器上最后已知运行 AISubAPI、PostgreSQL、Redis 和 Nginx UI。不要停止、删除、迁移或覆盖这些服务及其数据。
- 最后已知占用端口：`80`、`443`、`9000`、`18080`、`22022`、`28080`。登录后必须以 `ss -lntup` 和 `docker ps` 的实时结果为准。

## 当前状态

- 2026-08-03 已恢复 SSH：公网 `22` 持续遭受密码爆破，未认证连接挤满 `MaxStartups`，导致正常连接在 banner 阶段被随机丢弃。
- 已安装并启用 fail2ban `sshd` jail；UFW 已撤销公网 `22`，仅对 `22022/tcp` 使用 `LIMIT IN`。`ssh-new-server.sh` 已验证可从当前 WSL 环境直接登录，不再依赖 FlClash。
- AISubAPI、独立 PostgreSQL/Redis、Nginx UI 和现有 `dianfan-staging` 容器均保持运行；不要覆盖或重建这些服务，除非用户明确要求部署。

## 操作约束

- 凭据只从本目录 `.env` 读取，不要在回复、日志、命令输出、Git 提交或 Markdown 中显示密码。
- 首次登录只做只读检查；确认磁盘、内存、端口、Docker 网络、容器和 `/opt` 目录后再制定部署方案。
- 点凡阅卷建议使用独立目录 `/opt/dianfan-grading`、独立 Compose project 和独立网络/volume；该路径尚未确认创建。
- 不要直接运行默认的 `docker compose up`：仓库的 `compose.override.yml` 是本地开发配置，会发布开发端口并启动本地 Traefik。
- 生产部署应显式指定 Compose 文件，例如 `docker compose -f compose.yml ...`，并先解决现有 Nginx 与项目 Traefik 标签/外部网络的衔接。
- 任何数据库或 volume 变更前先备份；替换镜像前保留带时间戳的回滚标签。
- 部署后至少验证容器健康、HTTP 健康端点、数据库迁移、worker、持久化目录、端口冲突和最近错误日志。
- 容器重建会换 IP：`deploy-staging.sh ... app` 之后必须 `docker exec nginx-ui nginx -s reload`，否则外层 nginx 按启动时解析的旧 IP 转发，公网 502（v0.2.0 部署时实测复现并解决）。
- 标准发布路径：本地打 `v*` tag 推送 → release.yml 构建 ghcr 镜像 → rsync 快照到 `releases/<tag>` 并切换 `current` 软链 → 服务器上 `export DIANFAN_IMAGE_*=ghcr.io/zxc123aa/...` 后 `deploy-staging.sh <tag> pull` + `app`（v0.2.0 首次全程走通）。
