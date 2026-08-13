#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Download OpenMC depletion chain files.
#
# Usage:
#   download_chain_files.sh <ON|OFF> <target_directory>
#
# When the first argument is ON, chain XML files are downloaded into
# <target_directory>/chain/. The default OpenMC chain file environment
# variable should point to one of these files.

set -euo pipefail

download_chain_data=${1:-OFF}
chain_data_dir=${2:-/opt/openmc_data}

if [ "$download_chain_data" == "ON" ]; then
    mkdir -p "${chain_data_dir}/chain"
    cd "${chain_data_dir}/chain"

    # ENDF/B-VIII.0 depletion chains (thermal and fast spectrum).
    # These pair with the LANL ENDF/B-VIII.0 (lib80x) cross-section library.
    wget -O chain_endfb80_thermal.xml "https://anl.box.com/shared/static/nyezmyuofd4eqt6wzd626lqth7wvpprr.xml"
    wget -O chain_endfb80_fast.xml "https://anl.box.com/shared/static/x3kp739hr5upmeqpbwx9zk9ep04fnmtg.xml"

    # ENDF/B-VIII.1 depletion chains.
    wget -O chain_endfb81_thermal.xml "https://anl.box.com/shared/static/q6ev8pl7xct179ke7kq148smde8gzni6.xml"
    wget -O chain_endfb81_fast.xml "https://anl.box.com/shared/static/n0pkqe66uotskoljr93szvjyvtvycgze.xml"
fi
