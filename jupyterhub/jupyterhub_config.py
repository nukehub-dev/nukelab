# Import modules
import os
import sys
from dockerspawner import DockerSpawner
from oauthenticator.generic import GenericOAuthenticator

# Set the base URL
#c.JupyterHub.base_url = "/nukelab/"

# Set the logo
c.JupyterHub.logo_file = "nukelab.png"

# GenericOAuthenticator
c.JupyterHub.authenticator_class = GenericOAuthenticator
c.GenericOAuthenticator.allow_all = True
c.GenericOAuthenticator.login_service = "NukeHub"
c.GenericOAuthenticator.client_id = os.environ['OAUTH_CLIENT_ID']
c.GenericOAuthenticator.client_secret = os.environ['OAUTH_CLIENT_SECRET']
c.GenericOAuthenticator.oauth_callback_url = os.environ['OAUTH_CALLBACK_URL']
c.GenericOAuthenticator.authorize_url = os.environ['OAUTH_AUTHORIZE_URL']
c.GenericOAuthenticator.token_url = os.environ['OAUTH_TOKEN_URL']
c.GenericOAuthenticator.userdata_url = os.environ['OAUTH_USERDATA_URL']
c.GenericOAuthenticator.username_claim = os.environ.get("OAUTH_USERNAME_CLAIM", "preferred_username")
c.GenericOAuthenticator.scope = os.environ.get("OAUTH_SCOPES", "openid email profile").split()
c.GenericOAuthenticator.custom_403_message = "Sorry, you are not currently authorized to use this NukeLab. Please contact <a href='mailto:admin@nukehub.org' style='text-decoration: none;'>NukeHub Admin</a>"

# NativeAuthenticator (Testing purposes, uncomment if needed)
""" 
from nativeauthenticator import NativeAuthenticator
c.Authenticator.allow_all = True
c.JupyterHub.authenticator_class = NativeAuthenticator
c.NativeAuthenticator.open_signup = True
"""

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