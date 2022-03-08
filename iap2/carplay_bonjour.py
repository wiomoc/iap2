import dbus
import avahi


def start_service(device_id):
    bus = dbus.SystemBus()
    server = dbus.Interface(bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER), avahi.DBUS_INTERFACE_SERVER)

    group = dbus.Interface(bus.get_object(avahi.DBUS_NAME, server.EntryGroupNew()),
                           avahi.DBUS_INTERFACE_ENTRY_GROUP)

    group.AddService(avahi.IF_UNSPEC, avahi.PROTO_INET, 0, "raspberrypi", "_airplay._tcp", '', '', 7000,
                     avahi.string_array_to_txt_array([
                         f"deviceID={device_id}",
                         "features=0x44540380,0x21",
                         "model=raspberrypi",
                         "srcvers=280.33.8",
                         "flags=0x4"]))
    group.Commit()

    def on_service(interface, protocol, name, type, domain, flags):
        try:
            interface, protocol, name, type, domain, host, aprotocol, address, port, txt, flags = server.ResolveService(
                interface, protocol, name, type, domain, avahi.PROTO_INET, 0)
            print(txt)
            txt = [''.join((str(t) for t in txt_entry)) for txt_entry in txt]
            print(host, port, txt)

            mac_int = int(device_id.replace(":",""), 16)
            from urllib import request
            ip = "192.168.2.10"
            req = request.Request(f"http://{host}:{port}/ctrl-int/1/connect", headers={
                "Host": host,
                "User-Agent": "AirPlay/280.33.8",
                "AirPlay-Receiver-Device-ID": str(mac_int),
            })
            print(request.urlopen(req).read())
        except:
            pass

    browser = server.ServiceBrowserNew(avahi.IF_UNSPEC, avahi.PROTO_INET, '_carplay-ctrl._tcp', 'local', 0)
    bus.add_signal_receiver(on_service, "ItemNew", path=browser)

