const WebSocketServer = require('ws').Server;
const { SerialPort } = require('serialport');
const wifiControl = require('wifi-control');
const os = require('os');
const dgram = require('dgram');

function getBroadcastIp(ip, netmask) {
    // Convert the IP address and netmask to binary strings
    const ipParts = ip.split('.').map(Number);
    const netmaskParts = netmask.split('.').map(Number);
    
    // Convert each part of the IP and netmask to 8-bit binary strings
    const ipBinary = ipParts.map(part => part.toString(2).padStart(8, '0')).join('');
    const netmaskBinary = netmaskParts.map(part => part.toString(2).padStart(8, '0')).join('');
    
    // Calculate the inverse of the netmask (inversion means 1s become 0s and 0s become 1s)
    const inverseNetmaskBinary = netmaskBinary.split('').map(bit => bit === '1' ? '0' : '1').join('');
    
    // Calculate the broadcast binary address by performing a bitwise OR between the IP and inverse netmask
    const broadcastBinary = ipBinary.split('')
        .map((bit, index) => bit === '1' || inverseNetmaskBinary[index] === '1' ? '1' : '0')
        .join('');
    
    // Split the broadcast binary string into 4 octets (each 8 bits long)
    const broadcastParts = [];
    for (let i = 0; i < 4; i++) {
        broadcastParts.push(parseInt(broadcastBinary.slice(i * 8, i * 8 + 8), 2));
    }
    
    // Return the broadcast address as a string
    return broadcastParts.join('.');
}

function getIps() {
    const interfaces = os.networkInterfaces();
    const localIp = interfaces.wlan0[0].address;
    const localMask = interfaces.wlan0[0].netmask;
    
    console.log('Local IP and mask: ', localIp, ' mask: ', localMask);
    
    const broadcastIp = getBroadcastIp(localIp, localMask);
    console.log('Broadcast IP: ', broadcastIp);
    
    return {localIp, broadcastIp};
}

function startUdpBroadcast(client, ip, port, broadcastIp) {
    client.bind(() => {
        client.setBroadcast(true); // Enable broadcast
    });
    
    console.log('Ip in UDP broadcast: ', ip);

    const broadcastInterval = setInterval(() => {
        if (client) {
            const message = ip.toString(); // Ensure ip is a string
            client.send(message, 0, message.length, port, broadcastIp, (err) => {
                if (err) {
                    console.error('Error broadcasting UDP message:', err);
                } else {
                    console.log(`Broadcasting server IP: ${message} to ${broadcastIp}:${port}`);
                }
            });
        }
    }, 1000);

    return broadcastInterval;
}

function startWebSocketServer(port, onClientConnected) {
    const {localIp, broadcastIp} = getIps();
    // Start UDP broadcast and end it, after a client has connected
    console.log('piIp in start WSS: ', localIp);
    
    let client = dgram.createSocket('udp4');
    let udpInterval = startUdpBroadcast(client, localIp, 41234, broadcastIp);
    
    const wss = new WebSocketServer({ port, host: '0.0.0.0' });
    console.log(`Server is running on port ${port}`);
    
    wss.on('connection', function connection(ws) {
        // A client has connected
        console.log('connected');
        
        // Close UDP broadcast after connection
        try {
            client.close();
            clearInterval(udpInterval);
        } catch (e) {
            console.log('No client to close');
        }
        
        // Pass the connected socket to the callback
        onClientConnected(ws);
        
        // Declare actions for the server
        ws.on('error', console.error);
        
        ws.on('message', function message(data) {
            console.log('Server received: %s', data);
            if (global.serialPort && global.serialPort.isOpen) {
                global.serialPort.write(data);
            }
        });

        ws.on('close', function close() {
            console.log('disconnected');
            if (global.serialPort && global.serialPort.isOpen) {
                global.serialPort.close((err) => {
                    if (err) console.error('Error closing serial port:', err);
                    else console.log('Serial port closed');
                });
            }
            try {
                client = dgram.createSocket('udp4');
                udpInterval = startUdpBroadcast(client, localIp, 41234, broadcastIp);
            } catch(e) {
                console.log('Cannot open client');
            }
        });

        // ws.send('Hello from server to client');  // Commented to not spam the client
    });
}

function startSerialPort (path, baudRate, clientSocket){
    // Read from USB serial device
    global.serialPort = new SerialPort({ path: path, baudRate: baudRate });

    global.serialPort.on('data', (data) => {
        console.log('Serial port incoming data: ', data.toString());
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
    var settings = {
        debug: true || false,
        iface: 'wlan0',
        connectionTimeout: 10000 // in ms
    };
     
    wifiControl.init( settings );

    function attemptConnection() {
        console.log(`Attempting to connect to ${hotspotName}...`);
        const ap = { ssid: hotspotName, password: hotspotPassword };

        wifiControl.connectToAP(ap, (error, response) => {
            if (error) {
                console.log('Connection error:', error);
                setTimeout(attemptConnection, 5000); // Retry after delay
            } else {
                console.log(response.msg);
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
    const path = '/dev/serial0' // /dev/serial0 for Raspberry Pi GPIO pins / 'COM5' for Windows
    const baudRate = 115200;
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
