#!/usr/bin/env bash
# Bash completion for ./manage.sh
# Source this file or install it via ./manage.sh install-completion

_manage_sh_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local prev="${COMP_WORDS[COMP_CWORD-1]}"
    local cmd="${COMP_WORDS[1]}"

    local commands=(
        start stop restart status logs build update pull remove clean
        shell exec install test e2e loadtest db-migrate db-shell
        backup restore reset doctor version install-completion selftest help
    )

    local global_flags=(--dev -d --coverage --overlay -o --verbose -v --quiet -q --help -h)

    # First argument: command names only.
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands[*]}" -- "$cur") )
        return
    fi

    # Command-specific completions.
    case "$cmd" in
        start|build|restart|remove)
            local opts="backend frontend all ${global_flags[*]}"
            if [[ "$cmd" == "start" ]]; then
                opts="$opts --no-build --no-wait"
            fi
            COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
            ;;
        stop)
            COMPREPLY=( $(compgen -W "backend frontend all --timeout -t ${global_flags[*]}" -- "$cur") )
            ;;
        status)
            COMPREPLY=( $(compgen -W "--running ${global_flags[*]}" -- "$cur") )
            ;;
        logs)
            COMPREPLY=( $(compgen -W "backend frontend postgres redis traefik celery-worker celery-beat pgbouncer prometheus grafana --tail -n --no-follow ${global_flags[*]}" -- "$cur") )
            ;;
        shell|exec)
            COMPREPLY=( $(compgen -W "backend frontend postgres redis ${global_flags[*]}" -- "$cur") )
            ;;
        install|test)
            COMPREPLY=( $(compgen -W "frontend backend all --coverage ${global_flags[*]}" -- "$cur") )
            ;;
        loadtest)
            COMPREPLY=( $(compgen -W "baseline smoke stress ${global_flags[*]}" -- "$cur") )
            ;;
        update|pull|clean|e2e|db-migrate|db-shell|backup|restore|reset|selftest|install-completion|help)
            COMPREPLY=( $(compgen -W "${global_flags[*]}" -- "$cur") )
            ;;
        *)
            COMPREPLY=( $(compgen -W "${global_flags[*]}" -- "$cur") )
            ;;
    esac
}

complete -F _manage_sh_complete ./manage.sh
