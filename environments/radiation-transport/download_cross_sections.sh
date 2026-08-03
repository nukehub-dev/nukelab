#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Download OpenMC cross-section data libraries.
#
# Usage:
#   download_cross_sections.sh <ON|OFF> <target_directory>
#
# When the first argument is ON, libraries are downloaded and extracted into
# <target_directory>/.

set -euo pipefail

# Assign command line arguments to variables
download_cross_section_data=${1:-OFF}
cross_section_data_lib=${2:-/opt/openmc_data}

if [ "$download_cross_section_data" == "ON" ]; then
    mkdir -p "${cross_section_data_lib}"
    cd "${cross_section_data_lib}"

    # Function to download and extract data
    download_and_extract() {
        local url=$1
        local filename
        filename=$(basename "$url")
        mkdir -p tmp
        cd tmp
        wget "$url"
        cd ..
        tar -Jxvf "tmp/${filename}"
        rm -rf tmp
    }

    # Current libraries are the LANL-based data sets distributed for use with
    # MCNP/OpenMC. They extract to mcnp_endfb70, mcnp_endfb71, and lib80x_hdf5.
    #
    # Newer official OpenMC-produced libraries are available from
    # https://openmc.org/data/ and may be substituted here. For example:
    #   - ENDF/B-VIII.0 official: https://anl.box.com/shared/static/uhbxlrx7hvxqw27psymfbhi7bx7s6u6a.xz
    #   - ENDF/B-VIII.1 official: https://anl.box.com/shared/static/6qr7jezzihkj9p9esl5jn19qgpujyjyz.xz
    # If switching libraries, update OPENMC_CROSS_SECTIONS in the Dockerfile to
    # match the extracted directory name and verify with a test build.
    download_and_extract "https://anl.box.com/shared/static/t25g7g6v0emygu50lr2ych1cf6o7454b.xz"
    download_and_extract "https://anl.box.com/shared/static/d359skd2w6wrm86om2997a1bxgigc8pu.xz"
    download_and_extract "https://anl.box.com/shared/static/nd7p4jherolkx4b1rfaw5uqp58nxtstr.xz"
fi
