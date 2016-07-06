#!/bin/bash

export PARALIFE_DEBUG=1
python -W ignore ./test_life.py
unset PARALIFE_DEBUG
