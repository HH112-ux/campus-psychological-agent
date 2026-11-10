# 生产编排（prod profile）本机部署演练报告

> 日期：2026-11-10
> 范围：`backend/docker-compose.yml` 的 `--profile prod` 全链路（mongo + api + nginx/TLS）
> 方式：本机 Colima 上的真实 `docker compose config` + `build` + `up -d`，非语法校验
> 结论摘要：**prod 编排在本机真实跑通过一次**（含 HTTPS、限流、认证读写、加密字段迁移），但**尚未部署到任何真实服务器**，且依赖真实微信/智谱/ASR 凭据的环节未验证。

## 一、直接回答「系统真的部署过吗」

| 问题 | 回答 |
|---|---|
| 是否真实执行过 prod 编排？ | **是**。本次在本机用 Colima 真跑 `docker compose --profile prod config` 与 `up --build -d`，三个容器全部起来且 healthy。 |
| 部署到哪一步？ | 单机全链路跑通：客户端 → nginx(443/TLS) → api(8000/非 root) → mongo(仅集群网络)。初始化（root 账号、加密字段迁移）与认证读写均已实测。 |
| 是否部署到真实服务器/域名？ | **否**。无公网入口、无备案域名、无正式证书，全部在本机回环地址上用自签证书完成。 |
| 还差什么？ | 见第六节。核心是：真实第三方凭据（微信 AppID/Secret、智谱 Key、ASR 网关）、正式证书与域名、Redis 共享状态、镜像源与 pip 源的固化、备份与监控。 |

一句话给评委的口径：**编排本身已被真实验证可运行**（不是"写好了没跑过"），**但从未以正式凭据在真实服务器上对外提供过服务**。

## 二、环境与前置

- 容器运行时：Colima（vz 虚拟机，Docker 29.5.2），**不是 Docker Desktop**。
- 镜像源：Docker Hub 直连不可用，改用 `docker.1ms.run` / `docker.m.daocloud.io`。
- 证书：`openssl` 自签，SAN=`DNS:localhost,IP:127.0.0.1`，放 `backend/nginx/certs/`（已被 `.gitignore` 覆盖）。
- 配置：`backend/.env` 临时替换为演练专用值（真实值备份后还原）。

## 三、验收结果（全部为实际执行输出）

| # | 验收点 | 命令/方式 | 实际结果 |
|---|---|---|---|
| 1 | `/health` 通 | `curl -k https://localhost/health` | `200`，`{"status":"ok","service":"xinyu-backend","version":"0.2.0","env":"prod","db":"connected"}` |
| 2 | 经 nginx 的 `/api/v1/...` 通 | `curl -k https://localhost/api/v1/crisis/resources` | `200`，返回 `version:2` 的求助资源列表 |
| 3 | 非白名单路径 404 | `curl -k https://localhost/whatever` | `404`（nginx 默认拒绝，未透传后端） |
| 4 | 未认证接口 401 | `curl -k https://localhost/api/v1/sessions` | `401`，`{"code":1002,"message":"缺少 access_token"}` |
| 5 | 安全响应头 | `curl -kI https://localhost/health` | `Strict-Transport-Security: max-age=31536000`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、`Permissions-Policy: camera=(), geolocation=()`、`server: nginx`（已 `server_tokens off`） |
| 6 | 限流生效 | 连续 10 次 `POST /api/v1/auth/wx-login` | `401 401 401 401 401 401 429 429 429 429`（burst=5 + 10r/m，第 7 次起被 nginx 拦截，nginx error.log 有 `limiting requests ... zone "auth_login"`） |
| 7 | 80 跳转 | `curl http://localhost/api/v1/crisis/resources` | `301` → `https://localhost/api/v1/crisis/resources` |
| 8 | Mongo 不对外暴露 27017 | `docker compose port mongo 27017`；`docker inspect xinyu-mongo` | 输出 `:0`；`NetworkSettings.Ports = {"27017/tcp":null}`，未发布到宿主机 |
| 9 | 容器非 root | `docker exec xinyu-api id` | `uid=10001(appuser) gid=10001(appuser)` |
| 10 | healthcheck 状态 | `docker inspect --format '{{.State.Health.Status}}'` | `xinyu-api healthy`、`xinyu-mongo healthy` |

补充：`docker compose ps` 显示 nginx 只发布 `80/tcp`、`443/tcp`，api/mongo 仅 `expose`，符合"443 是唯一业务入口"的设计。

## 四、首次初始化流程

1. **Mongo root 账号**：由 `MONGO_INITDB_ROOT_USERNAME/PASSWORD` 在首次启动时创建。实测 `mongosh -u $MONGO_INITDB_ROOT_USERNAME -p $MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase admin --eval 'db.adminCommand({ping:1}).ok'` 返回 `1`。
2. **加密字段迁移**（`scripts/migrate_encrypt_sensitive_fields.py`）：先插入明文历史数据（`checkins.note`、`emotion_records.evidence` 各 1 条），再执行：

```
# dry-run
[DRY-RUN] emotion_records.evidence: 1 条
[DRY-RUN] messages.emotion.evidence: 0 条
[DRY-RUN] checkins.note: 1 条
[DRY-RUN] risk_events.matched: 0 条

# 实跑
[DONE] emotion_records.evidence: 1 条
[DONE] messages.emotion.evidence: 0 条
[DONE] checkins.note: 1 条
[DONE] risk_events.matched: 0 条
```

3. **迁移结果校验**：字段由明文字符串变为 `{__enc: true, iv, ct, tag}`；用 `app.core.crypto.decrypt` 解回原文（`演练用明文备注` / `演练用明文摘录`）一致。
4. **幂等性**：再次实跑，四个字段均为 `0 条`，未二次加密。
5. **服务读写**：插入合法 `ObjectId` 用户并签发 access token 后，经 nginx 实测
   - `POST /api/v1/sessions` → `201`，返回 `session_id`；
   - `GET /api/v1/sessions` → `200`，`total:1`。

## 五、本次真实踩到的坑（按出现顺序）

### 坑 1：本地 `.env` 缺 `MONGO_ROOT_USERNAME/PASSWORD`，`config` 直接失败

```
error while interpolating services.mongo.environment.MONGO_INITDB_ROOT_PASSWORD:
required variable MONGO_ROOT_PASSWORD is missing a value: 请在 .env 配置 MONGO_ROOT_PASSWORD
```

`.env.example` 有这两项，但本地 `.env` 只有 `MONGODB_URI`，从未补过。**这是最容易被忽略的坑**：本机 dev 路径根本不走 compose 的 mongo，所以一直没暴露。修法：在 `.env` 补 `MONGO_ROOT_*`，且必须与 `MONGODB_URI` 中的账号密码一致（否则 api 连不上）。

### 坑 2：Docker Hub 不可达

```
failed to resolve reference "docker.io/library/mongo:7": dial tcp 202.160.128.205:443: i/o timeout
```

本机 `docker info` 的 `RegistryConfig.Mirrors` 为空。改用国内镜像源拉取后可通。

### 坑 3：镜像源对特定镜像卡死 / containerd ingest 报错

- `docker.1ms.run` 对 `python:3.12-slim` 反复停在全部层 `Download complete` 后不再推进（等待 3 分钟以上无日志增量）；`mongo:7` 也出现同样停滞。
- 走 `docker.m.daocloud.io` 时曾报：

```
failed commit on ref "layer-sha256:bb371a8e9e66...":
rename /var/lib/containerd/io.containerd.content.v1.content/ingest/319f1b.../data
/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256/bb371a8e9e66...: no such file or directory
```

排除磁盘问题（虚拟机内可用 81.7G）。判断为被中断的拉取在 containerd content store 留下残缺 ingest 目录，导致同一 layer digest 的 commit 反复失败。`colima restart` 后该问题消失，`python:3.12-slim` 与 `mongo:7` 均由 daocloud 源拉取成功。

**运维提示**：中断 `docker pull` 不要只 `Ctrl-C` 后立刻重试，先确认 CLI 进程退出再拉；同一镜像不要并发从两个源拉（layer digest 相同会互相抢占 ingest）。

### 坑 4：镜像源拉下来的是带前缀的名字，compose 找不到

`docker pull docker.m.daocloud.io/library/mongo:7` 落地为 `docker.m.daocloud.io/library/mongo:7`，而 compose 引用 `mongo:7`。需本地打标签：

```
docker tag docker.m.daocloud.io/library/mongo:7 mongo:7
docker tag docker.m.daocloud.io/library/python:3.12-slim python:3.12-slim
```

（未修改 compose 文件。）

### 坑 5：构建时容器内 pip 连不上 PyPI

```
pip._vendor.urllib3.exceptions.ReadTimeoutError:
HTTPSConnectionPool(host='files.pythonhosted.org', port=443): Read timed out.
```

宿主机访问 PyPI 也很慢（8s 才建连），容器内直接超时。**绕过方式**：临时在 `Dockerfile` 加 `ARG PIP_INDEX_URL` 并用 `--build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 构建，构建成功后已**立即还原 Dockerfile，未提交**。

> 留给后续的正式修法（尚未实施，需评审后再改）：在国内构建环境固化 pip 镜像源，或改用预构建依赖层/私有源。这是一项真实的部署前置条件，不是本次演练的临时怪癖。

### 坑 6：`--profile prod` 下 api 的 env_file 与 compose 变量替换是两套来源

`api` 的 `env_file: .env` 决定容器内环境；`MONGO_ROOT_*` 的 `${VAR:?}` 由 compose 读取同目录 `.env` 做替换。两者都指向 `backend/.env`，所以只改一处会导致"变量替换通过但容器里没有对应值"。演练中统一用一个临时 `.env` 同时满足两者。

### 坑 7：非 ObjectId 的 `sub` 返回 404 而不是 401

演练时用字符串 id 伪造用户，`GET /api/v1/sessions` 返回 `404 {"code":2001,"message":"资源不存在"}` 而非 401。原因是 `get_current_user` 内的 `get_by_id` 先走 `parse_oid`，非法 id 抛 `CODE_NOT_FOUND`。真实链路里 `sub` 恒为 ObjectId，不影响功能，但**属于错误码语义瑕疵**：令牌合法但指向非法 id 时，语义上更应是 401。未修改代码，仅记录。

### 坑 8：prod 下 `SHARED_STATE_BACKEND=memory` 只告警不拦截

启动日志：

```
生产环境 SHARED_STATE_BACKEND 非 redis，限流/告警冷却/计数不跨实例共享
```

起步阶段可接受，但多实例部署会失效，已写入"还差什么"。

## 六、还差什么（上真实生产前必须补齐）

1. **真实凭据**：`WX_APPID/WX_SECRET`（微信登录与内容安全）、`ZHIPU_API_KEY`、ASR 网关 `ASR_ENDPOINT_URL/ASR_API_KEY`。本次全部是合成值，只够通过 prod 启动校验，真实登录/对话/转写均未验证（实测 `wx-login` 返回 `errcode=40013 invalid appid`，符合预期）。
2. **正式证书与域名**：替换自签证书，配置 DNS 与（如需）备案；HSTS 一旦下发不可撤销，上线前确认域名已定。
3. **Redis**：`SHARED_STATE_BACKEND=redis`，否则多实例下限流与冷却失效。
4. **构建可复现**：固化 pip 镜像源/私有源与镜像仓库地址，避免每次部署依赖手工 `docker tag`。
5. **Mongo 认证与最小权限**：当前 api 直接用 root 账号连接，生产应建独立业务账号并限制到单库。
6. **备份与监控**：`mongo-data` 卷的备份策略、日志采集、`/health` 外部探活告警。
7. **数据迁移的正式执行顺序**：本次是"先插数据再迁移"，正式环境需确认迁移脚本在流量进入前执行，并保留回滚点。

## 七、演练使用的临时值（生产必须全部替换）

| 项 | 演练取值方式 | 生产要求 |
|---|---|---|
| `MONGO_ROOT_USERNAME/PASSWORD` | `openssl rand -hex 16` 临时生成 | 独立强口令，由密钥管理下发 |
| `JWT_SECRET` | `openssl rand -hex 32` | ≥32 位随机串，定期轮换 |
| `DATA_ENCRYPTION_KEY` | `openssl rand -base64 32`（base64url，32 字节） | 密钥管理系统保管，**丢失即不可解密历史数据** |
| `WX_APPID/WX_SECRET` | 合成占位 | 真实小程序凭据 |
| `ZHIPU_API_KEY` | 合成占位 | 真实 Key，配额与限速需评估 |
| `ASR_*` | 指向 `127.0.0.1:9` 的假地址 | 真实 ASR 网关 |
| TLS 证书 | 自签 2 天有效期 | CA 签发正式证书 |

以上全部只存在于本次演练的临时 `backend/.env`（演练后已还原）与容器运行时，**未写入任何入库文件**。

## 八、清理与状态确认

- `docker compose --profile prod down -v`：3 个容器停止并删除，`backend_mongo-data` 卷与 `backend_default` 网络已删除。
- 自签证书 `backend/nginx/certs/server.{crt,key}` 已删除（目录仅剩 `README.md`）。
- `backend/.env` 已还原为演练前内容（MD5 校验一致）。
- `Dockerfile` 的临时 `ARG` 已还原，`git status` 无本次演练产生的改动。
- 无遗留 `xinyu-*` 容器/卷/网络；本机其余 13 个容器（`lp-*`）在 Colima 重启后已自动恢复，未被本次演练影响。

## 九、结论性判断

**这次演练证明的是**：`backend/docker-compose.yml` 的 `--profile prod` 编排不是纸面配置，它能在真实容器运行时里完整起栈并通过验收——HTTPS 唯一入口、80 跳转、白名单路由、401/404 语义、安全响应头、限流、Mongo 不对外、非 root、healthcheck、加密字段迁移与认证读写都实测通过。

**这次演练没有证明的是**：系统**没有**以正式凭据在真实服务器上对外提供过服务。微信登录/内容安全、智谱对话、ASR 转写这三条真实外部依赖全部用的是合成凭据，只验证到"启动校验能过、请求能打到第三方并正确报错"；也没有公网入口、正式域名与 CA 证书、Redis 共享状态、备份监控。因此本报告不能作为"已上线"的证据，只能作为"编排可运行、部署路径已走通"的证据。
