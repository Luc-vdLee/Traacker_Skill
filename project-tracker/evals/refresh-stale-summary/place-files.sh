#!/usr/bin/env bash
set -eu
python3 "$(dirname "$0")/../make_fixture.py" . stale-summary
cd trailmix
