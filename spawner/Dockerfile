# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

# Use the Debian image as a base
ARG BASE_IMAGE=debian:12
FROM $BASE_IMAGE

LABEL maintainer="NukeLab <nukehub.org>"
ARG LAB_USER="nukelab"
ARG LAB_UID="1000"
ARG LAB_GID="100"

# Work as root
USER root
WORKDIR /root
ENV HOME=/root

# Use non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Install all OS dependencies
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    git \
    wget \
    ca-certificates \
    locales && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

# Configure environment
ENV CONDA_DIR=/opt/conda \
    SHELL=/bin/bash \
    LAB_USER="${LAB_USER}" \
    LAB_UID=${LAB_UID} \
    LAB_GID=${LAB_GID} \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8
ENV PATH="${CONDA_DIR}/bin:${PATH}" \
    LD_LIBRARY_PATH=/opt/conda/lib:$LD_LIBRARY_PATH

# Install miniforge
RUN wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O Miniforge3.sh && \
    bash Miniforge3.sh -b -p $CONDA_DIR && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/profile.d/conda.sh && \
    rm Miniforge3.sh

# Install basic dependencies using mamba
RUN mamba install --yes \
        "jupyterhub==5.3.0" \
        gcc \  
        gxx \
        gfortran \
        binutils \
        make \
        cmake \
        autoconf \
        pkg-config \
        nodejs \
        jupyterlab \
        jupyter-server-proxy \
        xeus-cling && \
    npm install -g yarn && \
    jupyter server --generate-config && \
    mamba clean --all -f -y && \
    npm cache clean --force

# Copy jupyter server configuration
COPY jupyter_server_config.py /etc/jupyter/

# Expose the jupyter server port
ENV JUPYTER_PORT=8888
EXPOSE $JUPYTER_PORT

# Install nuke-ide
RUN cd /opt && \
    git clone https://github.com/nukehub-dev/nuke-ide.git && \
    cd nuke-ide && \
    yarn && \
    yarn download:plugins && \
    yarn build:browser

# Set theia webview endpoint (required for notebook output rendering)
ENV THEIA_WEBVIEW_EXTERNAL_ENDPOINT={{hostname}}

##################################################################
#                             Nuclear Pack                       #
##################################################################

# Set nuke directory
ENV NUKE_DIR=/opt/nuke

# Set build arguments
ARG CI_JOBS=14
ARG MOAB_BRANCH="5.5.1"
ARG DOUBLE_DOWN_BRANCH="v1.1.0"
ARG GEANT4_BRANCH="v11.3.0"
ARG DAGMC_BRANCH="v3.2.4"
ARG LIBMESH_BRANCH="v1.7.7"
ARG OPENMC_BRANCH="v0.15.1"
ARG KDSOURCE_BRANCH="v0.1.0"
ARG PYNE_BRANCH="scikit-build-core"
ARG DOWNLOAD_GEANT4_DATA=ON
ARG DOWNLOAD_CROSS_SECTION_DATA=ON

ENV MOAB_ROOT=${NUKE_DIR} \
    DOUBLE_DOWN_ROOT=${NUKE_DIR} \
    GEANT4_ROOT=${NUKE_DIR} \
    DAGMC_ROOT=${NUKE_DIR} \
    LIBMESH_ROOT=${NUKE_DIR}/libmesh \
    OPENMC_ROOT=${NUKE_DIR} \
    KDSOURCE_ROOT=${NUKE_DIR}

ENV GEANT4_DATA_DIR=${GEANT4_ROOT}/share/data \
    OPENMC_CROSS_SECTIONS=${OPENMC_ROOT}/share/data/lib80x_hdf5/cross_sections.xml \
    ENDFB70=${OPENMC_ROOT}/share/endfb70/cross_sections.xml \
    ENDFB71=${OPENMC_ROOT}/share/data/endfb71/cross_sections.xml \
    LIB80X=${OPENMC_ROOT}/share/data/lib80x_hdf5/cross_sections.xml 

# Install essential tools
RUN mamba install --yes \
        cython \
        blas \
        lapack \
        eigen \
        boost \
        openmp \
        hdf5 \
        embree \
        libxml2 \
        libpng \
        xvfbwrapper \
        xorg-libxft \
        xorg-libxext \
        mesa \
        ffmpeg \
        gmsh \
        m4 \
        njoy2016 \
        mcpl && \
        mamba clean --all -f -y

# Create a Conda environment in ${NUKE_DIR}
RUN conda create --yes -p ${NUKE_DIR} python=3.12 && \
    conda clean --all -f -y && \
    echo "conda activate ${NUKE_DIR}" >> /etc/profile.d/conda.sh

# Set the shell to use the nuke conda environment
SHELL ["conda", "run", "-p", "${NUKE_DIR}", "/bin/bash", "-c"]

# Install MOAB from source
RUN git clone -b ${MOAB_BRANCH} --depth 1 https://bitbucket.org/fathomteam/moab && \
    cd moab && \
    mkdir -p build && \
    cd build && \
    cmake ../ \
        -DENABLE_HDF5=ON \
        -DBUILD_SHARED_LIBS=ON \
        -DENABLE_PYMOAB=ON \
        -DENABLE_BLASLAPACK=OFF \
        -DENABLE_FORTRAN=OFF \
        -DCMAKE_INSTALL_PREFIX=${MOAB_ROOT} \
        -DCMAKE_PREFIX_PATH=${CONDA_DIR} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf moab

# Performed after moab install as double-down requires moab
RUN git clone -b ${DOUBLE_DOWN_BRANCH} https://github.com/pshriwise/double-down.git && \
    cd double-down && \
    mkdir -p build && \
    cd build && \
    cmake ../ \
        -DMOAB_DIR=${MOAB_ROOT} \
        -DCMAKE_INSTALL_PREFIX=${DOUBLE_DOWN_ROOT} \
        -DCMAKE_PREFIX_PATH=${CONDA_DIR} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf double-down

# Install Geant4 from source
RUN mkdir -p geant4 && \
    cd geant4 && \
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
        -DGEANT4_INSTALL_DATADIR=${GEANT4_ROOT}/share/data \
        -DGEANT4_INSTALL_DATA_TIMEOUT=0 \
        -DCMAKE_PREFIX_PATH=${CONDA_DIR} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../../.. && \
    rm -rf geant4

# Install DAGMC from source
RUN git clone -b ${DAGMC_BRANCH} https://github.com/svalinn/DAGMC.git && \
    cd DAGMC && \
    mkdir -p build && \
    cd build && \
    cmake ../ \
        -DMOAB_DIR=${MOAB_ROOT} \
        -DHDF5_VERSION="1.14.0" \
        -DMOAB_CMAKE_CONFIG=${MOAB_ROOT}/lib/cmake/MOAB \
        -DCMAKE_INSTALL_PREFIX=${DAGMC_ROOT} \
        -DBUILD_GEANT4=ON \
        -DGEANT4_DIR=${GEANT4_ROOT} \
        -DBUILD_TALLY=ON \
        -DBUILD_STATIC_LIBS=OFF \
        -DDOUBLE_DOWN=ON \
        -Ddd_ROOT=${DOUBLE_DOWN_ROOT} \
        -DCMAKE_PREFIX_PATH=${CONDA_DIR} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf DAGMC

# Install LibMesh from source
RUN git clone --depth 1 -b ${LIBMESH_BRANCH} https://github.com/libMesh/libmesh.git libmesh && \
    cd libmesh && \
    git submodule update --init --recursive && \
    mkdir build && cd build && \
    export METHODS="opt" && \
    ../configure \
        --disable-mpi \
        --prefix=${LIBMESH_ROOT} \
        --enable-exodus \
        --disable-netcdf-4 \
        --disable-eigen \
        --disable-lapack && \
    make -j$(nproc) && make install && \
    cd ../.. && \
    rm -rf libmesh

COPY download_cross_sections.sh .

# Install OpenMC from source
RUN git clone -b ${OPENMC_BRANCH} https://github.com/openmc-dev/openmc.git && \
    cd openmc && \
    mkdir -p build && \
    cd build && \
    cmake ../ \ 
        -DCMAKE_INSTALL_PREFIX=${OPENMC_ROOT} \
        -DHDF5_VERSION="1.14.0" \
        -DOPENMC_USE_OPENMP=ON \
        -DOPENMC_USE_LIBMESH=ON \
        -DOPENMC_USE_MCPL=ON \
        -DOPENMC_USE_DAGMC=ON \
        -DOPENMC_USE_UWUW=ON \
        -DCMAKE_PREFIX_PATH="${CONDA_DIR};${LIBMESH_ROOT}" && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd .. && \
    pip install --no-cache-dir . && \
    cd .. && \
    rm -rf openmc && \
    chmod +x download_cross_sections.sh && \
    ./download_cross_sections.sh ${DOWNLOAD_CROSS_SECTION_DATA} ${OPENMC_ROOT}/share/data && \
    rm download_cross_sections.sh

# Install PyNE from source
RUN git clone -b ${PYNE_BRANCH} https://github.com/pyne/pyne.git && \
    cd pyne && \
    export SKBUILD_CMAKE_ARGS="-DDOWNLOAD_EIGEN3=OFF; \
        -DDOWNLOAD_LAPACK=OFF; \
        -DDOWNLOAD_BLAS=OFF; \
        -DDOWNLOAD_HDF5=OFF; \
        -DDOWNLOAD_MOAB=OFF; \
        -DDOWNLOAD_DAGMC=OFF" && \
    pip -v install --no-cache-dir . && \
    nuc_data_make && \
    cd .. && \
    rm -rf pyne

# Install KDSource from source
RUN git clone -b ${KDSOURCE_BRANCH} --recurse-submodules https://github.com/KDSource/KDSource.git && \
    cd KDSource && \
    mkdir -p build && \
    cd build && \
    cmake ../ \
        -DCMAKE_INSTALL_PREFIX=${KDSOURCE_ROOT} \
        -DCMAKE_PREFIX_PATH=${CONDA_DIR} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf KDSource

# Install different python packages
RUN pip install --no-cache-dir \
        paramak \
        plasmapy \
        stellarmesh \
        cad_to_dagmc \
        geant4-pybind \
        git+https://github.com/proximafusion/vmecpp \
        git+https://github.com/svalinn/pydagmc


# Create a non-root user
ENV HOME=/home/${LAB_USER}
RUN useradd --no-log-init \
        --create-home \
        --shell ${SHELL} \
        --uid ${LAB_UID} \
        --gid ${LAB_GID} \
        --no-user-group \
        ${LAB_USER} && \
    rm -rf /root && \
    mkdir -p ${HOME}/work && \
    chown -R ${LAB_UID}:${LAB_GID} ${HOME}

# Copy the entrypoint script and make it executable
COPY entrypoint.sh /etc/entrypoint.sh
RUN chmod +x /etc/entrypoint.sh

# Start jupyter server as the non-root user
USER ${LAB_UID}
WORKDIR ${HOME}/work

# Set the entrypoint script
ENTRYPOINT ["/etc/entrypoint.sh"]

# Default command to start JupyterHub
CMD ["jupyterhub-singleuser"]
