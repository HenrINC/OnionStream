#!/bin/sh
envsubst < /nginx/nginx.conf.template > /nginx/nginx.conf
exec nginx -c /nginx/nginx.conf -g 'daemon off;'