#!/bin/bash
envsubst < /tor/torrc.template > /tor/torrc

tor -f /tor/torrc &

while [ ! -f /tor/HiddenService/hostname ]; do
    sleep 1
done

if [ "$LOG_ADDRESS" = "true" ]; then
    echo "Server Tor Address: $(cat /tor/HiddenService/hostname)"
fi

tail -f /dev/null
