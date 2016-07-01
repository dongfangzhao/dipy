#!/bin/bash

./_update.sh
export PARALIFE_DEBUG=1
python ./test_life.py
unset PARALIFE_DEBUG
