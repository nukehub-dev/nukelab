#!/bin/bash

# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the Modified BSD License.

# Enable Shell exit on any error
set -e

# Store current directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

cd $DIR/spawner

# Build docker image
# Note: The image will be named "nukelab-spawner"
#       If you get permissions errors, try running as root
#       Or, run the following command:
#           sudo usermod -aG docker $USER
#       This will allow you to run docker commands without sudo
docker build -t nukelab-spawner .

cd $DIR

# Build with docker-compose
docker compose build

