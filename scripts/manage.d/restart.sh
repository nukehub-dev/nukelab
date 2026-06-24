source "$DIR/scripts/manage.d/stop.sh"
source "$DIR/scripts/manage.d/start.sh"

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}
