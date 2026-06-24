help_install_completion() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh install-completion

Install bash tab-completion for manage.sh.

This appends a source line to ${BOLD}~/.bashrc${RESET}. Reload your shell or run
${BOLD}source ~/.bashrc${RESET} to use it immediately.

${BOLD}Examples:${RESET}
  ./manage.sh install-completion
EOF
}

cmd_install_completion() {
    local completion_file="$DIR/scripts/manage-completion.bash"
    if [ ! -f "$completion_file" ]; then
        die "Completion script not found: $completion_file"
    fi

    local shell_rc="$HOME/.bashrc"
    if [ -n "${ZSH_VERSION:-}" ] || [ "${SHELL##*/}" = "zsh" ]; then
        warn "Zsh detected. Bash completion is not automatically installed for zsh."
        info "To use it, add this line to your ~/.zshrc:"
        info "  source $completion_file"
        return 0
    fi

    local source_line="source $completion_file  # NukeLab manage.sh completion"
    if [ -f "$shell_rc" ] && grep -Fxq "$source_line" "$shell_rc" 2>/dev/null; then
        info "Completion already installed in $shell_rc"
        return 0
    fi

    echo "$source_line" >> "$shell_rc"
    ok "Bash completion installed in $shell_rc"
    info "Reload with: source $shell_rc"
}
