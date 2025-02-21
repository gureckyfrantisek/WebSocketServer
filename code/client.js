const WebSocket = require('ws');

const ws = new WebSocket('ws://localhost:8080');

ws.on('error', console.error);

ws.on('open', function open() {
    ws.send('Hello from client to server');
});

ws.on('message', function message(data) {
    console.log('Client received: %s', data);
});

ws.on('close', function close() {
    console.log('disconnected');
});