#!/usr/bin/env python
'''Shows the micro inverters of an OpenDTU as PV inverters on Venus OS (D-Bus).

Three small parts:
  Poller    a background thread that asks the OpenDTU every few seconds and keeps the newest answer.
            Only this thread ever waits for the network.
  Inverter  one D-Bus device per micro inverter. update() copies the newest answer to D-Bus.
  main()    reads config.ini, starts the poller and calls update() once per second from the GLib main loop.
            update() only looks at the newest answer, so the main loop is never blocked.

If there is no answer for ErrorStateAfterSeconds, the values are set to 0 until the OpenDTU answers again.

Based on https://github.com/henne49/dbus-opendtu (MIT license, see LICENSE).
'''

import configparser
import logging
import os
import platform
import sys
import threading
import time

import requests

sys.path.insert(1, "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
import dbus  # noqa: E402  pylint: disable=import-error,wrong-import-position
from dbus.mainloop.glib import DBusGMainLoop  # noqa: E402  pylint: disable=import-error,wrong-import-position
from gi.repository import GLib  # noqa: E402  pylint: disable=import-error,wrong-import-position
from vedbus import VeDbusService  # noqa: E402  pylint: disable=import-error,wrong-import-position

SERVICE = "com.victronenergy.pvinverter"
PRODUCT_NAME = "henne49_dbus-opendtu"  # unchanged, so that Venus OS still knows the devices
POLL_SECONDS = 5
PHASES = ("L1", "L2", "L3")
RUNNING, STANDBY, ERROR = 7, 8, 10  # D-Bus /StatusCode
TEXT = {"W": "{:.1f}W", "V": "{:.1f}V", "A": "{:.1f}A", "kWh": "{:.2f}KWh"}  # how the GUI shows a value


def truthy(value):
    '''OpenDTU sends booleans, older versions sent 1/"1"'''
    return value in (True, 1, "1", "true", "True")


class Poller(threading.Thread):
    '''Asks the OpenDTU in the background; .latest = (list of inverters, time.monotonic()) of the last answer'''

    def __init__(self, host, auth, timeout):
        super().__init__(daemon=True)
        self.url = f"http://{host}/api/livedata/status"
        self.auth = auth
        self.timeout = timeout
        self.latest = None  # replaced as a whole, so the main loop can read it without a lock

    def get_json(self, url):
        '''one request; raises on any problem'''
        response = requests.get(url, auth=self.auth, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fetch(self):
        '''the list of inverters as sent by the OpenDTU; raises on any problem'''
        inverters = self.get_json(self.url).get("inverters")
        if not inverters:
            raise ValueError("the OpenDTU reports no inverters")
        for inverter in inverters:
            if "serial" not in inverter:
                raise ValueError("OpenDTU too old (no serial numbers in the answer), please update it")
            if "AC" not in inverter and truthy(inverter["reachable"]):
                # OpenDTU older than v24.2.12 lists only a summary here; the values need one request per inverter.
                # Not asked for an inverter that is not reachable: it is shown as asleep anyway, and a newer OpenDTU
                # has no values for it either (nothing received since it was started, e.g. at night).
                detail = self.get_json(f"{self.url}?inv={inverter['serial']}")["inverters"][0]
                if "AC" in detail:
                    inverter.update(detail)
                    inverter["legacy"] = True  # the yield is found in "INV" instead of "AC"
        return inverters

    def run(self):
        failing = False
        while True:
            try:
                self.latest = (self.fetch(), time.monotonic())
                if failing:
                    logging.info("OpenDTU reachable again")
                    failing = False
            except Exception as error:  # pylint: disable=broad-except
                if not failing:  # log only the first failure, not every 5 seconds
                    logging.warning("OpenDTU request failed: %s", error)
                failing = True
            time.sleep(POLL_SECONDS)


class Inverter:
    '''One micro inverter on D-Bus. index = position in the OpenDTU list.'''

    def __init__(self, index, section, poller, error_after, use_yield_day):
        self.index = index
        self.phase = section["Phase"]
        if self.phase not in PHASES:
            raise ValueError(f"config.ini [INVERTER{index}]: Phase must be one of {PHASES}, not '{self.phase}'")
        self.poller = poller
        self.error_after = error_after
        self.use_yield_day = use_yield_day
        self.seen = None  # time of the answer that was written last
        self.in_error = False

        info = poller.latest[0][index]
        instance = int(section["DeviceInstance"])
        bus = dbus.SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else dbus.SystemBus(private=True)
        self.svc = svc = VeDbusService(f"{SERVICE}.http_{instance}", bus=bus, register=False)

        version = read_version()
        svc.add_path("/Mgmt/ProcessName", __file__)
        svc.add_path("/Mgmt/ProcessVersion", f"{version}, running on Python {platform.python_version()}")
        svc.add_path("/Mgmt/Connection", "TCP/IP (HTTP)")
        svc.add_path("/DeviceInstance", instance)
        svc.add_path("/ProductId", 0xFFFF)
        svc.add_path("/ProductName", PRODUCT_NAME)
        svc.add_path("/CustomName", info["name"])
        svc.add_path("/FirmwareVersion", version)
        svc.add_path("/HardwareVersion", 0)
        svc.add_path("/Serial", info["serial"])
        svc.add_path("/Position", int(section.get("AcPosition", 0)))  # 0=AC input 1; 1=AC output; 2=AC input 2
        svc.add_path("/Connected", 1)
        svc.add_path("/Latency", None)
        svc.add_path("/UpdateIndex", 0)
        svc.add_path("/StatusCode", RUNNING)

        phase = f"/Ac/{self.phase}"
        for path, unit in (("/Ac/Power", "W"), ("/Ac/Energy/Forward", "kWh"), (phase + "/Power", "W"),
                           (phase + "/Voltage", "V"), (phase + "/Current", "A"), (phase + "/Energy/Forward", "kWh")):
            svc.add_path(path, None, gettextcallback=lambda _path, value, fmt=TEXT[unit]: fmt.format(value))
        svc.register()
        logging.info("Registered %s.http_%d: '%s' on %s", SERVICE, instance, info["name"], self.phase)

    def update(self):
        '''Write the newest answer to D-Bus (or the error state, if there has been none for too long).'''
        inverters, received = self.poller.latest
        if time.monotonic() - received > self.error_after:
            self.fail()
        elif received != self.seen:  # a new answer since the last call
            self.seen = received
            try:
                self.show(inverters[self.index])
            except (KeyError, IndexError, TypeError, ValueError) as error:
                logging.warning("Inverter #%d: unexpected data from OpenDTU: %r", self.index, error)

    def fail(self):
        '''no data for too long: zero values, status error. Only once, until data is back.'''
        if self.in_error:
            return
        self.in_error = True
        logging.warning("Inverter #%d: no data from OpenDTU for %ds, setting values to 0", self.index, self.error_after)
        self.zero()
        self.svc["/StatusCode"] = ERROR
        self.svc["/Connected"] = 0

    def show(self, inverter):
        '''write the values of one inverter (as found in the OpenDTU answer)'''
        svc = self.svc
        phase = f"/Ac/{self.phase}"
        if not truthy(inverter["reachable"]) or "AC" not in inverter:  # OpenDTU is fine, the inverter sleeps (night)
            self.zero()
            svc["/StatusCode"] = STANDBY
        else:
            ac = inverter["AC"]["0"]
            producing = truthy(inverter["producing"])
            power = ac["Power"]["v"] if producing else 0
            current = ac["Current"]["v"] if producing else 0
            svc[phase + "/Power"] = svc["/Ac/Power"] = power
            svc[phase + "/Current"] = current
            svc[phase + "/Voltage"] = ac["Voltage"]["v"]
            counters = inverter["INV" if inverter.get("legacy") else "AC"]["0"]
            pvyield = counters["YieldDay"]["v"] / 1000 if self.use_yield_day else counters["YieldTotal"]["v"]
            if pvyield > 0:
                svc[phase + "/Energy/Forward"] = svc["/Ac/Energy/Forward"] = pvyield
            svc["/StatusCode"] = RUNNING
        if self.in_error:
            logging.info("Inverter #%d: data from OpenDTU is back", self.index)
            self.in_error = False
        svc["/Connected"] = 1
        svc["/UpdateIndex"] = (svc["/UpdateIndex"] + 1) % 256  # tells Venus OS that there are new values

    def zero(self):
        '''power values to 0; the energy counter keeps its last value'''
        for path in ("/Ac/Power", f"/Ac/{self.phase}/Power", f"/Ac/{self.phase}/Voltage",
                     f"/Ac/{self.phase}/Current"):
            self.svc[path] = 0


def read_version():
    '''first line of version.txt: "Version: 3.0.0"'''
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt"), encoding="utf-8") as file:
            return file.readline().split(":")[-1].strip()
    except OSError:
        return "unknown"


def read_config():
    '''config.ini next to this script; also sets the log level'''
    config = configparser.ConfigParser()
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.ini")
    if not config.read(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    logging.basicConfig(format="%(levelname)s %(message)s", level=config["DEFAULT"].get("Logging", "ERROR").upper())
    return config


def start(config):
    '''start polling and register one D-Bus device per [INVERTERn] section. Returns the devices.'''
    first = config["INVERTER0"]  # Host, Username, ... may be in [DEFAULT] or here
    user, password = first.get("Username", "").strip(), first.get("Password", "").strip()
    poller = Poller(first["Host"], (user, password) if user and password else None,
                    float(first.get("HTTPTimeout", 2.5)))
    poller.start()

    while poller.latest is None:  # the OpenDTU may start later than Venus OS - just wait for it
        time.sleep(1)

    use_yield_day = truthy(first.get("useYieldDay", 0))
    # 0 (old config.ini: "off") means the default; never less than 3 polls, or one lost answer would trigger it
    error_after = max(3 * POLL_SECONDS, int(first.get("ErrorStateAfterSeconds", 60)) or 60)
    available = len(poller.latest[0])
    devices = []
    index = 0
    while f"INVERTER{index}" in config:
        if index < available:
            devices.append(Inverter(index, config[f"INVERTER{index}"], poller, error_after, use_yield_day))
        else:
            logging.warning("[INVERTER%d] ignored: the OpenDTU reports only %d inverters", index, available)
        index += 1
    return devices


def main():
    '''start everything and run the GLib main loop'''
    config = read_config()
    DBusGMainLoop(set_as_default=True)  # needed before the first D-Bus service is created
    devices = start(config)
    if not devices:
        logging.critical("No inverters to show - check the [INVERTERn] sections in config.ini")
        sys.exit(1)

    def update_all():
        for device in devices:
            try:
                device.update()
            except Exception:  # pylint: disable=broad-except
                logging.exception("update of inverter #%d failed", device.index)
        return True  # True = call again

    def sign_of_life():
        for device in devices:
            logging.info("Inverter #%d '/Ac/Power': %s", device.index, device.svc["/Ac/Power"])
        return True

    GLib.timeout_add_seconds(1, update_all)
    GLib.timeout_add_seconds(int(config["DEFAULT"].get("SignOfLifeLog", 1)) * 60, sign_of_life)
    logging.info("Connected to dbus, switching over to GLib.MainLoop()")
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
