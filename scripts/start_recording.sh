#!/bin/bash

# Array for Audio Recording: Lite Recorder
LITE_RECORDER=(
    "Audio Recording: Lite Recorder/ARAB"
    "Audio Recording: Lite Recorder/KMRO"
    "Audio Recording: Lite Recorder/KVNR"
    "Audio Recording: Lite Recorder/MCD"
    "Audio Recording: Lite Recorder/WGOS"
    "Audio Recording: Lite Recorder/WGSP"
    "Audio Recording: Lite Recorder/WIST"
    "Audio Recording: Lite Recorder/WMUZ - 1200 AM"
    "Audio Recording: Lite Recorder/WNZK - 680 AM"
    "Audio Recording: Lite Recorder/WOLS"
    "Audio Recording: Lite Recorder/WSGH"
    "Audio Recording: Lite Recorder/WSRP"
    "Audio Recording: Lite Recorder/WWFE - 670 AM"
    "Audio Recording: Lite Recorder/WYMY"
)

# Array for Audio Recording: Max Recorder
MAX_RECORDER=(
    "Audio Recording: Max Recorder/K229DB - 93"
    "Audio Recording: Max Recorder/KABA - 90"
    "Audio Recording: Max Recorder/KBIC - 105"
    "Audio Recording: Max Recorder/KBNL - 89"
    "Audio Recording: Max Recorder/KCKO - 107"
    "Audio Recording: Max Recorder/KCMT - 92"
    "Audio Recording: Max Recorder/KENO - 1460 AM"
    "Audio Recording: Max Recorder/KFUE - 106"
    "Audio Recording: Max Recorder/KMMA - 97"
    "Audio Recording: Max Recorder/KNNR - 1400 AM"
    "Audio Recording: Max Recorder/KNOG - 91"
    "Audio Recording: Max Recorder/KRMC - 91"
    "Audio Recording: Max Recorder/KWST - 1430 AM"
    "Audio Recording: Max Recorder/KYAR - 98"
    "Audio Recording: Max Recorder/KZLZ - 105"
    "Audio Recording: Max Recorder/RUMBA 4451"
    "Audio Recording: Max Recorder/SPMN"
    "Audio Recording: Max Recorder/WACC - 830 AM"
    "Audio Recording: Max Recorder/WAXY - 790 AM"
    "Audio Recording: Max Recorder/WBZW - 96"
    "Audio Recording: Max Recorder/WBZY - 105"
    "Audio Recording: Max Recorder/WDJA - 1420 AM"
    "Audio Recording: Max Recorder/WDTW - 1310 AM"
    "Audio Recording: Max Recorder/WLAZ - 89"
    "Audio Recording: Max Recorder/WLCH - 91"
    "Audio Recording: Max Recorder/WLEL - 94"
    "Audio Recording: Max Recorder/WLMV - 1480 AM"
    "Audio Recording: Max Recorder/WNMA - 1210 AM"
    "Audio Recording: Max Recorder/WOAP - 1080 AM"
    "Audio Recording: Max Recorder/WPHE - 690 AM"
    "Audio Recording: Max Recorder/WRUM - 100"
    "Audio Recording: Max Recorder/WRUM HD2 - 97"
    "Audio Recording: Max Recorder/WSDS - 1480 AM"
    "Audio Recording: Max Recorder/WSRF - 99"
    "Audio Recording: Max Recorder/WSUA - 1260 AM"
    "Audio Recording: Max Recorder/WUMR - 106"
    "Audio Recording: Max Recorder/WURN - 1040 AM"
    "Audio Recording: Max Recorder/WZHF"
    "Audio Recording: Max Recorder/WZTU - 94"
)

# Array for Generic Audio Recording
GENERIC_RECORDER=(
    "Generic Audio Recording/KHOT - 105"
    "Generic Audio Recording/KISF - 103"
    "Generic Audio Recording/KRGT - 99"
    "Generic Audio Recording/WADO - 1280 AM"
    "Generic Audio Recording/WAQI - 710 AM"
    "Generic Audio Recording/WKAQ - 580 AM"
)

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to start deployments from an array
start_deployments() {
    local deployments=("$@")
    for deployment in "${deployments[@]}"; do
        log "Starting: $deployment"
        if prefect deployment run "$deployment"; then
            log "Successfully started $deployment"
        else
            log "Failed to start $deployment"
        fi
        sleep 2
    done
}

# Start all deployments
log "Starting Lite Recorder deployments..."
start_deployments "${LITE_RECORDER[@]}"

log "Starting Max Recorder deployments..."
start_deployments "${MAX_RECORDER[@]}"

log "Starting Generic Audio Recording deployments..."
start_deployments "${GENERIC_RECORDER[@]}"
