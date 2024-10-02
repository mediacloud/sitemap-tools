#!/bin/sh

# invoked from .pre-commit-config.yaml to run mypy
LOG=$0.log
date > $LOG
echo -- $0 $* >> $LOG
#env >> /tmp/xxx.log
TMP=$0.tmp
if ! cmp -s pyproject.toml $TMP; then
    pip install '.[mypy]'
    cp -p pyproject.toml $TMP
fi
#pip list >> /tmp/xxx.log
# NOTE! first arg must be command to invoke!
"$@"
