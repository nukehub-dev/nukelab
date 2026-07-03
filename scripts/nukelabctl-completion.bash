#!/usr/bin/env bash
# Bash completion for ./nukelabctl
# Source this file or install it via ./nukelabctl install-completion

_manage_sh_complete() {
	local cur="${COMP_WORDS[COMP_CWORD]}"
	local prev="${COMP_WORDS[COMP_CWORD - 1]}"
	local cmd="${COMP_WORDS[1]}"

	local commands=(
		start stop restart status logs build update pull remove rm clean
		shell exec install test e2e loadtest db-migrate db-shell
		backup restore reset dev lint security
		init-user-auth-keys rotate-user-auth-key cleanup-user-auth-keys
		doctor version install-completion selftest help
	)

	local global_flags=(--coverage --overlay -o --verbose -v --quiet -q --skip-port-check --no-alertmanager --version --help -h)

	# First argument: command names only.
	if [[ $COMP_CWORD -eq 1 ]]; then
		COMPREPLY=($(compgen -W "${commands[*]}" -- "$cur"))
		return
	fi

	# Options that take a value — complete the value, not an option name.
	case "$prev" in
	--tail | -n | --timeout | -t)
		return
		;;
	--overlay | -o)
		COMPREPLY=($(compgen -f -- "$cur"))
		return
		;;
	esac

	# Command-specific completions.
	case "$cmd" in
	start | restart | remove | rm)
		local opts="backend frontend all ${global_flags[*]}"
		# start and restart both honor --no-build / --no-wait.
		if [[ "$cmd" == "start" || "$cmd" == "restart" ]]; then
			opts="$opts --no-build --no-wait"
		fi
		COMPREPLY=($(compgen -W "$opts" -- "$cur"))
		;;
	build)
		if [[ "$COMP_CWORD" -eq 2 ]]; then
			COMPREPLY=($(compgen -W "backend frontend all env ${global_flags[*]}" -- "$cur"))
		elif [[ "${COMP_WORDS[2]}" == "env" ]]; then
			COMPREPLY=($(compgen -W "base workspace radiation-transport dev all ${global_flags[*]}" -- "$cur"))
		else
			COMPREPLY=($(compgen -W "${global_flags[*]}" -- "$cur"))
		fi
		;;
	stop)
		COMPREPLY=($(compgen -W "backend frontend all --timeout -t ${global_flags[*]}" -- "$cur"))
		;;
	status)
		COMPREPLY=($(compgen -W "--running ${global_flags[*]}" -- "$cur"))
		;;
	logs)
		COMPREPLY=($(compgen -W "backend frontend postgres redis traefik celery-worker celery-beat pgbouncer prometheus grafana postgres-exporter redis-exporter node-exporter celery-exporter --tail -n --no-follow ${global_flags[*]}" -- "$cur"))
		;;
	shell | exec)
		COMPREPLY=($(compgen -W "backend frontend postgres redis traefik celery-worker celery-beat pgbouncer ${global_flags[*]}" -- "$cur"))
		;;
	install | test)
		COMPREPLY=($(compgen -W "frontend backend all --coverage ${global_flags[*]}" -- "$cur"))
		;;
	loadtest)
		COMPREPLY=($(compgen -W "smoke baseline stress spike endurance connection k6-smoke k6-baseline k6-stress k6-spike k6-endurance all ${global_flags[*]}" -- "$cur"))
		;;
	lint)
		COMPREPLY=($(compgen -W "frontend backend shell all --fix -f ${global_flags[*]}" -- "$cur"))
		;;
	restore)
		# restore takes a backup file path.
		COMPREPLY=($(compgen -f -- "$cur"))
		;;
	dev)
		if [[ "$COMP_CWORD" -eq 2 ]]; then
			COMPREPLY=($(compgen -W "start restart stop logs status ${global_flags[*]}" -- "$cur"))
		else
			# After `dev <sub>` offer targets/flags matching each subcommand.
			local sub="${COMP_WORDS[2]}"
			case "$sub" in
			start | restart | stop)
				local opts="backend frontend all ${global_flags[*]}"
				[[ "$sub" == "start" || "$sub" == "restart" ]] && opts="$opts --no-build --no-wait"
				COMPREPLY=($(compgen -W "$opts" -- "$cur"))
				;;
			logs)
				COMPREPLY=($(compgen -W "backend postgres redis traefik celery-worker celery-beat pgbouncer --tail -n --no-follow ${global_flags[*]}" -- "$cur"))
				;;
			*)
				COMPREPLY=($(compgen -W "${global_flags[*]}" -- "$cur"))
				;;
			esac
		fi
		;;
	update | pull | clean | e2e | db-migrate | db-shell | backup | reset | selftest | install-completion | help | security | init-user-auth-keys | rotate-user-auth-key | cleanup-user-auth-keys)
		COMPREPLY=($(compgen -W "${global_flags[*]}" -- "$cur"))
		;;
	*)
		COMPREPLY=($(compgen -W "${global_flags[*]}" -- "$cur"))
		;;
	esac
}

complete -F _manage_sh_complete ./nukelabctl
