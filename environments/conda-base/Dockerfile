# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

# Shared conda/Python/build foundation for the NukeLab workspace and for
# domain-specific scientific toolchain images. Keeping this separate from
# workspace means IDE updates do not force a rebuild of heavy C++/Fortran
# scientific stacks.
ARG BASE_IMAGE=ghcr.io/nukelab/base:v1.0.0

FROM $BASE_IMAGE

# Install build tools and scientific libraries shared by the IDE and toolchain
# images. Domain-specific toolchains add their own graphics/physics deps on top.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gfortran \
        cmake \
        autoconf \
        pkg-config \
        m4 \
        git \
        wget \
        locales \
        libblas-dev \
        liblapack-dev \
        libeigen3-dev \
        libboost-dev \
        libboost-tools-dev \
        libhdf5-dev \
        libxml2-dev \
        libpng-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

# Configure core environment variables for Conda
ENV CONDA_DIR=/opt/conda \
    SHELL=/bin/bash \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8
ENV PATH=${CONDA_DIR}/bin:${PATH}

# Install Miniforge to manage Python environments
RUN wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O Miniforge3.sh && \
    bash Miniforge3.sh -b -p $CONDA_DIR && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/profile.d/conda.sh && \
    rm Miniforge3.sh

# Activate the conda base environment in login shells so python from
# /opt/conda/bin is on PATH for toolchain builds and terminal sessions.
COPY conda-base.sh /etc/profile.d/nukelab-conda-base.sh
