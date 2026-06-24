cmd_install() {
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Installing frontend dependencies..."
        command -v npm > /dev/null 2>&1 || die "npm not found"
        cd "$DIR/frontend"
        npm install
        ok "Frontend dependencies installed"
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        info "Backend dependencies are managed via Docker (requirements.txt). No local installation needed."
    fi
}
