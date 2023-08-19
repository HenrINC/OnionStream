#!/bin/bash
envsubst < /tor/torrc.template > /tor/torrc

tor -f /tor/torrc &

while [ ! -f /tor/webserver/hostname ] || [ ! -f /tor/api/hostname ]; do
    sleep 1
done

if [ "$LOG_ADDRESS" = "true" ]; then
    echo "Web Server Tor Address: $(cat /tor/webserver/hostname)"
    echo "API Server Tor Address: $(cat /tor/api/hostname)"
fi

tail -f /dev/null
