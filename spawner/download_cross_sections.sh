#!/bin/bash

# Assign command line arguments to variables
download_cross_section_data=$1
cross_section_data_lib=$2

if [ "$download_cross_section_data" == "ON" ]; then
    mkdir -p ${cross_section_data_lib}
    cd ${cross_section_data_lib}
    # Function to download and extract data
    download_and_extract() {
        local url=$1
        local filename=$(basename $url)
        mkdir -p tmp
        cd tmp
        wget $url
        cd ..
        tar -Jxvf tmp/$filename
        rm -rf tmp
    }
    download_and_extract "https://anl.box.com/shared/static/t25g7g6v0emygu50lr2ych1cf6o7454b.xz"
    download_and_extract "https://anl.box.com/shared/static/t25g7g6v0emygu50lr2ych1cf6o7454b.xz"
    download_and_extract "https://anl.box.com/shared/static/d359skd2w6wrm86om2997a1bxgigc8pu.xz"
fi
