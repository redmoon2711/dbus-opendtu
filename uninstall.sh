#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd -P )
SERVICE_NAME=$(basename "$SCRIPT_DIR")
SERVICE_ROOT="${SERVICE_ROOT:-/service}"
LOG_DIR="/var/log/$SERVICE_NAME"
RC_LOCAL_FILE="${RC_LOCAL:-/data/rc.local}"

# kill all processes whose command line matches the pattern (nothing to do if there are none)
kill_matching() {
    local pids
    pids=$(pgrep -f "$1") || return 0
    [ -n "$pids" ] && kill $pids
    return 0
}

# 1. stop the service and its log service. "svc -dx": take it down and let its supervise process exit.
#    This has to happen before the link is removed, afterwards svc can not find the service any more.
if [ -L "$SERVICE_ROOT/$SERVICE_NAME" ]; then
    if command -v svc > /dev/null; then
        svc -dx "$SERVICE_ROOT/$SERVICE_NAME" "$SERVICE_ROOT/$SERVICE_NAME/log"
    fi
    rm -f "$SERVICE_ROOT/$SERVICE_NAME"
fi

# 2. clean up what is left (e.g. when the link was already removed by an earlier uninstall)
kill_matching "supervise $SERVICE_NAME\$"
kill_matching "python $SCRIPT_DIR/dbus_opendtu.py"
# The supervise of the log service is only called "supervise log" (all services have one),
# so it is recognised by its working directory.
for pid in $(pgrep -f "supervise log\$"); do
    if [ "$(readlink "/proc/$pid/cwd")" = "$SCRIPT_DIR/service" ]; then
        kill "$pid"
    fi
done
# multilog keeps the log folder locked, a new log service could not start while it runs
kill_matching "multilog .* /var/log/$SERVICE_NAME\$"

# delete old logs if they exist
rm -f "$SCRIPT_DIR"/current.log*

# remove install.sh from rc.local (exact line match, the path is not treated as a pattern)
if [ -f "$RC_LOCAL_FILE" ]; then
    TMP_RC=$(mktemp) || exit 1
    grep -vxF "$SCRIPT_DIR/install.sh" "$RC_LOCAL_FILE" > "$TMP_RC"
    # write back into the same file to keep owner and permissions
    cat "$TMP_RC" > "$RC_LOCAL_FILE"
    rm -f "$TMP_RC"
fi

# delete log folder in var log if they exist
if [ -d "$LOG_DIR" ]; then
    while true; do
        read -r -p "Do you really wish to delete the log folder $LOG_DIR? [y/n] " yn || break
        case $yn in
            [Yy]* ) rm -rf "$LOG_DIR"; echo "$LOG_DIR is deleted"; break;;
            [Nn]* ) break;;
            * ) echo "Please answer y or n.";;
        esac
    done
fi
