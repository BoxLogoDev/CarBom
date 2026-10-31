#!/bin/bash
set -e
if [[ "$1" == "doctor" ]]; then
  echo doctor ok
  exit 0
elif [[ "$1" == "drive" ]]; then
  echo drive $2 ok
  exit 0
fi
