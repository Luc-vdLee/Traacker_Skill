#!/usr/bin/env bash
set -eu
python3 "$(dirname "$0")/../make_fixture.py" . no-summary
cd trailmix
