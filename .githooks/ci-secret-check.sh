#!/bin/sh
# Run by GitHub on every push (see .github/workflows/secret-check.yml).
#
# Checks the files as they are now AND every commit that was just pushed, one
# by one. The second part matters: a key that was committed and then deleted
# in a later commit is gone from the files but still readable in the history.
#
# GitHub passes these in as environment variables:
#   BEFORE          the commit the branch pointed at before this push
#   BASE_REF        the target branch (pull requests only)
#   DEFAULT_BRANCH  normally "main"
#   REF_NAME        the branch that was pushed

here=$(dirname "$0")
status=0

echo "== Files as they are now"
sh "$here/check-secrets.sh" --all || status=1

ZERO=0000000000000000000000000000000000000000

if [ -n "$BASE_REF" ]; then
    # Pull request: everything it adds on top of the target branch.
    set -- "origin/$BASE_REF..HEAD"
elif [ -n "$BEFORE" ] && [ "$BEFORE" != "$ZERO" ] &&
     git cat-file -e "$BEFORE^{commit}" 2> /dev/null; then
    # Normal push: the commits that are new since the last push.
    set -- "$BEFORE..HEAD"
elif [ -n "$DEFAULT_BRANCH" ] && [ "$REF_NAME" != "$DEFAULT_BRANCH" ] &&
     git rev-parse -q --verify "origin/$DEFAULT_BRANCH" > /dev/null 2>&1; then
    # New branch: everything that is not on the main branch yet.
    set -- "origin/$DEFAULT_BRANCH..HEAD"
else
    # First push, or the history was rewritten: check the whole history.
    set -- HEAD
fi

echo "== Each pushed commit ($*)"
sh "$here/check-secrets.sh" --commits "$@" || status=1

exit $status
