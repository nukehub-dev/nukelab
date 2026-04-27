# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

# Define the base image for the Dockerfile
ARG BASE_IMAGE=debian:13

# Define the Python version and JupyterHub version to be used
ARG PYTHON_VERSION=3.12
ARG JUPYTERHUB_VERSION=5.3.0

# Define the number of parallel jobs for builds
ARG CI_JOBS=14

# Define branches for each project to ensure reproducibility
ARG MOAB_BRANCH="5.5.1"
ARG DOUBLE_DOWN_BRANCH="v1.1.0"
ARG GEANT4_BRANCH="v11.3.0"
ARG DAGMC_BRANCH="v3.2.4"
ARG LIBMESH_BRANCH="v1.8.1"
ARG NJOY2016_BRANCH="2016.78"
ARG OPENMC_BRANCH="v0.15.2"
ARG KDSOURCE_BRANCH="v0.1.0"
ARG PYNE_BRANCH="scikit-build-core"

# Define whether to download Geant4 data and cross-section data
ARG DOWNLOAD_GEANT4_DATA=ON
ARG DOWNLOAD_CROSS_SECTION_DATA=ON

###########################################################################
#                              Initial Setup                              #
###########################################################################

# Set the base image for the Dockerfile
FROM $BASE_IMAGE

# Image Metadata and Build-time Arguments
LABEL maintainer="NukeLab <nukehub.org>"
ARG LAB_USER="nukelab"
ARG LAB_UID="1000"
ARG LAB_GID="100"

# Work as root for system-wide installations
USER root
WORKDIR /root
ENV HOME=/root

# Use non-interactive mode for automated builds
ENV DEBIAN_FRONTEND=noninteractive

# Install all OS dependencies
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        # Build Toolchain
        build-essential \
        gfortran \
        cmake \
        autoconf \
        pkg-config \
        m4 \
        # Core Utilities
        git \
        wget \
        ca-certificates \
        locales \
        # Scientific and Numerical Libraries
        libblas-dev \
        liblapack-dev \
        libeigen3-dev \
        libboost-dev \
        libboost-tools-dev \
        libhdf5-dev \
        libembree-dev \
        libxml2-dev \
        libpng-dev \
        # Graphics and Visualization Libraries
        libxft-dev \
        libxext-dev \
        libglu1-mesa-dev \
        # Supporting Applications and Runtimes
        ffmpeg \
        gmsh && \
    # Remove downloaded package files to reduce the final image size.
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    # Configure the system's locale to en_US.UTF-8.
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

# Configure core environment variables for Conda and the user
ENV CONDA_DIR=/opt/conda \
    SHELL=/bin/bash \
    LAB_USER=${LAB_USER} \
    LAB_UID=${LAB_UID} \
    LAB_GID=${LAB_GID} \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8
ENV PATH=${CONDA_DIR}/bin:${PATH}

# Install Miniforge to manage Python environments
RUN wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O Miniforge3.sh && \
    bash Miniforge3.sh -b -p $CONDA_DIR && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/profile.d/conda.sh && \
    rm Miniforge3.sh

# Install Jupyter ecosystem packages into the base Conda environment
ARG JUPYTERHUB_VERSION
RUN mamba install --yes \
        "jupyterhub==${JUPYTERHUB_VERSION}" \
        jupyterlab \
        jupyter-server-proxy \
        nodejs && \
    # Use npm to install yarn globally
    npm install -g yarn && \
    jupyter server --generate-config && \
    # Clean up mamba and npm caches to reduce image size
    mamba clean --all -f -y && \
    npm cache clean --force

# Copy Jupyter server configuration
COPY jupyter_server_config.py /etc/jupyter/

# Expose the Jupyter server port and set environment variables
ENV JUPYTER_PORT=8888
EXPOSE $JUPYTER_PORT

# Install and build the nuke-ide extension
RUN cd /opt && \
    git clone https://github.com/nukehub-dev/nuke-ide.git && \
    cd nuke-ide && \
    yarn && \
    yarn download:plugins && \
    yarn build:browser

# Set the Theia webview endpoint for rendering notebook outputs
ENV THEIA_WEBVIEW_EXTERNAL_ENDPOINT={{hostname}}

###########################################################################
#                              Nuclear Pack                               #
###########################################################################

ARG CI_JOBS

# Define installation root directories for each project
ENV NUKE_DIR=/opt/nuke \
    MOAB_ROOT=/opt/moab \
    DOUBLE_DOWN_ROOT=/opt/double-down \
    GEANT4_ROOT=/opt/geant4 \
    DAGMC_ROOT=/opt/dagmc \
    LIBMESH_ROOT=/opt/libmesh \
    NJOY2016_ROOT=/opt/njoy2016 \
    OPENMC_ROOT=/opt/openmc \
    KDSOURCE_ROOT=/opt/kdsource

# Configure search paths for compilers and the dynamic linker
ENV PATH="${NUKE_DIR}/bin:${MOAB_ROOT}/bin:${DOUBLE_DOWN_ROOT}/lib:${GEANT4_ROOT}/bin:${DAGMC_ROOT}/bin:${LIBMESH_ROOT}/bin:${NJOY2016_ROOT}/bin:${OPENMC_ROOT}/bin:${KDSOURCE_ROOT}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${MOAB_ROOT}/lib:${DOUBLE_DOWN_ROOT}/lib:${GEANT4_ROOT}/lib:${DAGMC_ROOT}/lib:${LIBMESH_ROOT}/lib:${NJOY2016_ROOT}/lib:${OPENMC_ROOT}/lib:${KDSOURCE_ROOT}/lib"

# Create the dedicated Conda environment for the nuclear codes
ARG PYTHON_VERSION
RUN conda create --yes -p ${NUKE_DIR} \
        python=${PYTHON_VERSION} \
        ipykernel \
        xeus-cling && \
    conda clean --all -f -y && \
    echo "conda activate ${NUKE_DIR}" >> /etc/profile.d/conda.sh

# Install MOAB
ARG MOAB_BRANCH
RUN git clone -b ${MOAB_BRANCH} --depth 1 https://bitbucket.org/fathomteam/moab && \
    cd moab && \
    mkdir build && cd build && \
    pip install --no-cache-dir \
        numpy \
        cython && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${MOAB_ROOT} \
        -DENABLE_HDF5=ON \
        -DBUILD_SHARED_LIBS=ON \
        -DENABLE_PYMOAB=OFF && \
    make -j${CI_JOBS} && make install && \
    pip uninstall --yes cython && \
    rm -rf ${HOME}/moab

# Install Double-Down
ARG DOUBLE_DOWN_BRANCH
RUN git clone -b ${DOUBLE_DOWN_BRANCH} https://github.com/pshriwise/double-down.git && \
    cd double-down && \
    mkdir build && cd build && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${DOUBLE_DOWN_ROOT} \
        -DMOAB_DIR=${MOAB_ROOT} && \
    make -j${CI_JOBS} && make install && \
    rm -rf ${HOME}/double-down

# Install Geant4
ARG GEANT4_BRANCH
ARG DOWNLOAD_GEANT4_DATA
ENV GEANT4_DATA_DIR=${GEANT4_ROOT}/share/data
RUN mkdir geant4 && cd geant4 && \
    wget https://github.com/Geant4/geant4/archive/refs/tags/${GEANT4_BRANCH}.tar.gz && \
    tar -xzvf ${GEANT4_BRANCH}.tar.gz && \
    cd $(tar tzf ${GEANT4_BRANCH}.tar.gz | head -1 | cut -f1 -d"/") && \
    mkdir -p build && \
    cd build && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${GEANT4_ROOT} \
        -DGEANT4_USE_QT=OFF \
        -DGEANT4_USE_OPENGL_X11=OFF \
        -DGEANT4_USE_SYSTEM_EXPAT=OFF \
        -DGEANT4_BUILD_TLS_MODEL=global-dynamic \
        -DGEANT4_BUILD_MULTITHREADED=ON \
        -DGEANT4_INSTALL_DATA=${DOWNLOAD_GEANT4_DATA} \
        -DGEANT4_INSTALL_DATADIR=${GEANT4_DATA_DIR} \
        -DGEANT4_INSTALL_DATA_TIMEOUT=0 && \
    make -j${CI_JOBS} && make install && \
    rm -rf ${HOME}/geant4

# Install DAGMC
ARG DAGMC_BRANCH
RUN git clone -b ${DAGMC_BRANCH} https://github.com/svalinn/DAGMC.git && \
    cd DAGMC && \
    mkdir build && cd build && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${DAGMC_ROOT} \
        -DMOAB_DIR=${MOAB_ROOT} \
        -DBUILD_GEANT4=ON \
        -DGEANT4_DIR=${GEANT4_ROOT} \
        -DDOUBLE_DOWN=ON \
        -Ddd_ROOT=${DOUBLE_DOWN_ROOT} && \
    make -j${CI_JOBS} && make install && \
    rm -rf ${HOME}/DAGMC

# Install LibMesh
ARG LIBMESH_BRANCH
RUN git clone --depth 1 -b ${LIBMESH_BRANCH} https://github.com/libMesh/libmesh.git && \
    cd libmesh && \
    git submodule update --init --recursive && \
    mkdir build && cd build && \
    ../configure \
        --prefix=${LIBMESH_ROOT} \
        --disable-mpi && \
    make -j${CI_JOBS} && make install && \
    rm -rf ${HOME}/libmesh

# Install NJOY2016
ARG NJOY2016_BRANCH
RUN git clone --depth 1 -b ${NJOY2016_BRANCH} https://github.com/njoy/NJOY2016.git && \
    cd NJOY2016 && \
    mkdir build && cd build && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${NJOY2016_ROOT} && \
    make -j${CI_JOBS} && make install && \
    rm -rf ${HOME}/NJOY2016

# Install OpenMC
ARG OPENMC_BRANCH
RUN git clone -b ${OPENMC_BRANCH} https://github.com/openmc-dev/openmc.git && \
    cd openmc && mkdir build && cd build && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${OPENMC_ROOT} \
        -DOPENMC_USE_DAGMC=ON \
        -DDAGMC_DIR=${DAGMC_ROOT} \
        -DOPENMC_USE_LIBMESH=ON \
        -DCMAKE_PREFIX_PATH=${LIBMESH_ROOT} && \
    make -j${CI_JOBS} && make install && \
    cd .. && pip install --no-cache-dir . && \
    rm -rf ${HOME}/openmc

# Download cross-section data using the system shell
ARG DOWNLOAD_CROSS_SECTION_DATA
ENV OPENMC_DATA_DIR=/opt/openmc_data
ENV OPENMC_CROSS_SECTIONS=${OPENMC_DATA_DIR}/lib80x_hdf5/cross_sections.xml
COPY download_cross_sections.sh .
RUN ./download_cross_sections.sh ${DOWNLOAD_CROSS_SECTION_DATA} ${OPENMC_DATA_DIR} && \
    rm download_cross_sections.sh

# Install PyNE
ARG PYNE_BRANCH
RUN git clone -b ${PYNE_BRANCH} https://github.com/pyne/pyne.git && \
    cd pyne && \
    export SKBUILD_CMAKE_ARGS="-DDOWNLOAD_EIGEN3=OFF; \
        -DDOWNLOAD_LAPACK=OFF; \
        -DDOWNLOAD_BLAS=OFF; \
        -DDOWNLOAD_HDF5=OFF; \
        -DDOWNLOAD_MOAB=OFF; \
        -DMOAB_ROOT=${MOAB_ROOT}; \
        -DDOWNLOAD_DAGMC=OFF; \
        -DDAGMC_ROOT=${DAGMC_ROOT}" && \
    pip -v install --no-cache-dir . && \
    nuc_data_make && \
    cd .. && rm -rf pyne

# Install KDSource
ARG KDSOURCE_BRANCH
RUN git clone -b ${KDSOURCE_BRANCH} --recurse-submodules https://github.com/KDSource/KDSource.git && \
    cd KDSource && mkdir build && cd build && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${KDSOURCE_ROOT} && \
    make -j${CI_JOBS} && make install && \
    rm -rf ${HOME}/KDSource

# Install remaining Python packages from PyPI and GitHub
RUN pip install --no-cache-dir \
        --extra-index-url https://shimwell.github.io/wheels moab \
        mcpl \
        ncrystal \
        paramak \
        plasmapy \
        cad_to_dagmc \
        geant4-pybind \
        vmecpp \
        git+https://github.com/svalinn/pydagmc


###########################################################################
#                     Final User and Permission Setup                     #
###########################################################################

# Create the non-root user and set its home directory
ENV HOME=/home/${LAB_USER}
RUN useradd --no-log-init --create-home --shell ${SHELL} \
        --uid ${LAB_UID} \
        --gid ${LAB_GID} \
        --no-user-group \
        ${LAB_USER} && \
    # Remove the temporary root home directory
    rm -rf /root && \
    # Create a working directory for the user
    mkdir -p ${HOME}/work && \
    # Grant user ownership of its home directory and nuke-ide plugins
    chown -R ${LAB_UID}:${LAB_GID} ${HOME} /opt/nuke-ide/plugins

# Copy and set permissions for the container entrypoint
COPY entrypoint.sh /etc/entrypoint.sh
RUN chmod +x /etc/entrypoint.sh

###########################################################################
#                                Execution                                #
###########################################################################

# Switch to the non-root user for security
USER ${LAB_UID}
WORKDIR ${HOME}/work

# Set the entrypoint script to initialize the environment
ENTRYPOINT ["/etc/entrypoint.sh"]

# Set the default command to start the Jupyter single-user server
CMD ["jupyterhub-singleuser"]