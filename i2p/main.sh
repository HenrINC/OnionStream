#!/bin/bash

envsubst < /i2p/tunnels.conf.template > /i2p/tunnels.conf

i2pd --loglevel=error --tunconf=/i2p/tunnels.conf&

while [ ! -f /i2p/keys/keys.dat ]; do
    sleep 1
done

if [ "$LOG_ADDRESS" == "true" ]; then
    B32_ADDRESS=$(grep -o -E '([2-7a-z]{52}.b32.i2p)' /i2p/keys/keys.dat)

    echo "Server I2P Address: $B32_ADDRESS"
fi


tail -f /dev/null
