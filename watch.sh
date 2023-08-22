#!/bin/sh

# Check if argument is provided
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <url_to_stream>"
    exit 1
fi

# Create torrc with HTTPTunnelPort setting
echo "HTTPTunnelPort 9080" > /tmp/torrc

# Start tor with the custom config in the background
tor -f /tmp/torrc &

# Wait a little for tor to fully start up
sleep 10

# Use ffplay to play the stream through the Tor network
http_proxy=http://localhost:9080 ffplay "$1"

# Kill the background tor process
pkill -f "tor -f /tmp/torrc"

# Remove the temporary torrc
rm /tmp/torrc
