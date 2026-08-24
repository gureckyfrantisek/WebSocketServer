# WebSocket server pro přenos NMEA zpráv

Vedlejší projekt pro K155GNSSApp.
Kód pro server pro přenos dat.

Odkaz na hlavní repositář: https://github.com/DilnaC004/K155GNSSapp

Server se přepisuje z Node.js do Pythonu (FastAPI), aby k přenosu dat šlo přidat
i REST rozhraní pro statická měření a ukládání surových UBX dat na flash disk.
Původní Node.js verze zůstává ve složce `code` jako reference, dokud nebude
Python verze odzkoušená na Raspberry Pi.

## Python server (FastAPI)

### Struktura

```
app/
  main.py            spuštění aplikace a registrace routerů
  core/              logika - sériový port, discovery, WiFi, měření
  routers/           HTTP a WebSocket endpointy
```

Nastavení se čte z proměnných prostředí, výchozí hodnoty jsou v `.env.example`.
Pro lokální běh stačí soubor zkopírovat na `.env` a upravit.

### Instalace

Potřeba je Python 3.

```bash
python3 -m venv .venv
source .venv/bin/activate      # na Windows: .venv/Scripts/activate
pip install -r requirements.txt
```

Pokud pip hlásí `CERTIFICATE_VERIFY_FAILED` (firemní síť), přidat:

```bash
pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

### Spuštění

```bash
python -m app
```

Na Raspberry Pi je pro přístup k sériovému portu potřeba sudo:

```bash
sudo .venv/bin/python -m app
```

Server poslouchá na `0.0.0.0` a na portu z proměnné `SERVER_PORT`. Samotné
`uvicorn app.main:app` se pro běžný provoz nehodí, protože se bez parametrů
naváže jen na `127.0.0.1` a telefon se pak nemá kam připojit, i když ho
discovery navádí na správnou adresu.

Dokumentace endpointů se generuje sama na `http://<ip>:8080/docs`.

### Vývoj bez přijímače

Proměnná `GNSS_SIMULATE=1` nahradí sériový port generátorem platných NMEA vět
(jedna dvojice GGA a RMC za sekundu). Díky tomu jde všechno otestovat na PC bez
připojeného uBloxu.

Nejjednodušší je nastavit ji v souboru `.env`, pak se server spouští normálně.
Přes proměnnou prostředí se to liší podle shellu:

```bash
# bash
GNSS_SIMULATE=1 uvicorn app.main:app --port 8080
```

```powershell
# PowerShell - nemá zápis proměnné před příkazem
$env:GNSS_SIMULATE = "1"
uvicorn app.main:app --port 8080
```

### Testovací klient

Místo aplikace jde použít jednoduchý klient v `tools/ws_client.py`. Vypisuje
přijaté NMEA věty a co se do něj napíše, pošle jako korekci do přijímače.

```bash
python tools/ws_client.py                 # ws://127.0.0.1:8080
python tools/ws_client.py 192.168.1.42     # server na Raspberry Pi
```

### Chování WebSocketu

- Endpoint je na kořeni (`ws://<ip>:8080`), aplikace se tedy nemusí měnit.
  Stejný most běží i na `/ws`, což se hodí při testování.
- Nahoru jdou celé NMEA věty jako textové rámce. Binární UBX data se do
  WebSocketu neposílají, ta se ukládají až při statickém měření.
- Dolů jdou korekce, textové i binární rámce se zapisují rovnou do přijímače.
- Připojený smí být jen jeden klient. Druhý dostane při handshaku HTTP 403.
- Uvicorn sám posílá ping rámce, takže tiše odpojený klient uvolní slot
  i bez korektního zavření spojení.

### Nastavení zpráv přijímače

Přijímač si drží vlastní nastavení, co a jak často posílá. Po resetu nebo po
výměně kusu se tedy může tiše změnit, co do serveru přichází. Proto se dají
rychlosti zpráv nastavit v `.env` a server je pošle vždy, když otevře port.

```
UBX_MESSAGE_RATES=NMEA-GGA:1,NMEA-RMC:1,NMEA-GSV:0,RXM-RAWX:1,RXM-SFRBX:1
UBX_GENERATION=gen9
UBX_PORT=UART1
```

Číslo za dvojtečkou je perioda v počtu navigačních řešení, nula zprávu vypne.
Prázdná hodnota znamená, že se nastavení přijímače nechá být.

`UBX_GENERATION` rozlišuje protokol. ZED-F9P je `gen9` a nastavuje se přes
CFG-VALSET, starší u-blox 8 je `gen8` a používá CFG-MSG. `UBX_PORT` říká, ze
kterého portu přijímače mají zprávy chodit, přes GPIO piny je to `UART1`.

Server po každém příkazu čeká na potvrzení od přijímače. Co přijímač potvrdil
a co odmítl, je vidět v odpovědi `POST /gnss/messages/apply`, takže špatné
nastavení nezůstane bez povšimnutí.

`UBX_SAVE_TO_FLASH=1` uloží nastavení i do flash přijímače, přežije pak reset.

Pro statické zpracování jsou potřeba `RXM-RAWX` a `RXM-SFRBX`, tedy fázová
měření. ZED-F9P je umí, běžná M8N ne.

### NMEA a UBX naráz

Přijímač posílá NMEA věty i binární UBX zprávy jedním portem, promíchané za
sebou. Server je rozdělí sám:

- do WebSocketu jdou jen celé NMEA věty jako text
- do souboru `.ubx` při statickém měření jde celý tok bez úprav, tedy i UBX

Není tedy potřeba nic přepínat, obojí může běžet současně.

### Statické měření

Statické měření zapisuje surový tok z přijímače na disk, tedy i binární UBX
zprávy, aby se dal záznam později zpracovat. Běží nezávisle na WebSocketu,
takže aplikace může dál dostávat NMEA i během měření.

```
POST /static/start?point_id=B1    spustí zápis bodu B1
POST /static/stop                 ukončí zápis
GET  /static/status               stav a počet zapsaných bajtů
```

Kromě `point_id` přijímá start ještě tři nepovinné parametry, které vyplňuje
měřič v aplikaci:

```
POST /static/start?point_id=1&antenna_height=1.85&antenna_offset=0.042&code=roh
```

- `antenna_height` je výška antény nad měřeným bodem v metrech
- `antenna_offset` je posun fázového centra antény v metrech, vlastnost
  konkrétního kusu hardwaru
- `code` je volný kód bodu, třeba `roh` nebo `sloup`, diakritika je v pořádku

Obě čísla se dají zadat s desetinnou čárkou i tečkou, protože česká klávesnice
nabízí čárku. Nečíselná hodnota vrátí `400 {"status": "unusable antenna height"}`
a měření se vůbec nespustí. Vynechaný parametr není chyba, server běží dál i s
klientem, který posílá jen `point_id`.

Výška a posun se schválně ukládají zvlášť a nesčítají se. Při zpracování se
z jejich součtu skládá svislá složka hlavičky `ANTENNA: DELTA H/E/N` v RINEXu a
`code` se hodí do `MARKER NAME`, ale ten, kdo data zpracovává, má takhle vidět
obě části zvlášť.

Jeden bod je jedna dvojice souborů v `LOCAL_DATA_PATH`:

- `B1.ubx` je surový tok bajt po bajtu, jak přišel z přijímače
- `B1.json` obsahuje časy začátku a konce, délku, nastavení portu a údaje
  o anténě

Do `.ubx` se nikdy nic nepřidává, musí zůstat přesnou kopií toho, co poslal
přijímač, jinak by ho nástroje pro zpracování nepřečetly. Všechno ostatní patří
do `.json`:

```json
{
  "point_id": "1",
  "antenna_height": 1.85,
  "antenna_offset": 0.042,
  "code": "roh",
  "file_name": "1",
  "location": "usb",
  "start_ns": 1787498406808436100,
  "end_ns": 1787498407426368100,
  "duration_s": 61.4,
  "bytes_written": 812340,
  "raw_file": "1.ubx"
}
```

Když měřič pole nevyplní, zapíše se `null`, klíč ale ve výsledku zůstane, aby
se na tvar souboru dalo při zpracování spolehnout. Stejné tři údaje vrací i
`GET /static/status` a odpověď na `POST /static/stop`, takže aplikace umí
ukázat, s čím bylo běžící měření spuštěné, i když se připojí až po restartu.

Když se stejný bod měří znovu, starší záznam zůstává a k novému se přidá
číslo: `B1.ubx`, `B1_1.ubx`, `B1_2.ubx` a tak dál. Žádné měření se nepřepíše.

Název souboru vychází z `point_id`. Diakritika se převádí na ASCII, mezery a
ostatní znaky na podtržítko, takže z `Bod č. 12` je `Bod_c._12.ubx`.

```
GET    /points                          seznam bodů
GET    /points/{bod}                     soubory jednoho bodu
DELETE /points/{bod}                     smazání
POST   /points/{bod}/download            kopie na flash disk
POST   /points/{bod}/download?cleanup=true   kopie a smazání lokální kopie
```

Když je zapojený flash disk, zapisuje se rovnou na něj, do podsložky `gnss`.
Data pak odejdou i s diskem a nic se nemusí přesouvat. Bez disku se měření
uloží do `LOCAL_DATA_PATH` a dá se na disk zkopírovat později.

Kde měření skončí, říká `GET /storage/status`, položka `writing_to`. Ta samá
odpověď obsahuje i volné místo na obou úložištích.

```
GET  /storage/status                 kam se zapisuje a kolik zbývá místa
POST /storage/download-all           přesun všech lokálních měření na disk
POST /storage/download-all?cleanup=true
```

Flash disk se hledá v `BASE_USB_PATH`, na Raspberry Pi to bývá `/media/pi`.
Bere se jen skutečně připojené zařízení. Prázdná složka, která po disku někdy
zůstane, se přeskočí, aby se místo na disk nezapisovalo na SD kartu.

`LOCAL_DATA_PATH` záměrně není v `/tmp`, systemd tuto složku maže. Výchozí
hodnota `data` je relativní ke složce aplikace.

Chování jde otočit přes `PREFER_USB=0`, pak se zapisuje vždy lokálně.

Soubor se průběžně ukládá jednou za pět sekund, výpadek napájení tedy může
přijít nanejvýš o posledních pět sekund záznamu.

### Jak telefon najde Pi

Samotné vysílání adresy po síti tenhle problém vyřešit nemůže: aby Pi mohlo
svoji adresu oznámit, musí už být na hotspotu telefonu, jenže na ten se bez
přihlašovacích údajů nepřipojí. Bluetooth to rozetne, protože údaje přenese
mimo síť.

Průběh:

1. Telefon se jednou spáruje s Pi přes systémové nastavení Bluetooth.
2. Aplikace po spuštění otevře sériové spojení (Serial Port Profile).
3. Pošle jméno a heslo hotspotu.
4. Pi se na hotspot připojí a odpoví svojí adresou.
5. Aplikace se na tu adresu připojí WebSocketem, dál už je vše stejné.

Zprávy jsou jednořádkový JSON, jeden dotaz a jedna odpověď na řádek:

```json
{"command":"hello"}
{"command":"status","token":"..."}
{"command":"connect_wifi","ssid":"hotspot","password":"heslo","token":"..."}
```

Odpověď při úspěchu:

```json
{"status":"ok","ip":"192.168.43.42","ssid":"hotspot","server_port":8080,
 "ws_url":"ws://192.168.43.42:8080/","api_url":"http://192.168.43.42:8080"}
```

Nastavení na Raspberry Pi, stačí jednou:

```bash
sudo bash deploy/bluetooth_setup.sh K155GNSS
```

Druhým parametrem se dá vyžádat PIN při párování, třeba
`deploy/bluetooth_setup.sh K155GNSS 483920`. Bez něj se telefon spáruje bez
ptaní, což je pohodlné, ale spárovat se může kdokoliv v dosahu.

Třetím parametrem se dá změnit RFCOMM kanál, ve výchozím stavu 1. Musí
odpovídat `BLUETOOTH_CHANNEL` v `.env`, `deploy/install.sh` ho předává sám.

Skript pojmenuje adaptér, nastaví párování a hlavně zveřejní záznam Serial Port
Profile. Bez něj telefon nemá jak zjistit, na který kanál se připojit. To
vyžaduje `bluetoothd` v režimu kompatibility, což skript zařídí přes override
systemd jednotky.

Záznam Serial Port Profile žije jen v běžícím `bluetoothd`, takže ho restart
Raspberry Pi i restart služby `bluetooth` smaže. Telefon pak hlásí neúspěšné
spojení, přestože server na Pi normálně poslouchá. Proto skript instaluje
jednotku `sdp-spp.service`, která je svázaná s `bluetooth.service` a záznam
zveřejní pokaždé znovu. Server ho navíc při startu zveřejní také, pokud chybí,
a adaptér při každém startu znovu zapne, pojmenuje a zviditelní.

Kontrola po restartu:

```bash
systemctl status sdp-spp
sudo sdptool browse local | grep -A2 "Serial Port"
```

Bluetooth se nedá vypnout, telefon nemá jinou cestu k Pi. V `.env` se nastavuje
jen jméno, kanál a token:

```
BLUETOOTH_NAME=K155GNSS
BLUETOOTH_CHANNEL=1
BLUETOOTH_TOKEN=
```

Jméno se bere z `.env`, server ho při startu nastaví adaptéru sám, takže je na
jednom místě. Adresu adaptéru a jméno vrací `GET /bluetooth/status`, ručně se
dá spustit a zastavit přes `POST /bluetooth/start` a `/bluetooth/stop`.

Párování samo o sobě jen dokazuje, že se telefon někdy spároval. Nezabrání
spárovanému zařízení přesměrovat Pi na jinou síť. Od toho je `BLUETOOTH_TOKEN`,
který se kontroluje u každého požadavku. Vygeneruje se třeba přes
`openssl rand -hex 16`.

### Přihlašovací údaje k WiFi

V konfiguraci projektu žádné nejsou a být nemají. Hotspot přijde přes Bluetooth
a NetworkManager si profil uloží, takže se Pi příště připojí samo, i když
server neběží.

To znamená, že po prvním připojení k domácí síti nebo k hotspotu zůstává
zařízení dostupné i bez aplikace, což se hodí pro SSH. Profily se dají
zkontrolovat přes `nmcli connection show`.

```
GET  /wifi/status              na jaké síti Pi je
POST /wifi/connect?ssid=...    připojení k síti, kterou už NetworkManager zná
```

## Nasazení na Raspberry Pi

Server běží jako služba pod systemd, ne v Dockeru. Sériový port, připojování
flash disku a ovládání NetworkManageru jsou věci, které se z kontejneru dělají
špatně, a jde o jednu aplikaci na jednom stroji.

### Předpoklady

Sériový port na Raspberry Pi je ve výchozím stavu obsazený přihlašovací
konzolí, se kterou by se přijímač o port přetahoval:

```bash
sudo raspi-config
```

Interface Options → Serial Port → přihlašovací shell **ne** → hardware serial
**ano**, pak restart. Potom `/dev/serial0` patří přijímači.

#### Který UART komu

Raspberry Pi 4 má dva použitelné UARTy a Bluetooth jeden z nich potřebuje —
rádio BCM4345C0 je k UARTu připojené natvrdo, HCI nejde po USB. Kvalitní PL011
(`ttyAMA0`) má vlastní hodiny a drží libovolnou rychlost. Mini UART (`ttyS0`)
odvozuje přenosovou rychlost od frekvence jádra GPU, takže když ta škáluje,
rychlost ujede a bajty se rozsypou.

Ve výchozím stavu, **bez jakéhokoliv overlaye**, dostane PL011 Bluetooth a
GPIO piny 14/15 dostanou mini UART. Tak to nechte:

```
enable_uart=1
core_freq=500
```

`dtoverlay=miniuart-bt` (ani starší název `pi3-miniuart-bt`) sem **nepatří**.
Ten overlay UARTy prohodí a přijímač dostane PL011 na úkor Bluetooth. Zní to
lákavě, ale rádio mini UART nesnese: `hciuart` buď spadne na
`btuart: Initialization timed out`, nebo se připojí a pak selže inicializace
řadiče na `hci0: command 0x1003 tx timeout` a adaptér zůstane `DOWN`.
`bluetoothctl list` nevypíše nic a telefon nemá jak Pi najít. Přijímač mini
UART naopak snese bez problémů.

`core_freq=500` tam být musí a fixuje frekvenci jádra shora i zdola —
`core_freq_min` drží jen spodní hranici, a s `arm_boost=1` se strop stejně
hýbe. Na Pi 3 se použije `core_freq=250`.

Kontrola po restartu:

```bash
hciconfig -a | head -4
bluetoothctl list
ls -l /dev/serial0
curl -s localhost:8080/gnss/status
```

`hci0` musí být `UP RUNNING`, `bluetoothctl list` musí vypsat jeden Controller,
`/dev/serial0` bude ukazovat na `ttyS0` a `bytes_read` ve stavu musí růst.

Když se přijímač na mini UARTu chová nespolehlivě — rozsypané NMEA nebo
`bytes_read` na nule — je řešení USB převodník a `SERIAL_PATH=/dev/ttyACM0`.
Tím se PL011 uvolní úplně a o UART se nikdo nepere.

### Instalace

```bash
git clone https://github.com/gureckyfrantisek/WebSocketServer /home/pi/WebSocketServer
cd /home/pi/WebSocketServer
sudo bash deploy/install.sh
```

Skript vytvoří venv, nainstaluje závislosti, připraví Bluetooth, zapíše službu
do systemd, povolí ji při startu a spustí ji. Dá se pouštět opakovaně, třeba po
`git pull`, existující `.env` nechá být.

Bluetooth krok je součástí instalace schválně a nedá se přeskočit. Telefon nemá
jinou cestu, jak Pi najít, takže server bez připraveného Bluetooth je server,
ke kterému se nikdo nepřipojí.

Pokud má párování vyžadovat PIN, spustí se příprava Bluetooth zvlášť:

```bash
sudo bash deploy/bluetooth_setup.sh K155GNSS 483920
```

Před prvním ostrým během je potřeba projít `.env`, hlavně `SERIAL_PATH` a
`SERIAL_BAUDRATE`. Přihlašovací údaje k WiFi se nikam nepíšou, ty přijdou z
telefonu přes Bluetooth.

### Provoz

```bash
systemctl status k155-gnss      # stav
journalctl -u k155-gnss -f      # živý log
systemctl restart k155-gnss     # restart po změně .env
```

Kontrola, že se server chytil:

```bash
curl -s localhost:8080/status | python3 -m json.tool
curl -s localhost:8080/bluetooth/status | python3 -m json.tool
```

V odpovědi Bluetooth mají být `powered`, `discoverable` i `serial_profile` na
`true`. Když je `powered` na `false`, bývá adaptér blokovaný přes rfkill:

```bash
rfkill list
sudo rfkill unblock bluetooth
```

Služba se sama restartuje po pádu i po čistém ukončení, s pěti sekundami mezi
pokusy. Nahrazuje to řádek `@reboot ... &` v crontabu.

Pro čtení sériového portu potřebuje služba práva, proto běží pod rootem.
Alternativou je přidat uživatele do skupiny `dialout` a `User=pi` v souboru
`deploy/k155-gnss.service`.

## Legacy Node.js server

Ve složce code je k nalezení kód pro server a pro ukázkového klienta.
V historii repositáře existuje verze pro uzavřené testování komunikace, momentálně je zdejší server kompatibilní s aplikací, ne tímto klientem.

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
6. Pro jistotu povolit UDP firewallem: sudo ufw allow 41234/udp
7. Restartovat a vše by mělo v pořádku proběhnout :D

Nejrychlejší je naklonovat již funkční Raspsberry image místo instalace.

Nezapomenout nastavit na každém zařízení jiný hotspot, aby se přijímače nepřipojovali na jeden.
