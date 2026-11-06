# 证书目录

生产 nginx（`docker compose --profile prod up -d`）从这里读取域名证书：

- `server.crt`：证书链（含中间证书）
- `server.key`：私钥

规则：
- `*.key` / `*.pem` / `*.crt` 已被 `.gitignore` 拦截，**严禁入库**；
- 文件缺失或私钥与证书不匹配时，nginx 容器会明确报错并退出，不会降级为明文 HTTP；
- 证书路径可用 `TLS_CERT_PATH` / `TLS_KEY_PATH` 覆盖（见 `.env.example`）。
