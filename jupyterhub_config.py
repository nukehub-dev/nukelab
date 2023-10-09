# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the Modified BSD License.

# Import modules
from dockerspawner import DockerSpawner
from nativeauthenticator import NativeAuthenticator
import os

# Set the base URL
c.JupyterHub.base_url = "/nukelab/"

# Set the logo
c.JupyterHub.logo_file = "nukelab.png"


# Set the authenticator
c.JupyterHub.authenticator_class = NativeAuthenticator
c.GenericOAuthenticator.enable_auth_state = True
c.NativeAuthenticator.create_system_users = True

# Set the allowed users
c.Authenticator.allowed_users = set()
c.Authenticator.admin_users = {"tahmid"}
c.NativeAuthenticator.open_signup = True


# Set the timeout to 300 seconds
c.Spawner.http_timeout = 300
c.Spawner.start_timeout = 300

# Set the log level
c.JupyterHub.log_level = "INFO"

# Set the hub IP
c.JupyterHub.hub_ip = "0.0.0.0"

c.JupyterHub.allow_named_servers = True

# Set the spawner
c.DockerSpawner.network_name = "nukelab"
c.DockerSpawner.remove = True
c.JupyterHub.spawner_class = DockerSpawner
notebook_dir = os.environ.get("DOCKER_NOTEBOOK_DIR") or "/home/nukelab/"
c.DockerSpawner.notebook_dir = notebook_dir
c.DockerSpawner.volumes = {"nukelab-user-{username}": notebook_dir}
c.DockerSpawner.image = "nukelab-spawner"
c.DockerSpawner.prefix = "nukelab"
c.DockerSpawner.extra_create_kwargs = {"hostname": "nin"}

# Set the database
c.JupyterHub.db_url = "sqlite:///data/nukelab.sqlite"
