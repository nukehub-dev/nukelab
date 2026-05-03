#!/bin/bash

# Start ttyd in background
ttyd --writable -p 7681 bash -i &

# Start nginx in foreground
nginx -g 'daemon off;'