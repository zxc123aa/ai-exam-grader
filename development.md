# FastAPI Project - Development

## Docker Compose

* Start the local stack with Docker Compose:

```bash
docker compose watch
```

* Now you can open your browser and interact with these URLs:

Frontend, built with Docker, with routes handled based on the path: <http://localhost:5173>

Backend, JSON based web API based on OpenAPI: <http://localhost:8000>

Automatic interactive documentation with Swagger UI (from the OpenAPI backend): <http://localhost:8000/docs>

Adminer, database web administration: <http://localhost:8080>

Traefik UI, to see how the routes are being handled by the proxy: <http://localhost:8090>

**Note**: The first time you start your stack, it might take a minute for it to be ready. While the backend waits for the database to be ready and configures everything. You can check the logs to monitor it.

To check the logs, run (in another terminal):

```bash
docker compose logs
```

To check the logs of a specific service, add the name of the service, e.g.:

```bash
docker compose logs backend
```

## Mailcatcher

Mailcatcher is a simple SMTP server that catches all emails sent by the backend during local development. Instead of sending real emails, they are captured and displayed in a web interface.

This is useful for:

* Testing email functionality during development
* Verifying email content and formatting
* Debugging email-related functionality without sending real emails

The backend is automatically configured to use Mailcatcher when running with Docker Compose locally (SMTP on port 1025). All captured emails can be viewed at <http://localhost:1080>.

## Local Development

The Docker Compose files are configured so that each of the services is available in a different port in `localhost`.

For the backend and frontend, they use the same port that would be used by their local development server, so, the backend is at `http://localhost:8000` and the frontend at `http://localhost:5173`.

This way, you could turn off a Docker Compose service and start its local development service, and everything would keep working, because it all uses the same ports.

For example, you can stop that `frontend` service in the Docker Compose, in another terminal, run:

```bash
docker compose stop frontend
```

And then start the local frontend development server:

```bash
bun run dev
```

Or you could stop the `backend` Docker Compose service:

```bash
docker compose stop backend
```

And then you can run the local development server for the backend:

```bash
cd backend
fastapi dev app/main.py
```

## Docker Compose in `localhost.tiangolo.com`

When you start the Docker Compose stack, it uses `localhost` by default, with different ports for each service (backend, frontend, adminer, etc).

When you deploy it to production (or staging), it will deploy each service in a different subdomain, like `api.example.com` for the backend and `dashboard.example.com` for the frontend.

In the guide about [deployment](deployment.md) you can read about Traefik, the configured proxy. That's the component in charge of transmitting traffic to each service based on the subdomain.

If you want to test that it's all working locally, you can edit the local `.env` file, and change:

```dotenv
DOMAIN=localhost.tiangolo.com
```

That will be used by the Docker Compose files to configure the base domain for the services.

Traefik will use this to transmit traffic at `api.localhost.tiangolo.com` to the backend, and traffic at `dashboard.localhost.tiangolo.com` to the frontend.

The domain `localhost.tiangolo.com` is a special domain that is configured (with all its subdomains) to point to `127.0.0.1`. This way you can use that for your local development.

After you update it, run again:

```bash
docker compose watch
```

When deploying, for example in production, the main Traefik is configured outside of the Docker Compose files. For local development, there's an included Traefik in `compose.override.yml`, just to let you test that the domains work as expected, for example with `api.localhost.tiangolo.com` and `dashboard.localhost.tiangolo.com`.

## Docker Compose files and env vars

There is a main `compose.yml` file with all the configurations that apply to the whole stack, it is used automatically by `docker compose`.

And there's also a `compose.override.yml` with overrides for development, for example to mount the source code as a volume. It is used automatically by `docker compose` to apply overrides on top of `compose.yml`.

These Docker Compose files use the `.env` file containing configurations to be injected as environment variables in the containers.

They also use some additional configurations taken from environment variables set in the scripts before calling the `docker compose` command.

After changing variables, make sure you restart the stack:

```bash
docker compose watch
```

## The .env file

The `.env` file is the one that contains all your configurations, generated keys and passwords, etc.

Depending on your workflow, you could want to exclude it from Git, for example if your project is public. In that case, you would have to make sure to set up a way for your CI tools to obtain it while building or deploying your project.

One way to do it could be to add each environment variable to your CI/CD system, and updating the `compose.yml` file to read that specific env var instead of reading the `.env` file.

## Pre-commits and code linting

we are using a tool called [prek](https://prek.j178.dev/) (modern alternative to [Pre-commit](https://pre-commit.com/)) for code linting and formatting.

When you install it, it runs right before making a commit in git. This way it ensures that the code is consistent and formatted even before it is committed.

You can find a file `.pre-commit-config.yaml` with configurations at the root of the project.

#### Install prek to run automatically

`prek` is already part of the dependencies of the project.

After having the `prek` tool installed and available, you need to "install" it in the local repository, so that it runs automatically before each commit.

Using `uv`, you could do it with (make sure you are inside `backend` folder):

```bash
❯ uv run prek install -f
prek installed at `../.git/hooks/pre-commit`
```

The `-f` flag forces the installation, in case there was already a `pre-commit` hook previously installed.

Now whenever you try to commit, e.g. with:

```bash
git commit
```

...prek will run and check and format the code you are about to commit, and will ask you to add that code (stage it) with git again before committing.

Then you can `git add` the modified/fixed files again and now you can commit.

#### Running prek hooks manually

you can also run `prek` manually on all the files, you can do it using `uv` with:

```bash
❯ uv run prek run --all-files
check for added large files..............................................Passed
check toml...............................................................Passed
check yaml...............................................................Passed
fix end of files.........................................................Passed
trim trailing whitespace.................................................Passed
ruff.....................................................................Passed
ruff-format..............................................................Passed
biome check..............................................................Passed
```

## CI 检查与本地复现

`.github/workflows/` 下有四条流水线，push 到 `main`、开 PR 和手动触发时都会跑：

| Workflow | 内容 |
| --- | --- |
| `lint-backend` | `ruff check` + `ruff format --check`，范围 `backend/app` 与 `backend/tests` |
| `test-backend` | `postgres:18` + `redis:7-alpine` service 容器 → `alembic upgrade head` → `backend/scripts/tests-start.sh`（coverage + pytest）→ `scripts/smoke-openapi.py`，覆盖率报告作为 artifact |
| `test-frontend` | `npm ci` → `biome ci` → `tsc -p tsconfig.build.json` → `vite build` |
| `lint-workflows` | `zizmor` 审计 workflow 自身 |

### 本地跑后端检查

测试会清库，因此 `POSTGRES_DB` 必须包含 `test`，否则 `tests/conftest.py` 会主动拒绝执行（这是保护开发库的安全门，不要绕过）。

```bash
# lint
uv run ruff check backend/app backend/tests
uv run ruff format backend/app backend/tests --check

# 测试：需要 PostgreSQL 与 Redis 可达
cd backend
export POSTGRES_DB=app_test
export EMAILS_FROM_EMAIL=noreply@example.com   # emails_enabled 依赖它，找回密码用例需要
export BILLING_ENFORCEMENT_ENABLED=false       # 测试数据没有学校合同，与 .env.example 一致
uv run alembic upgrade head
uv run bash scripts/tests-start.sh
```

`BILLING_ENFORCEMENT_ENABLED` 默认是 `true`（生产语义）。计费与商业化用例会自己 monkeypatch 打开门禁，所以关掉它不会降低这部分覆盖；但如果保持打开，几个上传答卷的用例会因为学校没有合同而收到 402。

### 本地跑前端检查

```bash
npm ci                                   # 依赖装在仓库根，frontend 是 npm workspace 成员
cd frontend
npx biome ci .                           # 注意：npm run lint 会带 --write 改文件，CI 用 biome ci
npx tsc -p tsconfig.build.json
npx vite build
```

### 门禁之外的检查

- **mypy / ty**：`backend/scripts/lint.sh` 和 pre-commit 里都有，但当前 strict 模式下分别有 588 / 489 条告警，绝大多数是 SQLModel/SQLAlchemy 表达式误报，因此没有纳入 CI。清理计划见 `docs/issue-backlog.md` AEG-060。
- **Playwright E2E**：live 用例需要真实模型 Key、Node 参考服务和系统 Chromium（`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium`），只能本地或手动跑。分层进 CI 的计划见 AEG-061。
- **`backend/scripts` 与根 `scripts/`**：运维与评测脚本按设计使用 `print`，与 ruff 的 T201 冲突，不纳入 lint 门禁。

## URLs

The production or staging URLs would use these same paths, but with your own domain.

### Development URLs

Development URLs, for local development.

Frontend: <http://localhost:5173>

Backend: <http://localhost:8000>

Automatic Interactive Docs (Swagger UI): <http://localhost:8000/docs>

Automatic Alternative Docs (ReDoc): <http://localhost:8000/redoc>

Adminer: <http://localhost:8080>

Traefik UI: <http://localhost:8090>

MailCatcher: <http://localhost:1080>

### Development URLs with `localhost.tiangolo.com` Configured

Development URLs, for local development.

Frontend: <http://dashboard.localhost.tiangolo.com>

Backend: <http://api.localhost.tiangolo.com>

Automatic Interactive Docs (Swagger UI): <http://api.localhost.tiangolo.com/docs>

Automatic Alternative Docs (ReDoc): <http://api.localhost.tiangolo.com/redoc>

Adminer: <http://localhost.tiangolo.com:8080>

Traefik UI: <http://localhost.tiangolo.com:8090>

MailCatcher: <http://localhost.tiangolo.com:1080>
