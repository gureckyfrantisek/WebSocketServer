const WebSocketServer = require('ws').Server;
const { SerialPort } = require('serialport');
const wifiControl = require('wifi-control');
const os = require('os');
const dgram = require('dgram');
const fs = require('fs');
const { execSync } = require('child_process');

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

function startUdpServer(port, serialPath, baudRate) {
    const { localIp, broadcastIp } = getIps();
    const server = dgram.createSocket('udp4');
    const client = dgram.createSocket('udp4');
    
    let serialPort = new SerialPort({ path: serialPath, baudRate });
    
    server.on('message', (msg, rinfo) => {
        if (rinfo.address === localIp) {
            return;
        }
        console.log(`Received from ${rinfo.address}:${rinfo.port} - ${msg}`);
        if (serialPort.isOpen) {
            serialPort.write(msg);
        }
    });
    
    server.bind(port, () => {
        console.log(`UDP server listening on ${localIp}:${port}`);
    });

    client.bind(port, () => {
        client.setBroadcast(true);
    });
    
    serialPort.on('data', (data) => {
        console.log('Serial Data:', data.toString());
        client.send(data, 0, data.length, port, broadcastIp);
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
                monitorWifi(hotspotName, hotspotPassword);
            }
        });
    }

    attemptConnection();
}

function monitorWifi(hotspotName, hotspotPassword) {
    setInterval(() => {
        wifiControl.getIfaceState((error, state) => {
            if (error || state.connection === 'disconnected') {
                console.log('Lost WiFi connection, retrying...');
                connectToHotspot(hotspotName, hotspotPassword, () => {});
            }
        });
    }, 10000);
}

function main () {
    const path = '/dev/serial0' // /dev/serial0 for Raspberry Pi GPIO pins / 'COM5' for Windows
    const baudRate = 115200;
    const hotspotName = 'test';
    const hotspotPassword = 'testtest';
    const udpPort = 41234;

    connectToHotspot(hotspotName, hotspotPassword, (connected) => {
        if (connected) {
            console.log('Connected to hotspot, starting UDP server...');
            startUdpServer(udpPort, pathath, baudRate);
        }
    });

}

main();
