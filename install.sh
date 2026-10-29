#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd -P )
SERVICE_NAME=$(basename "$SCRIPT_DIR")
SERVICE_ROOT="${SERVICE_ROOT:-/service}"
RC_LOCAL="${RC_LOCAL:-/data/rc.local}"

# "v2.1.0-rc.1" -> "2.1.0"
normalize_version() {
    local v="${1#[vV]}"
    echo "${v%%[-+]*}"
}

# returns 0 if version $1 >= version $2 (numeric, component-wise)
version_ge() {
    local IFS=.
    local -a a b
    read -r -a a <<< "$(normalize_version "$1")"
    read -r -a b <<< "$(normalize_version "$2")"
    local i x y max=${#a[@]}
    [ "${#b[@]}" -gt "$max" ] && max=${#b[@]}
    for ((i = 0; i < max; i++)); do
        x="${a[i]:-0}"; x="${x//[^0-9]/}"; x=$((10#${x:-0}))
        y="${b[i]:-0}"; y="${y//[^0-9]/}"; y=$((10#${y:-0}))
        [ "$x" -gt "$y" ] && return 0
        [ "$x" -lt "$y" ] && return 1
    done
    return 0
}

# check if config.ini file exists
if [ ! -f "$SCRIPT_DIR/config.ini" ]; then
    echo "config.ini not found in $SCRIPT_DIR. Please copy config.example to config.ini and adjust it (see README.md):"
    echo "    cp $SCRIPT_DIR/config.example $SCRIPT_DIR/config.ini"
    exit 1
fi

# the service directory is part of the repository
for f in service/run service/log/run; do
    if [ ! -f "$SCRIPT_DIR/$f" ]; then
        echo "$SCRIPT_DIR/$f not found - the installation is incomplete."
        exit 1
    fi
done

if [ ! -d "$SERVICE_ROOT" ]; then
    echo "$SERVICE_ROOT not found - this script has to run on a Venus OS device."
    exit 1
fi

# delete old logs if they exist
rm -f "$SCRIPT_DIR"/current.log*

# since version 2.0.0 the script is called dbus_opendtu.py - remove the old dbus-opendtu.py
if [ -f "$SCRIPT_DIR/version.txt" ]; then
    INSTALLED_VERSION=$(grep -o 'Version: [^ ]*' "$SCRIPT_DIR/version.txt" | head -n1 | cut -d' ' -f2)
    if [ -n "$INSTALLED_VERSION" ] && version_ge "$INSTALLED_VERSION" "2.0.0"; then
        rm -f "$SCRIPT_DIR/dbus-opendtu.py"
    fi
fi

# remove files of the original GitHub project that are obsolete in this stand-alone version.
# Important: the old update.sh would download the original code from GitHub and overwrite this version.
rm -f "$SCRIPT_DIR/update.sh" "$SCRIPT_DIR/imports.py" "$SCRIPT_DIR/tests.py" "$SCRIPT_DIR/run_coverage.sh"
# modules of earlier versions, everything is in dbus_opendtu.py now
rm -f "$SCRIPT_DIR/dtu.py" "$SCRIPT_DIR/dbus_service.py" "$SCRIPT_DIR/helpers.py" "$SCRIPT_DIR/constants.py"
rm -rf "$SCRIPT_DIR/__pycache__"

# set permissions for script files
chmod 755 "$SCRIPT_DIR/restart.sh"
chmod 755 "$SCRIPT_DIR/uninstall.sh"
chmod 755 "$SCRIPT_DIR/service/run"
chmod 755 "$SCRIPT_DIR/service/log/run"

# remove the stray link "service/service" that older versions of this script created on every boot
if [ -L "$SCRIPT_DIR/service/service" ]; then
    rm -f "$SCRIPT_DIR/service/service"
fi

# create sym-link to the service directory in the daemon folder
LINK="$SERVICE_ROOT/$SERVICE_NAME"
if [ -L "$LINK" ]; then
    # fix a link that points somewhere else (e.g. the folder was moved)
    if [ "$(readlink "$LINK")" != "$SCRIPT_DIR/service" ]; then
        ln -sfn "$SCRIPT_DIR/service" "$LINK"
    fi
elif [ -e "$LINK" ]; then
    echo "$LINK exists and is not a link. Please remove it and run this script again."
    exit 1
else
    ln -s "$SCRIPT_DIR/service" "$LINK"
fi

# add install-script to rc.local to be ready for firmware update
# check if rc.local already exists, if not create it
if [ ! -f "$RC_LOCAL" ]; then
    printf '#!/bin/bash\n\n' > "$RC_LOCAL"
fi
# rc.local is only executed by Venus OS if it is executable
[ -x "$RC_LOCAL" ] || chmod 755 "$RC_LOCAL"

# check if the entry exists, if not add it
grep -qxF "$SCRIPT_DIR/install.sh" "$RC_LOCAL" || echo "$SCRIPT_DIR/install.sh" >> "$RC_LOCAL"

echo "All Done"
