#!/bin/bash
# Copyright (c) Jupyter Development Team.
# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the Modified BSD License.

set -e

# The _log function is used for everything this script wants to log. It will
# always log errors and warnings, but can be silenced for other messages
# by setting JUPYTER_DOCKER_STACKS_QUIET environment variable.
_log () {
    if [[ "$*" == "ERROR:"* ]] || [[ "$*" == "WARNING:"* ]] || [[ "${JUPYTER_DOCKER_STACKS_QUIET}" == "" ]]; then
        echo "$@"
    fi
}
_log "Entered start.sh with args:" "$@"

# A helper function to unset env vars listed in the value of the env var
# JUPYTER_ENV_VARS_TO_UNSET.
unset_explicit_env_vars () {
    if [ -n "${JUPYTER_ENV_VARS_TO_UNSET}" ]; then
        for env_var_to_unset in $(echo "${JUPYTER_ENV_VARS_TO_UNSET}" | tr ',' ' '); do
            _log "Unset ${env_var_to_unset} due to JUPYTER_ENV_VARS_TO_UNSET"
            unset "${env_var_to_unset}"
        done
        unset JUPYTER_ENV_VARS_TO_UNSET
    fi
}


# Default to starting bash if no command was specified
if [ $# -eq 0 ]; then
    cmd=( "bash" )
else
    cmd=( "$@" )
fi

# NOTE: This hook will run as the user the container was started with!
# shellcheck disable=SC1091
source /usr/local/bin/run-hooks.sh /usr/local/bin/start-notebook.d

# If the container started as the root user, then we have permission to refit
# the nukelab user, and ensure file permissions, grant sudo rights, and such
# things before we run the command passed to start.sh as the desired user
# (USER_NAME).
#
if [ "$(id -u)" == 0 ] ; then
    # Environment variables:
    # - USER_NAME: the desired username and associated home folder
    # - USER_ID: the desired user id
    # - GROUP_ID: a group id we want our user to belong to
    # - NB_GROUP: a group name we want for the group
    # - GRANT_SUDO: a boolean ("1" or "yes") to grant the user sudo rights
    # - CHOWN_HOME: a boolean ("1" or "yes") to chown the user's home folder
    # - CHOWN_EXTRA: a comma separated list of paths to chown
    # - CHOWN_HOME_OPTS / CHOWN_EXTRA_OPTS: arguments to the chown commands

    # Refit the nukelab user to the desired the user (USER_NAME)
    if id nukelab &> /dev/null ; then
        if ! usermod --home "/home/${USER_NAME}" --login "${USER_NAME}" nukelab 2>&1 | grep "no changes" > /dev/null; then
            _log "Updated the nukelab user:"
            _log "- username: nukelab       -> ${USER_NAME}"
            _log "- home dir: /home/nukelab -> /home/${USER_NAME}"
        fi
    elif ! id -u "${USER_NAME}" &> /dev/null; then
        _log "ERROR: Neither the nukelab user or '${USER_NAME}' exists. This could be the result of stopping and starting, the container with a different USER_NAME environment variable."
        exit 1
    fi
    # Ensure the desired user (USER_NAME) gets its desired user id (USER_ID) and is
    # a member of the desired group (NB_GROUP, GROUP_ID)
    if [ "${USER_ID}" != "$(id -u "${USER_NAME}")" ] || [ "${GROUP_ID}" != "$(id -g "${USER_NAME}")" ]; then
        _log "Update ${USER_NAME}'s UID:GID to ${USER_ID}:${GROUP_ID}"
        # Ensure the desired group's existence
        if [ "${GROUP_ID}" != "$(id -g "${USER_NAME}")" ]; then
            groupadd --force --gid "${GROUP_ID}" --non-unique "${NB_GROUP:-${USER_NAME}}"
        fi
        # Recreate the desired user as we want it
        userdel "${USER_NAME}"
        useradd --no-log-init --home "/home/${USER_NAME}" --shell /bin/bash --uid "${USER_ID}" --gid "${GROUP_ID}" --groups 100 "${USER_NAME}"
    fi

    # Move or symlink the nukelab home directory to the desired users home
    # directory if it doesn't already exist, and update the current working
    # directory to the new location if needed.
    if [[ "${USER_NAME}" != "nukelab" ]]; then
        if [[ ! -e "/home/${USER_NAME}" ]]; then
            _log "Attempting to copy /home/nukelab to /home/${USER_NAME}..."
            mkdir "/home/${USER_NAME}"
            if cp -a /home/nukelab/. "/home/${USER_NAME}/"; then
                _log "Success!"
            else
                _log "Failed to copy data from /home/nukelab to /home/${USER_NAME}!"
                _log "Attempting to symlink /home/nukelab to /home/${USER_NAME}..."
                if ln -s /home/nukelab "/home/${USER_NAME}"; then
                    _log "Success creating symlink!"
                else
                    _log "ERROR: Failed copy data from /home/nukelab to /home/${USER_NAME} or to create symlink!"
                    exit 1
                fi
            fi
        fi
        # Ensure the current working directory is updated to the new path
        if [[ "${PWD}/" == "/home/nukelab/"* ]]; then
            new_wd="/home/${USER_NAME}/${PWD:13}"
            _log "Changing working directory to ${new_wd}"
            cd "${new_wd}"
        fi
    fi

    # Optionally ensure the desired user get filesystem ownership of it's home
    # folder and/or additional folders
    if [[ "${CHOWN_HOME}" == "1" || "${CHOWN_HOME}" == "yes" ]]; then
        _log "Ensuring /home/${USER_NAME} is owned by ${USER_ID}:${GROUP_ID} ${CHOWN_HOME_OPTS:+(chown options: ${CHOWN_HOME_OPTS})}"
        # shellcheck disable=SC2086
        chown ${CHOWN_HOME_OPTS} "${USER_ID}:${GROUP_ID}" "/home/${USER_NAME}"
    fi
    if [ -n "${CHOWN_EXTRA}" ]; then
        for extra_dir in $(echo "${CHOWN_EXTRA}" | tr ',' ' '); do
            _log "Ensuring ${extra_dir} is owned by ${USER_ID}:${GROUP_ID} ${CHOWN_EXTRA_OPTS:+(chown options: ${CHOWN_EXTRA_OPTS})}"
            # shellcheck disable=SC2086
            chown ${CHOWN_EXTRA_OPTS} "${USER_ID}:${GROUP_ID}" "${extra_dir}"
        done
    fi

    # Update potentially outdated environment variables since image build
    export XDG_CACHE_HOME="/home/${USER_NAME}/.cache"

    # Prepend ${CONDA_DIR}/bin to sudo secure_path
    sed -r "s#Defaults\s+secure_path\s*=\s*\"?([^\"]+)\"?#Defaults secure_path=\"${CONDA_DIR}/bin:\1\"#" /etc/sudoers | grep secure_path > /etc/sudoers.d/path

    # Optionally grant passwordless sudo rights for the desired user
    if [[ "$GRANT_SUDO" == "1" || "$GRANT_SUDO" == "yes" ]]; then
        _log "Granting ${USER_NAME} passwordless sudo rights!"
        echo "${USER_NAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/added-by-start-script
    fi

    # NOTE: This hook is run as the root user!
    # shellcheck disable=SC1091
    source /usr/local/bin/run-hooks.sh /usr/local/bin/before-notebook.d
    unset_explicit_env_vars

    _log "Running as ${USER_NAME}:" "${cmd[@]}"
    exec sudo --preserve-env --set-home --user "${USER_NAME}" \
        LD_LIBRARY_PATH="${LD_LIBRARY_PATH}" \
        PATH="${PATH}" \
        PYTHONPATH="${PYTHONPATH:-}" \
        "${cmd[@]}"
        # Notes on how we ensure that the environment that this container is started
        # with is preserved (except vars listed in JUPYTER_ENV_VARS_TO_UNSET) when
        # we transition from running as root to running as USER_NAME.
        #
        # - We use `sudo` to execute the command as USER_NAME. What then
        #   happens to the environment will be determined by configuration in
        #   /etc/sudoers and /etc/sudoers.d/* as well as flags we pass to the sudo
        #   command. The behavior can be inspected with `sudo -V` run as root.
        #
        #   ref: `man sudo`    https://linux.die.net/man/8/sudo
        #   ref: `man sudoers` https://www.sudo.ws/docs/man/sudoers.man/
        #
        # - We use the `--preserve-env` flag to pass through most environment
        #   variables, but understand that exceptions are caused by the sudoers
        #   configuration: `env_delete` and `env_check`.
        #
        # - We use the `--set-home` flag to set the HOME variable appropriately.
        #
        # - To reduce the default list of variables deleted by sudo, we could have
        #   used `env_delete` from /etc/sudoers. It has higher priority than the
        #   `--preserve-env` flag and the `env_keep` configuration.
        #
        # - We preserve LD_LIBRARY_PATH, PATH and PYTHONPATH explicitly. Note however that sudo
        #   resolves `${cmd[@]}` using the "secure_path" variable we modified
        #   above in /etc/sudoers.d/path. Thus PATH is irrelevant to how the above
        #   sudo command resolves the path of `${cmd[@]}`. The PATH will be relevant
        #   for resolving paths of any subprocesses spawned by `${cmd[@]}`.

# The container didn't start as the root user, so we will have to act as the
# user we started as.
else
    # Warn about misconfiguration of: granting sudo rights
    if [[ "${GRANT_SUDO}" == "1" || "${GRANT_SUDO}" == "yes" ]]; then
        _log "WARNING: container must be started as root to grant sudo permissions!"
    fi

    nukelab_UID="$(id -u nukelab 2>/dev/null)"  # The default UID for the nukelab user
    nukelab_GID="$(id -g nukelab 2>/dev/null)"  # The default GID for the nukelab user

    # Attempt to ensure the user uid we currently run as has a named entry in
    # the /etc/passwd file, as it avoids software crashing on hard assumptions
    # on such entry. Writing to the /etc/passwd was allowed for the root group
    # from the Dockerfile during build.
    #
    # ref: https://github.com/jupyter/docker-stacks/issues/552
    if ! whoami &> /dev/null; then
        _log "There is no entry in /etc/passwd for our UID=$(id -u). Attempting to fix..."
        if [[ -w /etc/passwd ]]; then
            _log "Renaming old nukelab user to nuclearlab ($(id -u nukelab):$(id -g nukelab))"

            # We cannot use "sed --in-place" since sed tries to create a temp file in
            # /etc/ and we may not have write access. Apply sed on our own temp file:
            sed --expression="s/^nukelab:/nuclearlab:/" /etc/passwd > /tmp/passwd
            echo "${USER_NAME}:x:$(id -u):$(id -g):,,,:/home/nukelab:/bin/bash" >> /tmp/passwd
            cat /tmp/passwd > /etc/passwd
            rm /tmp/passwd

            _log "Added new ${USER_NAME} user ($(id -u):$(id -g)). Fixed UID!"

            if [[ "${USER_NAME}" != "nukelab" ]]; then
                _log "WARNING: user is ${USER_NAME} but home is /home/nukelab. You must run as root to rename the home directory!"
            fi
        else
            _log "WARNING: unable to fix missing /etc/passwd entry because we don't have write permission. Try setting gid=0 with \"--user=$(id -u):0\"."
        fi
    fi

    # Warn about misconfiguration of: desired username, user id, or group id.
    # A misconfiguration occurs when the user modifies the default values of
    # USER_NAME, USER_ID, or GROUP_ID, but we cannot update those values because we
    # are not root.
    if [[ "${USER_NAME}" != "nukelab" && "${USER_NAME}" != "$(id -un)" ]]; then
        _log "WARNING: container must be started as root to change the desired user's name with USER_NAME=\"${USER_NAME}\"!"
    fi
    if [[ "${USER_ID}" != "${nukelab_UID}" && "${USER_ID}" != "$(id -u)" ]]; then
        _log "WARNING: container must be started as root to change the desired user's id with USER_ID=\"${USER_ID}\"!"
    fi
    if [[ "${GROUP_ID}" != "${nukelab_GID}" && "${GROUP_ID}" != "$(id -g)" ]]; then
        _log "WARNING: container must be started as root to change the desired user's group id with GROUP_ID=\"${GROUP_ID}\"!"
    fi

    # Warn if the user isn't able to write files to ${HOME}
    if [[ ! -w /home/nukelab ]]; then
        _log "WARNING: no write access to /home/nukelab. Try starting the container with group 'users' (100), e.g. using \"--group-add=users\"."
    fi

    # NOTE: This hook is run as the user we started the container as!
    # shellcheck disable=SC1091
    source /usr/local/bin/run-hooks.sh /usr/local/bin/before-notebook.d
    unset_explicit_env_vars

    _log "Executing the command:" "${cmd[@]}"
    exec "${cmd[@]}"
fi