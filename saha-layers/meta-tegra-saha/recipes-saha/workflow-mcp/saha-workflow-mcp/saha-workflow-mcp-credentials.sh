#!/bin/sh
set -eu

state_dir=/data/saha/workflow-mcp
credentials_file="$state_dir/credentials.env"

install -d -m 0700 "$state_dir"
if [ ! -s "$credentials_file" ]; then
    umask 077
    token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    printf 'WORKFLOW_MCP_ACCESS_TOKEN=%s\n' "$token" > "$credentials_file"
fi
chown 0:999 "$credentials_file"
chmod 0640 "$credentials_file"
