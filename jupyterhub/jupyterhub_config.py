# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the Modified BSD License.

# Import modules
from dockerspawner import DockerSpawner
from nativeauthenticator import NativeAuthenticator
from oauthenticator import GitHubOAuthenticator
import os
import sys

# Set the base URL
#c.JupyterHub.base_url = "/nukelab/"

# Set the logo
c.JupyterHub.logo_file = "nukelab.png"

# NativeAuthenticator
#c.JupyterHub.authenticator_class = NativeAuthenticator
#c.NativeAuthenticator.open_signup = True

# Shutdown
#c.JupyterHub.shutdown_on_logout = True

# GitHubOAuthenticator
c.JupyterHub.authenticator_class = GitHubOAuthenticator
c.GitHubOAuthenticator.oauth_callback_url = os.environ['OAUTH_CALLBACK_URL']
c.GitHubOAuthenticator.allow_all = True
c.GitHubOAuthenticator.delete_invalid_users = True
c.GitHubOAuthenticator.custom_403_message = "Sorry, you are not currently authorized to use this NukeLab. Please contact <a href='mailto:admin@nukehub.org' style='text-decoration: none;'>NukeHub Admin</a>"

# Allowed admins
admin = os.environ.get("NUKELAB_ADMIN")
if admin:
    c.Authenticator.admin_users = [admin]

# Set the timeout to 300 seconds
c.Spawner.http_timeout = 300
c.Spawner.start_timeout = 300

# Set the log level
c.JupyterHub.log_level = "INFO"

# Set the hub IP
c.JupyterHub.hub_ip = "nukelab"
c.JupyterHub.hub_port = 8080

# Set the spawner
c.JupyterHub.spawner_class = DockerSpawner
c.DockerSpawner.network_name = "nukelab-network"
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.notebook_dir = os.environ.get("DOCKER_NUKELAB_DIR")
c.DockerSpawner.volumes = {"nukelab-user-{username}": os.environ.get("DOCKER_NUKELAB_DIR")}
c.DockerSpawner.image = os.environ["DOCKER_NUKELAB_IMAGE"]
c.DockerSpawner.prefix = "nukelab"
c.DockerSpawner.extra_create_kwargs = {"hostname": "NukeHub",}
c.DockerSpawner.remove = True

# Set the database
c.JupyterHub.db_url = "sqlite:///data/nukelab.sqlite"
c.JupyterHub.cookie_secret_file = "/data/jupyterhub_cookie_secret"

# Idle culler
c.JupyterHub.load_roles = [
    {
        "name": "jupyterhub-idle-culler-role",
        "scopes": [
            "list:users",
            "read:users:activity",
            "read:servers",
            "delete:servers",
        ],
        # assignment of role's permissions to:
        "services": ["jupyterhub-idle-culler-service"],
    }
]
c.JupyterHub.services = [
    {
        "name": "jupyterhub-idle-culler-service",
        "command": [
            sys.executable,
            "-m", "jupyterhub_idle_culler",
            "--timeout=600",
        ],
    }
]