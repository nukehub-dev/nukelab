# NukeLab: show the human username in the prompt
if [ -n "${NUKELAB_USERNAME:-}" ]; then
    export USER="$NUKELAB_USERNAME"
    export HOME="/home/$NUKELAB_USERNAME"
    export PS1="\[\e[0;32m\]${NUKELAB_USERNAME}@\[\e[0;36m\]NukeLab\[\e[0m\]:\w\$ "
fi
