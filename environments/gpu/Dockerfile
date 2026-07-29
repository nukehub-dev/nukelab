# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

# Define the base image for the Dockerfile
ARG BASE_IMAGE=nukelab-workspace:latest

# Define the CUDA toolkit version
ARG CUDA_VERSION=12.6

# Set the base image for the Dockerfile
FROM $BASE_IMAGE

# Install the CUDA toolkit into the base conda environment from the
# NVIDIA channel, then clean up conda caches to reduce the image size.
ARG CUDA_VERSION
RUN conda install -y -c nvidia cuda-toolkit=${CUDA_VERSION} && \
    conda clean -afy

# Advertise all GPUs and the compute/utility driver capabilities to the
# NVIDIA container runtime when the container is started with GPU access.
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
