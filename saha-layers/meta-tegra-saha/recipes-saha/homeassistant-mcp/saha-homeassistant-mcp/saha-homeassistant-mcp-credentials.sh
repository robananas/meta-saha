#!/bin/sh
set -eu

state_dir=/data/saha/homeassistant-mcp
credentials_file="$state_dir/credentials.env"

install -d -m 0700 "$state_dir"
if [ ! -s "$credentials_file" ]; then
    umask 077
    token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    board_ip=$(ip -4 -brief address show scope global | awk '$1 != "docker0" {split($3, value, "/"); print value[1]; exit}')
    [ -n "$board_ip" ] || board_ip=127.0.0.1
    {
        printf 'MCP_ACCESS_TOKEN=%s\n' "$token"
        printf 'MCP_PUBLIC_URL=http://%s:8000/mcp\n' "$board_ip"
    } > "$credentials_file"
fi
chown 0:999 "$credentials_file"
chmod 0640 "$credentials_file"
