#!/bin/bash

NETWORK_NAME="restreamer_network"
RANGE_START="128"
RANGE_LENGTH="26"

# Check if the network exists
if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "Network $NETWORK_NAME exists, removing..."
    docker network rm "$NETWORK_NAME"
fi

# Get the default network interface, subnet, and gateway
DEFAULT_INTERFACE=$(ip route | grep default | awk '{print $5}')
SUBNET=$(ip -o -f inet addr show $DEFAULT_INTERFACE | awk '{print $4}')
GATEWAY=$(ip route | grep default | awk '{print $3}')

# Calculate IP range for Docker network
IP_BASE=$(echo $SUBNET | cut -d'/' -f1 | awk -F. '{OFS="."; print $1,$2,$3}')
IP_RANGE="${IP_BASE}.${RANGE_START}/${RANGE_LENGTH}"

# Create Docker network with IPvLAN
docker network create -d ipvlan \
    --subnet=$SUBNET \
    --ip-range=$IP_RANGE \
    --gateway=$GATEWAY \
    -o parent=$DEFAULT_INTERFACE \
    $NETWORK_NAME
