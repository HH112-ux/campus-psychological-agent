#!/bin/sh
# 心屿 nginx 启动前置校验 + 配置渲染。
#
# 红线：证书/私钥缺失或不可用时**直接启动失败**并给出明确提示，
# 绝不静默降级为明文 HTTP（小程序提审要求全链路 HTTPS）。
set -eu

CERT="${TLS_CERT_PATH:-/etc/nginx/certs/server.crt}"
KEY="${TLS_KEY_PATH:-/etc/nginx/certs/server.key}"
SERVER_NAME="${TLS_SERVER_NAME:-_}"
TEMPLATE="${NGINX_TEMPLATE:-/etc/nginx/xinyu/nginx.conf.template}"

fail() {
    echo "[xinyu-nginx] 启动失败：$1" >&2
    echo "[xinyu-nginx] 请将域名证书与私钥放入 backend/nginx/certs/（默认 server.crt / server.key），" >&2
    echo "[xinyu-nginx] 或用 TLS_CERT_PATH / TLS_KEY_PATH 指定容器内路径；私钥严禁入库。" >&2
    exit 1
}

[ -f "$TEMPLATE" ] || fail "找不到配置模板 $TEMPLATE"
[ -s "$CERT" ] || fail "TLS 证书不存在或为空：$CERT"
[ -s "$KEY" ] || fail "TLS 私钥不存在或为空：$KEY"

sed -e "s|__TLS_CERT_PATH__|${CERT}|g" \
    -e "s|__TLS_KEY_PATH__|${KEY}|g" \
    -e "s|__TLS_SERVER_NAME__|${SERVER_NAME}|g" \
    "$TEMPLATE" > /etc/nginx/nginx.conf

# 语法与证书可用性校验（私钥与证书不匹配、已过期等会在这里报错）
nginx -t

exec nginx -g 'daemon off;'
