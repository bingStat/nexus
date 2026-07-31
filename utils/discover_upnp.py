import socket
import struct
import urllib.request
import xml.etree.ElementTree as ET

def discover_upnp():
    msg = \
        'M-SEARCH * HTTP/1.1\r\n' \
        'HOST:239.255.255.250:1900\r\n' \
        'ST:urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n' \
        'MX:2\r\n' \
        'MAN:"ssdp:discover"\r\n' \
        '\r\n'

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(3)
    s.sendto(msg.encode('utf-8'), ('239.255.255.250', 1900) )

    devices = []
    try:
        while True:
            data, addr = s.recvfrom(65507)
            response = data.decode('utf-8')
            for line in response.split('\r\n'):
                if line.lower().startswith('location:'):
                    url = line.split(':', 1)[1].strip()
                    devices.append((addr[0], url))
    except socket.timeout:
        pass

    return list(set(devices))

print("Discovering UPnP Internet Gateway Devices...")
devices = discover_upnp()
if not devices:
    print("No UPnP IGD devices found on the current network.")
else:
    for ip, url in devices:
        print(f"Found UPnP Device at {ip}")
        print(f"Location: {url}")
