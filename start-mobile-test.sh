#!/bin/bash
# Start the app for mobile testing with ngrok HTTPS tunnel

echo "Starting Berton Bottling App for mobile testing..."
echo ""

# Start uvicorn in background
echo "Starting server on port 8001..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 &
SERVER_PID=$!

# Wait for server to start
sleep 3

# Start ngrok
echo ""
echo "Starting ngrok tunnel..."
echo "Look for the 'Forwarding' URL below - use the https:// one on your phone"
echo ""
ngrok http 8001

# Cleanup on exit
kill $SERVER_PID 2>/dev/null
