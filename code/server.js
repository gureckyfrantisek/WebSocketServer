const WebSocketServer = require('ws').Server;
const { SerialPort } = require('serialport');
const wifiControl = require('wifi-control');

function startWebSocketServer(port, onClientConnected) {
    const wss = new WebSocketServer({ port, host: '0.0.0.0' });
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
            if (global.serialPort && global.serialPort.isOpen) {
                global.serialPort.close((err) => {
                    if (err) console.error('Error closing serial port:', err);
                    else console.log('Serial port closed');
                });
            }
        });

        // ws.send('Hello from server to client');  // Commented to not spam the client
    });
}

function startSerialPort (path, baudRate, clientSocket){
    // Read from USB serial device
    global.serialPort = new SerialPort({ path: path, baudRate: baudRate });

    global.serialPort.on('data', (data) => {
        console.log(data.toString());
        if (clientSocket) {
            clientSocket.send(data.toString());
        }
    });

    global.serialPort.on('error', (err) => {
        console.error('Serial port error:', err);
    });
}

function connectToHotspot (hotspotName, hotspotPassword, callback) {
    // Initialize with default settings
    wifiControl.init({ debug: true });

    function attemptConnection() {
        console.log(`Attempting to connect to ${hotspotName}...`);
        const ap = { ssid: hotspotName, password: hotspotPassword };

        wifiControl.connectToAP(ap, (error, response) => {
            if (error) {
                console.log('Connection error:', error);
                setTimeout(attemptConnection, 5000); // Retry after delay
            } else {
                console.log('Connected to WiFi:', response);
                callback(true);
                monitorWifi(hotspotName);
            }
        });
    }

    attemptConnection();
}

function monitorWifi(hotspotName) {
    setInterval(() => {
        wifiControl.getIfaceState((error, state) => {
            if (error || state.connection === 'disconnected') {
                console.log('Lost WiFi connection, retrying...');
                connectToHotspot(hotspotName, 'testtest', () => {});
            }
        });
    }, 10000);
}

function main () {
    const path = 'COM5' // /dev/ttyUSB0 for Raspberry Pi
    const baudRate = 9600;
    const hotspotName = 'test';
    const hotspotPassword = 'testtest';

    connectToHotspot(hotspotName, hotspotPassword, (connected) => {
        if (connected) {
            // Allow the firewall and display the IP address
            console.log('Connected to hotspot');
            startWebSocketServer(8080, (ws) => {
                console.log('Client connected, starting serial port...');
                startSerialPort(path, baudRate, ws);
            });
        }
    });

}

main();