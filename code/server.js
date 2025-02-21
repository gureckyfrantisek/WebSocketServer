const WebSocketServer = require('ws').Server;

const wss = new WebSocketServer({ port: 8080 });
console.log('Server is running on port 8080');

wss.on('connection', function connection(ws) {
    // A client has connected
    console.log('connected');

    // Declare actions for the server
    ws.on('error', console.error);
    
    ws.on('message', function message(data) {
        console.log('Server received: %s', data);
    });

    ws.on('close', function close() {
        console.log('disconnected');
    });

    ws.send('Hello from server to client');
});