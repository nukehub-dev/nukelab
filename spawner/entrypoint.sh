#!/bin/bash
set -e

# Ensure the .nuke-ide directory exists in the mounted volume
if [ ! -d "${HOME}/work/.nuke-ide" ]; then
    mkdir -p "${HOME}/work/.nuke-ide"
fi

# Ensure the symlink exists
if [ ! -L "${HOME}/.nuke-ide" ]; then
    ln -sfn "${HOME}/work/.nuke-ide" "${HOME}/.nuke-ide"
fi

# Adjust ownership if running rootless
if [ "$(id -u)" -ne 0 ]; then
    chown -R $(id -u):$(id -g) "${HOME}/work/.nuke-ide"
fi

# Execute the container's main process
exec conda run -p ${NUKE_DIR} "$@"
