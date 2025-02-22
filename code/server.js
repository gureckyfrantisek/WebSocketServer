const WebSocketServer = require('ws').Server;

const wss = new WebSocketServer({ port: 8080 });
console.log('Server is running on port 8080');

let clientSocket = null;

wss.on('connection', function connection(ws) {
    // A client has connected
    console.log('connected');
    clientSocket = ws;
    
    // Declare actions for the server
    ws.on('error', console.error);
    
    ws.on('message', function message(data) {
        console.log('Server received: %s', data);
    });

    ws.on('close', function close() {
        console.log('disconnected');
        clientSocket = null;
    });

    ws.send('Hello from server to client');
});

// Read from stdin and send to the connected client
process.stdin.on('data', function(data) {
    if (clientSocket) {
        clientSocket.send(data.toString().trim());
    }
});