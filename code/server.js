const WebSocketServer = require('ws').Server;
const { SerialPort } = require('serialport');

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

// Read from USB serial device
// const port = new SerialPort({ path: '/dev/ttyUSB0', baudRate: 9600 }); // For Raspberry Pi
const port = new SerialPort({ path: 'COM5', baudRate: 9600 }); // For Windows

port.on('data', (data) => {
    console.log(data.toString());
    if (clientSocket) {
        clientSocket.send(data.toString());
    }
});

port.on('error', (err) => {
    console.error('Serial port error:', err);
});