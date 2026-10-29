#!/bin/bash
# Stops the python process; supervise (daemontools) starts it again immediately.
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd -P )

PIDS=$(pgrep -f "python $SCRIPT_DIR/dbus_opendtu.py")
if [ -n "$PIDS" ]; then
    # shellcheck disable=SC2086
    kill $PIDS
    echo "dbus_opendtu stopped, the service supervisor restarts it."
else
    echo "dbus_opendtu is not running (is the service installed? run install.sh)."
fi
