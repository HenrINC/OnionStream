#!/bin/bash

envsubst < /i2p/tunnels.conf.template > /i2p/tunnels.conf

i2pd --conf=/i2p/i2pd.conf --daemon

while [ ! -f /i2p/webserver-keys.dat ] || [ ! -f /i2p/api-keys.dat ]; do
    sleep 1
done

if [ "$LOG_ADDRESS" == "true" ]; then
    WEB_B32_ADDRESS=$(grep -o -E '([2-7a-z]{52}.b32.i2p)' /i2p/webserver-keys.dat)
    API_B32_ADDRESS=$(grep -o -E '([2-7a-z]{52}.b32.i2p)' /i2p/api-keys.dat)

    echo "Web Server I2P Address: $WEB_B32_ADDRESS"
    echo "API Server I2P Address: $API_B32_ADDRESS"
fi


tail -f /dev/null
