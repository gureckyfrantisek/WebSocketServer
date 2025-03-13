const dgram = require('dgram');
const WebSocket = require('ws');
const os = require('os');

// Create a UDP socket
const udpClient = dgram.createSocket('udp4');

udpClient.on('listening', () => {
    const address = udpClient.address();
    console.log(`UDP listening ${address.address}:${address.port}`);
});

// Listen for responses from servers
udpClient.on('message', (message, rinfo) => {
    console.log(`Received UDP message: ${message} from ${rinfo.address}`);

    // Use the received IP to connect to WebSocket
    const wsUrl = `ws://${message}:8080`;
    connectToWebSocket(wsUrl);
});

// Function to connect to the WebSocket server
function connectToWebSocket(serverUrl) {
    const ws = new WebSocket(serverUrl);

    ws.on('open', () => {
        console.log('Connected to WebSocket server');
        ws.send('Hello from client to server');
    });

    ws.on('message', (data) => {
        console.log('Client received:', data.toString());
    });

    ws.on('close', () => {
        console.log('Disconnected from WebSocket server');
    });

    ws.on('error', (error) => {
        console.error('WebSocket error:', error);
    });
}

// Bind to port 41234
udpClient.bind(41234);