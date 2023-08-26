DEFAULT_INTERFACE=$(ip route | grep default | awk '{print $5}')
SUBNET=$(ip -o -f inet addr show $DEFAULT_INTERFACE | awk '{print $4}')
GATEWAY=$(ip route | grep default | awk '{print $3}')

NETWORK_NAME="restreamer_test_network"
if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "Network $NETWORK_NAME exists, removing..."
    docker network rm "$NETWORK_NAME"
fi

docker network create -d ipvlan \
    --subnet=$SUBNET \
    --gateway=$GATEWAY \
    -o parent=$DEFAULT_INTERFACE \
    $NETWORK_NAME

NETWORK_NAME="source_test_network"
if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "Network $NETWORK_NAME exists, removing..."
    docker network rm "$NETWORK_NAME"
fi

docker network create -d ipvlan \
    --subnet=$SUBNET \
    --gateway=$GATEWAY \
    -o parent=$DEFAULT_INTERFACE \
    $NETWORK_NAME