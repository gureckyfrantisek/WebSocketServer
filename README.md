# WebSocket server pro přenos NMEA zpráv

Vedlejší projekt pro K155GNSSApp.
Kód pro server pro přenos dat.

Odkaz na hlavní repositář: https://github.com/DilnaC004/K155GNSSapp

Pro nastavení na Raspberry Pi je třeba:
1. Nainstalovat Node.js viz.: https://www.w3schools.com/nodejs/nodejs_raspberrypi.asp
2. Nainstalovat network-manager: sudo apt install network-manager
3. Zjistit port uBloxu (zdroj: https://askubuntu.com/questions/398941/find-which-tty-device-connected-over-usb): 
    1. Bez zapojení spustit ls /dev/ > dev_list_1.txt
    2. Zapojit a spustit ls /dev/ | diff --suppress-common-lines -y - dev_list_1.txt
    3. Nastavit podle toho proměnnou path v mainu server.js
4. Přetáhnout soubory server.js a node_modules na plochu do složky GNSSApp
5. Nastavit automatické spouštění:
    1. Spustit sudo crontab -e
    2. Vespod nastavit @reboot node /home/pi/Desktop/GNSSApp/server.js &
6. Restartovat a vše by mělo v pořádku proběhnout :D

Nezapomenout nastavit na každém zařízení jiný hotspot, aby se přijímače nepřipojovali na jeden.