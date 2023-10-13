# Copyright (c) Jupyter Development Team.
# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the Modified BSD License.

# Ubuntu 22.04 (jammy)
# https://hub.docker.com/_/ubuntu/tags?page=1&name=jammy
ARG ROOT_CONTAINER=ubuntu:22.04

FROM $ROOT_CONTAINER

LABEL maintainer="NukeLab <nrms.mist.ac.bd>"
ARG NB_USER="nukelab"
ARG NB_UID="1000"
ARG NB_GID="100"

# Fix: https://github.com/hadolint/hadolint/wiki/DL4006
# Fix: https://github.com/koalaman/shellcheck/wiki/SC3014
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root

# Install all OS dependencies for Server that starts
# but lacks all features (e.g., download as all possible file formats)
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update --yes && \
    # - apt-get upgrade is run to patch known vulnerabilities in apt-get packages as
    #   the ubuntu base image is rebuilt too seldom sometimes (less than once a month)
    apt-get upgrade --yes && \
    apt-get install --yes --no-install-recommends \
    build-essential \
    # - bzip2 is necessary to extract the micromamba executable.
    bzip2 \
    ca-certificates \
    locales \
    sudo \
    # - tini is installed as a helpful container entrypoint that reaps zombie
    #   processes and such of the actual executable we want to start, see
    #   https://github.com/krallin/tini#why-tini for details.
    tini \
    wget && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

# Configure environment
ENV CONDA_DIR=/opt/conda \
    SHELL=/bin/bash \
    NB_USER="${NB_USER}" \
    NB_UID=${NB_UID} \
    NB_GID=${NB_GID} \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8
ENV PATH="${CONDA_DIR}/bin:${PATH}" \
    HOME="/home/${NB_USER}"

# Copy a script that we will use to correct permissions after running certain commands
COPY fix-permissions /usr/local/bin/fix-permissions
RUN chmod a+rx /usr/local/bin/fix-permissions

# Enable prompt color in the skeleton .bashrc before creating the default NB_USER
# hadolint ignore=SC2016
RUN sed -i 's/^#force_color_prompt=yes/force_color_prompt=yes/' /etc/skel/.bashrc && \
   # Add call to conda init script see https://stackoverflow.com/a/58081608/4413446
   echo 'eval "$(command conda shell.bash hook 2> /dev/null)"' >> /etc/skel/.bashrc

# Create NB_USER with name nukelab user with UID=1000 and in the 'users' group
# and make sure these dirs are writable by the `users` group.
RUN echo "auth requisite pam_deny.so" >> /etc/pam.d/su && \
    sed -i.bak -e 's/^%admin/#%admin/' /etc/sudoers && \
    sed -i.bak -e 's/^%sudo/#%sudo/' /etc/sudoers && \
    useradd --no-log-init --create-home --shell /bin/bash --uid "${NB_UID}" --no-user-group "${NB_USER}" && \
    mkdir -p "${CONDA_DIR}" && \
    chown "${NB_USER}:${NB_GID}" "${CONDA_DIR}" && \
    chmod g+w /etc/passwd && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

USER ${NB_UID}

# Pin python version here, or set it to "default"
ARG PYTHON_VERSION=3.11

# Setup work directory for backward-compatibility
RUN mkdir "/home/${NB_USER}/work" && \
    fix-permissions "/home/${NB_USER}"

# Download and install Micromamba, and initialize Conda prefix.
#   <https://github.com/mamba-org/mamba#micromamba>
#   Similar projects using Micromamba:
#     - Micromamba-Docker: <https://github.com/mamba-org/micromamba-docker>
#     - repo2docker: <https://github.com/jupyterhub/repo2docker>
# Install Python, Mamba and jupyter_core
# Cleanup temporary files and remove Micromamba
# Correct permissions
# Do all this in a single RUN command to avoid duplicating all of the
# files across image layers when the permissions change
COPY --chown="${NB_UID}:${NB_GID}" initial-condarc "${CONDA_DIR}/.condarc"
WORKDIR /tmp
RUN set -x && \
    arch=$(uname -m) && \
    if [ "${arch}" = "x86_64" ]; then \
        # Should be simpler, see <https://github.com/mamba-org/mamba/issues/1437>
        arch="64"; \
    fi && \
    wget --progress=dot:giga -O /tmp/micromamba.tar.bz2 \
        "https://micromamba.snakepit.net/api/micromamba/linux-${arch}/latest" && \
    tar -xvjf /tmp/micromamba.tar.bz2 --strip-components=1 bin/micromamba && \
    rm /tmp/micromamba.tar.bz2 && \
    PYTHON_SPECIFIER="python=${PYTHON_VERSION}" && \
    if [[ "${PYTHON_VERSION}" == "default" ]]; then PYTHON_SPECIFIER="python"; fi && \
    # Install the packages
    ./micromamba install \
        --root-prefix="${CONDA_DIR}" \
        --prefix="${CONDA_DIR}" \
        --yes \
        "${PYTHON_SPECIFIER}" \
        'mamba' \
        'jupyter_core' && \
    rm micromamba && \
    # Pin major.minor version of python
    mamba list python | grep '^python ' | tr -s ' ' | cut -d ' ' -f 1,2 >> "${CONDA_DIR}/conda-meta/pinned" && \
    mamba clean --all -f -y && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

# Configure container startup
ENTRYPOINT ["tini", "-g", "--"]

# Copy local files as late as possible to avoid cache busting
COPY run-hooks.sh start.sh /usr/local/bin/

USER root

# Create dirs for startup hooks
RUN mkdir /usr/local/bin/start-notebook.d && \
    mkdir /usr/local/bin/before-notebook.d


##################################################################
#                        Base Notebook                           #
##################################################################

USER root

# Install all OS dependencies for Server that starts but lacks all
# features (e.g., download as all possible file formats)
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    fonts-liberation \
    # - pandoc is used to convert notebooks to html files
    #   it's not present in aarch64 ubuntu image, so we install it here
    pandoc \
    # - run-one - a wrapper script that runs no more
    #   than one unique  instance  of  some  command with a unique set of arguments,
    #   we use `run-one-constantly` to support `RESTARTABLE` option
    run-one && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# Install JupyterLab, Jupyter Notebook, JupyterHub and NBClassic
# Generate a Jupyter Server config
# Cleanup temporary files
# Correct permissions
# Do all this in a single RUN command to avoid duplicating all of the
# files across image layers when the permissions change
WORKDIR /tmp

# Install cadquery and gmsh first
RUN mamba install --yes \
    gmsh \
    cadquery && \
    mamba clean --all -f -y && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

RUN mamba install --yes \
    jupyterlab \
    notebook \
    jupyterhub \
    nbclassic && \
    jupyter server --generate-config && \
    mamba clean --all -f -y && \
    npm cache clean --force && \
    jupyter lab build --name='NukeLab' && \
    jupyter lab clean && \
    pip install --no-cache-dir \ 
    jupyter_ai \
    jupyterlab-lsp \
    jupyter-resource-usage \
    jupyter-cadquery \
    jupyter-collaboration && \
    jupyter labextension disable @jupyterlab/extensionmanager-extension && \
    rm -rf "/home/${NB_USER}/.cache/yarn" && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

ENV JUPYTER_PORT=8888
EXPOSE $JUPYTER_PORT

# Configure container startup
CMD ["start-notebook.sh"]

# Copy local files as late as possible to avoid cache busting
COPY start-notebook.sh start-singleuser.sh /usr/local/bin/
COPY jupyter_server_config.py docker_healthcheck.py /etc/jupyter/

# Fix permissions on /etc/jupyter as root
USER root
RUN fix-permissions /etc/jupyter/

# HEALTHCHECK documentation: https://docs.docker.com/engine/reference/builder/#healthcheck
# This healtcheck works well for `lab`, `notebook`, `nbclassic`, `server` and `retro` jupyter commands
# https://github.com/jupyter/docker-stacks/issues/915#issuecomment-1068528799
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
    CMD /etc/jupyter/docker_healthcheck.py || exit 1


##################################################################
#                        Minimal Notebook                        #
##################################################################

# Install all OS dependencies for fully functional Server
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    # Common useful utilities
    curl \
    git \
    nano-tiny \
    tzdata \
    unzip \
    vim-tiny \
    # git-over-ssh
    openssh-client \
    # less is needed to run help in R
    # see: https://github.com/jupyter/docker-stacks/issues/1588
    less \
    # nbconvert dependencies
    # https://nbconvert.readthedocs.io/en/latest/install.html#installing-tex
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-plain-generic \
    # Enable clipboard on Linux host systems
    xclip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create alternative for nano -> nano-tiny
RUN update-alternatives --install /usr/bin/nano nano /bin/nano-tiny 10

# Switch back to nukelab to avoid accidental container runs as root
USER ${NB_UID}

# Add R mimetype option to specify how the plot returns from R to the browser
COPY --chown=${NB_UID}:${NB_GID} Rprofile.site /opt/conda/lib/R/etc/

# Add setup scripts that may be used by downstream images or inherited images
COPY setup-scripts/ /opt/setup-scripts/


##################################################################
#                        Scipy Notebook                          #
##################################################################

USER root

RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    # for cython: https://cython.readthedocs.io/en/latest/src/quickstart/install.html
    build-essential \
    # for latex labels
    cm-super \
    dvipng \
    # for matplotlib anim
    ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# mamba downgrades these packages to previous major versions, which causes issues
RUN echo 'jupyterlab >=4.0.4' >> "${CONDA_DIR}/conda-meta/pinned" && \
    echo 'notebook >=7.0.2' >> "${CONDA_DIR}/conda-meta/pinned"

# Install Python 3 packages
RUN mamba install --yes \
    'altair' \
    'beautifulsoup4' \
    'bokeh' \
    'bottleneck' \
    'cloudpickle' \
    'conda-forge::blas=*=openblas' \
    'cython' \
    'dask' \
    'dill' \
    'h5py' \
    'ipympl'\
    'ipywidgets' \
    'jupyterlab-git' \
    'matplotlib-base' \
    'numba' \
    'numexpr' \
    'openpyxl' \
    'pandas' \
    'patsy' \
    'protobuf' \
    'pytables' \
    'scikit-image' \
    'scikit-learn' \
    'scipy' \
    'seaborn' \
    'sqlalchemy' \
    'statsmodels' \
    'sympy' \
    'widgetsnbextension'\
    'xlrd' && \
    mamba clean --all -f -y && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

# Install facets which does not have a pip or conda package at the moment
WORKDIR /tmp
RUN git clone https://github.com/PAIR-code/facets && \
    jupyter nbclassic-extension install facets/facets-dist/ --sys-prefix && \
    rm -rf /tmp/facets && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

# Import matplotlib the first time to build the font cache.
ENV XDG_CACHE_HOME="/home/${NB_USER}/.cache/"

RUN MPLBACKEND=Agg python -c "import matplotlib.pyplot" && \
    fix-permissions "/home/${NB_USER}"

# Install Tensorflow with pip
RUN pip install --no-cache-dir tensorflow && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

WORKDIR ${HOME}


##################################################################
#                        Data Science Notebook                   #
##################################################################

USER root

# R pre-requisites
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    fonts-dejavu \
    gfortran \
    gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Julia dependencies
# install Julia packages in /opt/julia instead of ${HOME}
ENV JULIA_DEPOT_PATH=/opt/julia \
    JULIA_PKGDIR=/opt/julia

# Setup Julia
RUN /opt/setup-scripts/setup-julia.bash

USER ${NB_UID}

# Setup IJulia kernel & other packages
RUN /opt/setup-scripts/setup-julia-packages.bash

# R packages including IRKernel which gets installed globally.
# r-e1071: dependency of the caret R package
RUN mamba install --yes \
    'r-base' \
    'r-caret' \
    'r-crayon' \
    'r-devtools' \
    'r-e1071' \
    'r-forecast' \
    'r-hexbin' \
    'r-htmltools' \
    'r-htmlwidgets' \
    'r-irkernel' \
    'r-nycflights13' \
    'r-randomforest' \
    'r-rcurl' \
    'r-rmarkdown' \
    'r-rodbc' \
    'r-rsqlite' \
    'r-shiny' \
    'r-tidymodels' \
    'r-tidyverse' \
    'rpy2' \
    'unixodbc' && \
    mamba clean --all -f -y && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"


##################################################################
#                             Nuclear Pack                       #
##################################################################

USER root

ARG CI_JOBS=4
ARG EMBREE_BRANCH="v3.6.1"
ARG MOAB_BRANCH=5.4.0
ARG DOUBLE_DOWN_BRANCH="v1.0.0"
ARG GEANT4_BRANCH="v11.1.2"
ARG DAGMC_BRANCH="v3.2.2"
ARG OPENMC_BRANCH="v0.13.1"
ARG PYNE_BRANCH="develop"
ARG DOWNLOAD_GEANT4_DATA=ON
ARG DOWNLOAD_CROSS_SECTION_DATA=ON

ENV MOAB_ROOT=${CONDA_DIR} \
    EMBREE_ROOT=${CONDA_DIR} \
    DOUBLE_DOWN_ROOT=${CONDA_DIR} \
    GEANT4_ROOT=${CONDA_DIR} \
    DAGMC_ROOT=${CONDA_DIR} \
    OPENMC_ROOT=${CONDA_DIR} \
    PYNE_ROOT=${CONDA_DIR} 

ENV GEANT4_DATA_DIR=${GEANT4_ROOT}/share/data \
    OPENMC_CROSS_SECTIONS=${OPENMC_ROOT}/share/data/lib80x_hdf5/cross_sections.xml \
    ENDFB70=${OPENMC_ROOT}/share/endfb70/cross_sections.xml \
    ENDFB71=${OPENMC_ROOT}/share/data/endfb71/cross_sections.xml \
    LIB80X=${OPENMC_ROOT}/share/data/lib80x_hdf5/cross_sections.xml 

# Install dependencies
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    software-properties-common \
    libblas-dev \
    liblapack-dev \
    libeigen3-dev \
    libboost-dev \
    xvfb \
    libxft2 \
    libxext6 \
    libglu1-mesa && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# Install python packages
RUN mamba install --yes \
    cmake \
    hdf5 \
    # DAGMC requires Cython<3
    "cython<3" \
    setuptools \
    progress \ 
    future && \
    mamba clean --all -f -y && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

USER root

ENV HDF5_ROOT=${CONDA_DIR}
ENV LD_LIBRARY_PATH=${HDF5_ROOT}:${CONDA_DIR}/lib

# Install MOAB from source
RUN git clone -b ${MOAB_BRANCH} --depth 1 https://bitbucket.org/fathomteam/moab && \
    cd moab && \
    mkdir -p build && \
    cd build && \
    cmake ../ -DENABLE_HDF5=ON -DHDF5_ROOT=${HDF5_ROOT} \
        -DBUILD_SHARED_LIBS=ON \
        -DENABLE_PYMOAB=ON \
        -DENABLE_BLASLAPACK=OFF \
        -DENABLE_FORTRAN=OFF \
        -DCMAKE_INSTALL_PREFIX=${MOAB_ROOT} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf moab && \
    fix-permissions "${MOAB_ROOT}" && \
    fix-permissions "/home/${NB_USER}"

# Install Embree from source
RUN git clone -b ${EMBREE_BRANCH} https://github.com/embree/embree && \
    cd embree && \
    mkdir -p build && \
    cd build && \
    cmake ../ -DCMAKE_INSTALL_PREFIX=${EMBREE_ROOT} \
        -DEMBREE_TASKING_SYSTEM=INTERNAL \
        -DEMBREE_ISPC_SUPPORT=OFF \
        -DEMBREE_TUTORIALS=OFF \
        -DEMBREE_TBB_ROOT=/usr && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf embree && \
    fix-permissions "${EMBREE_ROOT}" && \
    fix-permissions "/home/${NB_USER}"

# Performed after moab install as double-down requires moab
RUN git clone -b ${DOUBLE_DOWN_BRANCH} https://github.com/pshriwise/double-down.git && \
    cd double-down && \
    mkdir -p build && \
    cd build && \
    cmake ../ -DMOAB_DIR=${MOAB_ROOT} \
        -DCMAKE_INSTALL_PREFIX=${DOUBLE_DOWN_ROOT} \
        -DEMBREE_DIR=${EMBREE_ROOT} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf double-down && \
    fix-permissions "${DOUBLE_DOWN_ROOT}" && \
    fix-permissions "/home/${NB_USER}"

# Install Geant4 from source
RUN mkdir -p geant4 && \
    cd geant4 && \
    wget https://github.com/Geant4/geant4/archive/refs/tags/${GEANT4_BRANCH}.tar.gz && \
    tar -xzvf ${GEANT4_BRANCH}.tar.gz && \
    cd $(tar tzf ${GEANT4_BRANCH}.tar.gz | head -1 | cut -f1 -d"/") && \
    mkdir -p build && \
    cd build && \
    cmake ../ -DCMAKE_INSTALL_PREFIX=${GEANT4_ROOT} \
        -DGEANT4_USE_QT=OFF \
        -DGEANT4_USE_OPENGL_X11=OFF \
        -DGEANT4_USE_SYSTEM_EXPAT=OFF \
        -DGEANT4_BUILD_TLS_MODEL=global-dynamic \
        -DGEANT4_BUILD_MULTITHREADED=ON \
        -DGEANT4_INSTALL_DATA=${DOWNLOAD_GEANT4_DATA} \
        -DGEANT4_INSTALL_DATADIR=${GEANT4_ROOT}/share/data \
        -DGEANT4_INSTALL_DATA_TIMEOUT=0 && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../../.. && \
    rm -rf geant4 && \
    fix-permissions "${GEANT4_ROOT}" && \
    fix-permissions "/home/${NB_USER}"

# Install DAGMC from source
RUN git clone -b ${DAGMC_BRANCH} https://github.com/svalinn/DAGMC.git && \
    cd DAGMC && \
    mkdir -p build && \
    cd build && \
    cmake ../ -DMOAB_DIR=${MOAB_ROOT} \
        -DMOAB_CMAKE_CONFIG=${MOAB_ROOT}/lib/cmake/MOAB \
        -DCMAKE_INSTALL_PREFIX=${DAGMC_ROOT} \
        # Fix GEANT4 V 11 NOT WORKING WITH DAGMC
        -DBUILD_GEANT4=OFF \
        -DGEANT4_DIR=${GEANT4_ROOT} \
        -DGeant4_CMAKE_CONFIG=${GEANT4_ROOT}/lib/cmake/Geant4 \
        -DBUILD_TALLY=ON \
        -DBUILD_STATIC_LIBS=OFF \
        -DDOUBLE_DOWN=ON \
        -Ddd_ROOT=${DOUBLE_DOWN_ROOT} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf DAGMC && \
    fix-permissions "${DAGMC_ROOT}" && \
    fix-permissions "/home/${NB_USER}"

COPY download_cross_sections.sh ${HOME}/download_cross_sections.sh

# Install OpenMC from source
RUN git clone -b ${OPENMC_BRANCH} https://github.com/openmc-dev/openmc.git && \
    cd openmc && \
    mkdir -p build && \
    cd build && \
    cmake ../ -DCMAKE_INSTALL_PREFIX=${OPENMC_ROOT} \
    -DOPENMC_USE_DAGMC=ON \
    -DDAGMC_ROOT=${DAGMC_ROOT} && \
    make -j${CI_JOBS} && make -j${CI_JOBS} install && \
    cd ../.. && \
    rm -rf openmc && \
    chmod +x download_cross_sections.sh && \
    ./download_cross_sections.sh ${DOWNLOAD_CROSS_SECTION_DATA} ${OPENMC_ROOT}/share/data && \
    rm download_cross_sections.sh && \
    fix-permissions "${OPENMC_ROOT}" && \
    fix-permissions "/home/${NB_USER}"

# Install PyNE from source
RUN git clone -b ${PYNE_BRANCH} https://github.com/pyne/pyne.git && \
    cd pyne && \
    python3 setup.py install --prefix ${PYNE_ROOT} \
        --moab ${MOAB_ROOT} \
        --dagmc ${DAGMC_ROOT} \
        --clean && \
    mkdir -p tmp && \
    nuc_data_make && \
    cd ../.. && \
    rm -rf pyne && \
    fix-permissions "${PYNE_ROOT}" && \
    fix-permissions "/home/${NB_USER}"

# Switch back to nukelab to avoid accidental container runs as root
USER ${NB_UID}

# Install different python packages
RUN pip install --no-cache-dir \
    plasmapy \
    #paramak \ Fix It using lower version of client
    tables \
    yt \
    tabulate \
    requests \
    geant4-pybind \
    cad_to_dagmc \
    stellarmesh \
    git+https://github.com/gumyr/build123d \
    cad_to_openmc && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"
