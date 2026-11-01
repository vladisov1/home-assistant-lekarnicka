#!/bin/sh
set -eu
mkdir -p /data
exec gunicorn --bind 0.0.0.0:8099 --workers 1 --threads 4 --access-logfile - app:app
