# 加密密钥轮换 Runbook（`DATA_ENCRYPTION_KEY`）

> 适用代码：`18065e0` 起（密文信封含 `key_id`，读取支持 `DATA_ENCRYPTION_KEY_PREVIOUS` 兜底）
> 风险级别：高（加密与密钥）。按 `AGENTS.md` §2，执行前须有第二人复核，并先确定停机窗口与回滚方式。
> 关联：[SECURITY.md](../SECURITY.md) §2、[backend/.env.example](../backend/.env.example)、[crypto.py](../backend/app/core/crypto.py)

## 1. 先看懂机制

- **写入**：敏感字段用 `DATA_ENCRYPTION_KEY`（AES-256-GCM）加密，落库结构为：

  ```json
  {"__enc": true, "key_id": "v1", "iv": "...", "ct": "...", "tag": "..."}
  ```

  `key_id` 取自 `DATA_ENCRYPTION_KEY_ID`，只用于审计，**不参与解密选钥**。
- **读取**：先用当前钥解密；抛 `InvalidTag` 时再用 `DATA_ENCRYPTION_KEY_PREVIOUS`；previous 为空则把异常继续上抛。
- **只支持一个 previous**。因此每次只能轮换一代，且上一代密文必须在下次轮换前全部重写完成。
- **读取侧没有字段级降级**：`sessions.list_sessions`、`sessions.get_session`、`privacy.export_user_data` 都直接调用 `decrypt_optional_text` / `decrypt`。只要有一处旧密文解不开，整个请求 500，而不是某条记录留空。
- **密钥格式**：base64url 编码的 32 字节；长度或编码不对时启动即 `RuntimeError`，不会静默降级。

重写需要覆盖的加密字段：

| 集合 | 字段 |
|---|---|
| `messages` | `content` |
| `messages` | `emotion.evidence` |
| `sessions` | `title` |
| `emotion_records` | `evidence` |
| `checkins` | `note` |
| `risk_events` | `matched[]`（数组元素） |
| `memories` | `content` |

## 2. 顺序红线：先配 `PREVIOUS`，再换当前钥

正确顺序（两次重启）：

1. 当前钥保持不变，把旧钥同时写入 `DATA_ENCRYPTION_KEY_PREVIOUS`；
2. 再把 `DATA_ENCRYPTION_KEY` 换成新钥、`DATA_ENCRYPTION_KEY_ID` 换成新版本号。

**顺序反了会怎样（对应审查报告 C-1）**：直接把 `DATA_ENCRYPTION_KEY` 改成新钥、`PREVIOUS` 仍为空，所有旧密文在当前钥上都会 `InvalidTag`；`_previous()` 返回 `None` 后异常继续上抛，会话列表、会话详情、数据导出整页 500。此时再补 `PREVIOUS` 也必须再次重启，停机窗口内已加密数据全部不可读。

> 第 1 步单独执行时，`PREVIOUS` 与当前钥相同，写入行为不变，是安全的「预置」动作，用来确认配置能被正常加载。

## 3. 轮换前检查

以下命令在 `backend/` 目录执行。所有检查只输出布尔值和数量，不打印密钥。

### 3.1 确认当前配置状态

```bash
docker compose --profile prod exec api python -c \
  "from app.config import get_settings as g; s=g(); print('key_set=', bool(s.data_encryption_key), 'key_id=', s.data_encryption_key_id, 'previous_set=', bool(s.data_encryption_key_previous))"
```

预期：`key_set= True key_id= v1 previous_set= False`。若 `previous_set` 已经是 `True`，说明上一次轮换没有收尾，先按第 8 节确认状态，不要直接开始新一轮。

### 3.2 备份数据库（必须）

```bash
docker compose exec -T mongo sh -c \
  'mongodump --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db xinyu --archive' \
  > backup-before-key-rotation-$(date +%Y%m%d%H%M).archive
```

`--db xinyu` 按 `MONGODB_DB` 的实际值替换。备份文件含全部对话密文，按敏感数据保管，轮换验收完成后按留存策略处置。

### 3.3 生成新钥

```bash
.venv/bin/python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

输出只应粘贴进 `backend/.env`，不要留在 shell 历史、工单或聊天记录里。

### 3.4 记录变更信息

在变更单里写明：旧 `key_id`、新 `key_id`（例如 `v1` → `v2`）、执行人、复核人、开始时间、备份文件名。**只记版本号，不记密钥**。

### 3.5 确认部署形态

- 当前仓库 `docker-compose.yml` 是单 `api` 容器：按本文步骤重启即可。
- 多实例部署必须整体停机，或确保所有实例在同一时刻拿到 `current=新钥 + previous=旧钥`。否则旧配置实例读到新密文（它既没有新钥，也没有对应 previous）会 500。
- 修改 `.env` 后**不能用 `docker compose restart`**：它只重启进程，不重新读取 `env_file`。必须用 `up -d --force-recreate`。

## 4. 第一步：预置旧钥到 previous（当前钥不动）

编辑 `backend/.env`：

```dotenv
DATA_ENCRYPTION_KEY=<现有旧钥，原样保留>
DATA_ENCRYPTION_KEY_ID=v1
DATA_ENCRYPTION_KEY_PREVIOUS=<同一把旧钥>
```

重建容器：

```bash
docker compose --profile prod up -d --force-recreate api
```

验证：

```bash
# 配置已加载，且 previous 已就位
docker compose --profile prod exec api python -c \
  "from app.config import get_settings as g; s=g(); print('key_id=', s.data_encryption_key_id, 'previous_set=', bool(s.data_encryption_key_previous))"
# 服务与数据库连通
curl -fsS https://<域名>/health
# 用测试账号读会话列表，确认旧数据仍可解密
curl -fsS -H "Authorization: Bearer <测试账号 token>" https://<域名>/api/v1/sessions
```

预期：`previous_set= True`，健康检查返回 `status: ok`、`db: connected`，会话列表 200。

## 5. 第二步：切换新钥与版本号

编辑 `backend/.env`：

```dotenv
DATA_ENCRYPTION_KEY=<新钥>
DATA_ENCRYPTION_KEY_ID=v2
DATA_ENCRYPTION_KEY_PREVIOUS=<旧钥>
```

重建容器：

```bash
docker compose --profile prod up -d --force-recreate api
```

验证三件事：

1. 配置生效：

   ```bash
   docker compose --profile prod exec api python -c \
     "from app.config import get_settings as g; s=g(); print('key_id=', s.data_encryption_key_id, 'previous_set=', bool(s.data_encryption_key_previous))"
   ```

   预期：`key_id= v2 previous_set= True`。

2. 旧数据仍可读（走 previous 兜底）：

   ```bash
   curl -fsS -H "Authorization: Bearer <测试账号 token>" https://<域名>/api/v1/sessions
   curl -fsS -H "Authorization: Bearer <测试账号 token>" https://<域名>/api/v1/users/me/data/export
   ```

   两者都必须 200。任一 500 立即停止，按第 8 节回退。

3. 新写入使用新钥：用测试账号新建一个带标题的会话，再查库确认最新标题的 `key_id` 为 `v2`：

   ```bash
   docker compose exec -T mongo sh -c \
     'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin xinyu --eval "db.sessions.find({}, {title:1}).sort({created_at:-1}).limit(3).toArray()"'
   ```

## 6. 第三步：全量重写旧钥密文

> **注意**：`scripts/migrate_encrypt_sensitive_fields.py` 只把**明文**加密，遇到已加密记录会跳过。它不能把旧钥密文改写成新钥密文，轮换必须单独做一次重写。

在 `current=新钥、previous=旧钥` 已生效的前提下，执行以下重写（覆盖第 1 节全部字段；已带新 `key_id` 的记录会跳过，可重复执行）：

```bash
docker compose --profile prod exec -T api python - <<'PY'
import asyncio

from app.config import get_settings
from app.core.crypto import decrypt, encrypt, is_encrypted
from app.db.mongo import mongo

NEW_ID = get_settings().data_encryption_key_id
FIELDS = [
    ("messages", "content"),
    ("messages", "emotion.evidence"),
    ("sessions", "title"),
    ("emotion_records", "evidence"),
    ("checkins", "note"),
    ("memories", "content"),
]


def rewrite(value):
    if value in (None, ""):
        return value
    if is_encrypted(value):
        if value.get("key_id") == NEW_ID:
            return value
        return encrypt(decrypt(value))  # 旧钥经 previous 解出，再用新钥加密
    if isinstance(value, str):
        return encrypt(value)
    return value


def get_path(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


async def main():
    await mongo.connect()
    for coll, path in FIELDS:
        changed = 0
        async for doc in mongo.db[coll].find({path: {"$exists": True}}):
            old = get_path(doc, path)
            new = rewrite(old)
            if new == old:
                continue
            await mongo.db[coll].update_one({"_id": doc["_id"]}, {"$set": {path: new}})
            changed += 1
        print(f"[DONE] {coll}.{path}: {changed}")

    changed = 0
    async for doc in mongo.db["risk_events"].find({"matched": {"$exists": True}}):
        old = doc.get("matched") or []
        new = [rewrite(x) for x in old]
        if new != old:
            await mongo.db["risk_events"].update_one({"_id": doc["_id"]}, {"$set": {"matched": new}})
            changed += 1
    print(f"[DONE] risk_events.matched: {changed}")

    stale = 0
    for coll, path in FIELDS:
        async for doc in mongo.db[coll].find({path: {"$exists": True}}):
            value = get_path(doc, path)
            if is_encrypted(value) and value.get("key_id") != NEW_ID:
                stale += 1
    async for doc in mongo.db["risk_events"].find({"matched": {"$exists": True}}):
        stale += sum(
            1
            for x in (doc.get("matched") or [])
            if is_encrypted(x) and x.get("key_id") != NEW_ID
        )
    print(f"[CHECK] 仍使用旧 key_id 的字段数: {stale}")


asyncio.run(main())
PY
```

收口判据：`[CHECK] 仍使用旧 key_id 的字段数: 0`。不为 0 不得进入下一步。

## 7. 第四步：清空 previous

只有同时满足以下条件才可清空：

- `[CHECK] 仍使用旧 key_id 的字段数: 0`；
- 会话列表、会话详情、数据导出均 200；
- 已用测试账号完整走一轮「发消息 → 回读 → 导出」。

编辑 `backend/.env`，把 `DATA_ENCRYPTION_KEY_PREVIOUS` 置空：

```dotenv
DATA_ENCRYPTION_KEY=<新钥>
DATA_ENCRYPTION_KEY_ID=v2
DATA_ENCRYPTION_KEY_PREVIOUS=
```

重建并复验：

```bash
docker compose --profile prod up -d --force-recreate api
docker compose --profile prod exec api python -c \
  "from app.config import get_settings as g; s=g(); print('key_id=', s.data_encryption_key_id, 'previous_set=', bool(s.data_encryption_key_previous))"
curl -fsS https://<域名>/health
```

预期：`previous_set= False`，健康检查正常，会话列表/详情/导出仍 200。

清空后把旧钥转入离线备份（按 `SECURITY.md` §2 的密钥保管要求），不要留在服务器配置中。

## 8. 出错回退

| 阶段 | 现象 | 回退动作 |
|---|---|---|
| 仅完成第 4 步（预置 previous） | 配置加载失败 / 服务起不来 | 把 `DATA_ENCRYPTION_KEY_PREVIOUS` 置空，`up -d --force-recreate api`；数据未受影响 |
| 第 5 步切换后、重写开始前 | 会话列表或导出 500 | `.env` 恢复为 `current=旧钥、PREVIOUS=空`，`up -d --force-recreate api`；旧数据直读恢复 |
| 第 6 步重写进行中/部分完成 | 服务异常或需要中止 | 保持双向可读：`DATA_ENCRYPTION_KEY=旧钥`、`DATA_ENCRYPTION_KEY_PREVIOUS=新钥`、`DATA_ENCRYPTION_KEY_ID=旧版本号`，重建后旧数据直读、新钥数据走 previous。确认恢复后再决定是否重跑轮换 |
| 第 7 步清空 previous 后 | 仍有旧密文读不出（漏重写） | 若旧钥仍保留：临时把旧钥放回 `DATA_ENCRYPTION_KEY_PREVIOUS`，重建后重新执行第 6 步；若无旧钥可用，从 3.2 的备份恢复 |

任何回退都先执行 `up -d --force-recreate api`，确认 `/health` 与三个读取接口恢复后再继续排查。

## 9. 执行清单

| # | 动作 | 完成判据 |
|---|---|---|
| 1 | 3.1 确认初始状态 | `previous_set= False` |
| 2 | 3.2 备份数据库 | 归档文件生成且大小非 0 |
| 3 | 3.3 生成新钥并记录新 `key_id` | 密钥为 base64url 32 字节；变更单已登记版本号 |
| 4 | 第 4 步预置旧钥到 previous | `previous_set= True`，旧数据读取 200 |
| 5 | 第 5 步切换新钥 | `key_id= 新版本号`；旧数据读取 200；新写入 `key_id` 为新版本号 |
| 6 | 第 6 步全量重写 | `[CHECK] 仍使用旧 key_id 的字段数: 0` |
| 7 | 第 7 步清空 previous | `previous_set= False`；列表/详情/导出 200 |
| 8 | 收尾 | 旧钥转离线保管；变更单记录完成时间与复核人 |
