# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

# Define the base image for the Dockerfile
ARG BASE_IMAGE=nukelab-workspace:latest

# Define the Python version
ARG PYTHON_VERSION=3.13

# Define the number of parallel jobs for builds
ARG CI_JOBS=14

# Define branches for each project to ensure reproducibility
ARG MOAB_BRANCH="5.5.1"
ARG DOUBLE_DOWN_BRANCH="v1.1.0"
ARG GEANT4_BRANCH="v11.4.2"
ARG DAGMC_BRANCH="v3.2.4"
ARG LIBMESH_BRANCH="v1.8.4"
ARG NJOY2016_BRANCH="2016.79"
ARG OPENMC_BRANCH="v0.15.3"
ARG KDSOURCE_BRANCH="v0.2.2"
ARG PYNE_BRANCH="scikit-build-core"

# Define whether to download Geant4 data and cross-section data
ARG DOWNLOAD_GEANT4_DATA=ON
ARG DOWNLOAD_CROSS_SECTION_DATA=ON

###########################################################################
#                              Initial Setup                              #
###########################################################################

# Set the base image for the Dockerfile
FROM $BASE_IMAGE

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
        wget \
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
        gmsh && \
    # Remove downloaded package files to reduce the final image size.
    apt-get clean && rm -rf /var/lib/apt/lists/*

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
        xeus-cling \
        paraview \
        pythonocc-core && \
    conda clean --all -f -y

# Activate the nuclear conda environment in login shells (terminals).
COPY nuke-env.sh /etc/profile.d/nukelab-nuke-env.sh

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
        -DCMAKE_BUILD_TYPE=Release && \
    make -j${CI_JOBS} && \
    mkdir -p ${NJOY2016_ROOT}/bin && \
    cp njoy ${NJOY2016_ROOT}/bin/ && \
    cd .. && rm -rf ${HOME}/NJOY2016

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
        --extra-index-url https://shimwell.github.io/wheels \
        trame \
        moab \
        montepy \
        mcpl \
        ncrystal \
        paramak \
        plasmapy \
        geant4-pybind \
        vmecpp \
        git+https://github.com/svalinn/pydagmc
