# dbus-opendtu (lightweight)

**Shows the micro inverters of an [OpenDTU](https://github.com/tbnobody/OpenDTU) as PV inverters on Victron Venus OS (D-Bus) – one small Python file, no blocking of the GLib main loop.**

Runs on Venus OS (Cerbo GX, Raspberry Pi, ...) and works with current and older OpenDTU firmware. Every
inverter is single-phase (L1, L2 or L3) and appears as a normal `com.victronenergy.pvinverter` device.

> **Origin:** This project is based on [henne49/dbus-opendtu](https://github.com/henne49/dbus-opendtu)
> (MIT license, Copyright Christian Hennrich, Dirk Steinkopf, Maurice Schmicking) and is a heavily simplified,
> stand-alone variant of it. If you need Ahoy, templates (Tasmota/Shelly) or three-phase inverters,
> the original is the right choice.

## How it differs from the original

| | Original | This variant |
|---|---|---|
| Devices | OpenDTU, Ahoy, templates | OpenDTU only |
| Phases | L1, L2, L3, 3P | L1, L2, L3 (single-phase) |
| Program | several modules | one file, `dbus_opendtu.py` (about 260 lines) |
| Polling | in a timer of the main loop | in a background thread: a slow or failed OpenDTU never blocks Venus OS |
| OpenDTU failure | several modes (`ErrorMode`, ...) | one rule: after `ErrorStateAfterSeconds` without an answer the power values become 0 |
| Updates | `update.sh` downloads from GitHub | manual (copy the files), no automatic updates |

While an inverter sleeps (night) or has not sent data since the OpenDTU was started, it is shown as standby;
the energy counter keeps its value.

## Installation

1. Download this repository (`git clone` or "Code → Download ZIP") and copy the folder to the Venus OS device as
   **`/data/dbus-opendtu`**, e.g. `scp -r dbus-opendtu root@<venus-ip>:/data/`.
   The folder name is the service name and determines the log directory `/var/log/dbus-opendtu`. A ZIP download
   is usually called `<repo>-main`, please rename it.
2. On the device, create your settings and adjust them (`Host`, and `Phase` and `DeviceInstance` of every inverter):

       cp /data/dbus-opendtu/config.example /data/dbus-opendtu/config.ini
       vi /data/dbus-opendtu/config.ini

3. Set up the service: `bash /data/dbus-opendtu/install.sh`

`install.sh` fixes the file permissions, sets up the service and adds itself to `/data/rc.local`, so the service
survives a firmware update.

## Updating

Copy the new files over the old ones (`config.ini` is not part of the repository and stays untouched), then on the
device:

    bash /data/dbus-opendtu/install.sh
    bash /data/dbus-opendtu/restart.sh

A `config.ini` from the original keeps working; entries for Ahoy, templates, `ErrorMode` etc. are ignored.

## Removal

    bash /data/dbus-opendtu/uninstall.sh

## Troubleshooting

* Log: `tail -f /var/log/dbus-opendtu/current` (set the detail level with `Logging=` in `config.ini`, e.g. `DEBUG`)
* Restart the service: `bash /data/dbus-opendtu/restart.sh`
* `Bus name already exists`: another process uses the same `DeviceInstance` (an old installation or a duplicate
  entry in `config.ini`).
* `supervise: unable to start ... access denied`: `bash /data/dbus-opendtu/install.sh` sets the file permissions.
* The log only shows `Version: ...` and `OpenDTU request failed`: check `Host` in `config.ini`; enter user name
  and password only if the OpenDTU requires a login.

## Structure

| File | Purpose |
|---|---|
| `dbus_opendtu.py` | the whole program: poller thread, D-Bus device, startup |
| `config.example` | template for `config.ini` |
| `version.txt` | version number (shown on Venus OS) |
| `install.sh`, `uninstall.sh`, `restart.sh` | service management |
| `service/run`, `service/log/run` | started by the Venus OS supervisor, logging with multilog |

## Inspiration and thanks

Like the original, this project builds on the work of others:

- [henne49/dbus-opendtu](https://github.com/henne49/dbus-opendtu), the basis of this project
- [fabian-lauer/dbus-shelly-3em-smartmeter](https://github.com/fabian-lauer/dbus-shelly-3em-smartmeter) and
  [vikt0rm/dbus-shelly-1pm-pvinverter](https://github.com/vikt0rm/dbus-shelly-1pm-pvinverter), which inspired the original
- [OpenDTU](https://github.com/tbnobody/OpenDTU) and its [Web API documentation](https://github.com/tbnobody/OpenDTU/blob/master/docs/Web-API.md)
- [Victron Wiki: D-Bus PV inverters](https://github.com/victronenergy/venus/wiki/dbus#pv-inverters)

## License

MIT, see [LICENSE](LICENSE). The license text with the copyright notice comes from the original repository.
