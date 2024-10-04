#!/bin/sh

# invoked from .pre-commit-config.yaml to run mypy
LOG=$0.log
date > $LOG
echo $0 $* >> $LOG
env >> $LOG

# want to stash copy of pyproject.toml near pre-commit created virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    TMP=$VIRTUAL_ENV/pyproject.toml
else
    # try "which python3"? grab first PATH element??
    # hidden from view
    TMP=$0.tmp
fi
echo TMP $TMP >> $LOG

# saved copy of pyproject.toml:
if ! cmp -s pyproject.toml $TMP; then
    pip install '.[mypy]'
    cp -p pyproject.toml $TMP
fi
#pip list >> $LOG
# NOTE! first arg must be command to invoke!
"$@"
