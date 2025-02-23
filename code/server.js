const WebSocketServer = require('ws').Server;
const { SerialPort } = require('serialport');
const wifiControl = require('wifi-control');

function startWebSocketServer(port, onClientConnected) {
    const wss = new WebSocketServer({ port });
    console.log(`Server is running on port ${port}`);

    wss.on('connection', function connection(ws) {
        // A client has connected
        console.log('connected');

        // Pass the connected socket to the callback
        onClientConnected(ws);
        
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
}

function startSerialPort (path, baudRate, clientSocket){
    // Read from USB serial device
    const port = new SerialPort({ path: path, baudRate: baudRate });

    port.on('data', (data) => {
        console.log(data.toString());
        if (clientSocket) {
            clientSocket.send(data.toString());
        }
    });

    port.on('error', (err) => {
        console.error('Serial port error:', err);
    });
}

function connectToHotspot (hotspotName, hotspotPassword, callback) {
    // Initialize with default settings
    wifiControl.init({ debug: true });

    wifiControl.scanForWiFi((error, response) => {
        if (error) console.log(error);
        else console.log(response.networks);
    });

    // Connect to a Wi-Fi network
    const ap = { ssid: hotspotName, password: hotspotPassword };
    wifiControl.connectToAP(ap, (error, response) => {
        if (error) {
            console.log('Connection error:', error);
        } else {
            console.log('Connected to WiFi:', response);
            callback(true);
        }
    });
}

function main () {
    const path = 'COM5' // /dev/ttyUSB0 for Raspberry Pi
    const baudRate = 9600;
    let clientSocket = null;
    const hotspotName = 'test';
    const hotspotPassword = 'testtest';

    connectToHotspot(hotspotName, hotspotPassword, (connected) => {
        if (connected) {
            console.log('Connected to hotspot');
            startWebSocketServer(8080, (ws) => {
                console.log('Client connected, starting serial port...');
                clientSocket = ws;
                startSerialPort(path, baudRate, clientSocket);
            });

        }
    });

}

main();