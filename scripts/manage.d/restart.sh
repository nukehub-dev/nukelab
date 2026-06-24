source "$DIR/scripts/manage.d/stop.sh"
source "$DIR/scripts/manage.d/start.sh"

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

help_restart() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh restart [target]

Stop and then start services.

${BOLD}Targets:${RESET} backend | frontend | all

${BOLD}Examples:${RESET}
  ./manage.sh restart
  ./manage.sh restart backend
EOF
}

