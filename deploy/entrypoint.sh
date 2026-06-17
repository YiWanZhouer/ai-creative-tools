#!/bin/sh
set -e

# Substitute ${DEEPSEEK_API_KEY} in nginx config template → actual config
envsubst '${DEEPSEEK_API_KEY}' \
  < /etc/nginx/conf.d/default.conf.template \
  > /etc/nginx/conf.d/default.conf

# Start nginx in foreground
exec nginx -g 'daemon off;'
