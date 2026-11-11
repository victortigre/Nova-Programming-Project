#!/bin/sh
# Stops secrets (API keys, passwords, connection strings, secrets files)
# from being committed. The rules are explained in AGENTS.md.
#
#   check-secrets.sh                  check the staged changes (used by pre-commit)
#   check-secrets.sh --all            check every file as it is in the latest commit
#   check-secrets.sh --commits A..B   check each commit in a range, one by one, so a
#                                     key that was added and deleted again is found
#
# False alarm? Put the words  not-a-secret  in a comment on that line.

EMPTY_TREE=4b825dc642cb6eb9a060e54bf8d69288fbee4904

FROM=""     # empty = compare the staged changes
TO=""
WHERE=""    # extra text for the report, e.g. which commit
fail=0

gdiff() {
    if [ -n "$TO" ]; then
        git -c core.quotepath=false diff --no-ext-diff "$FROM" "$TO" "$@"
    else
        git -c core.quotepath=false diff --no-ext-diff --cached "$@"
    fi
}

# If git itself fails, stop rather than let something through unchecked.
cannot_run() {
    echo "Secret check could not run - stopped."
    exit 1
}

report() {
    echo "  BLOCKED  $1$WHERE"
    echo "           $2"
    fail=1
}

# Example files hold placeholder values, so the two loose rules skip them.
is_example() {
    case "$1" in
        *.example|*.sample|*.template|*.example.*) return 0 ;;
        *) return 1 ;;
    esac
}

# Files that must never be committed.
FORBIDDEN='(^|/)(\.env(\.[^/]*)?|\.envrc|secrets\.(toml|ya?ml|json)|credentials\.json|service[-_]?account[^/]*\.json|id_(rsa|dsa|ecdsa|ed25519)|[^/]*\.(pem|key|p12|pfx|keystore))$'
ALLOWED='\.env\.(example|sample|template)$'

check() {
    # $1 = file, $2 = rule name, $3 = pattern, $4 = extra grep flag (optional)
    if printf '%s\n' "$added" | grep -E -q $4 -e "$3"; then
        report "$1" "looks like: $2"
    fi
}

# Checks one set of changes (whatever gdiff currently points at).
scan() {
    files=$(gdiff --name-only --diff-filter=ACMR) || cannot_run

    OLDIFS=$IFS
    IFS='
'
    for f in $files; do
        # git puts quotes around names it cannot print; we could not look
        # inside such a file, so refuse it instead of skipping it.
        case "$f" in
            \"*) report "$f" "file name with unusual characters - rename it"; continue ;;
        esac

        if printf '%s\n' "$f" | grep -E -i -q -e "$FORBIDDEN" &&
           ! printf '%s\n' "$f" | grep -E -i -q -e "$ALLOWED"; then
            report "$f" "secrets file - keep it local, it belongs in .gitignore"
        fi

        added=$(gdiff -U0 --no-color -- "$f" | grep '^+' | grep -v '^+++' | grep -v 'not-a-secret')
        [ -z "$added" ] && continue

        check "$f" "API key (OpenAI / OpenRouter / Anthropic)" 'sk-[A-Za-z0-9_-]{20,}'
        check "$f" "GitHub token"            '(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'
        check "$f" "AWS access key"          'AKIA[0-9A-Z]{16}'
        check "$f" "Google API key"          'AIza[0-9A-Za-z_-]{35}'
        check "$f" "Slack token"             'xox[baprs]-[A-Za-z0-9-]{10,}'
        check "$f" "Hugging Face token"      'hf_[A-Za-z0-9]{30,}'
        check "$f" "Telegram bot token"      '[0-9]{8,10}:AA[A-Za-z0-9_-]{33}'
        check "$f" "webhook URL"             '(hooks\.slack\.com/services/[A-Za-z0-9]|discord(app)?\.com/api/webhooks/[0-9]+/)'
        check "$f" "private key"             'BEGIN [A-Z ]*PRIVATE KEY'

        if ! is_example "$f"; then
            check "$f" "database connection string with a password" \
                '(postgres(ql)?|mysql|mongodb(\+srv)?|redis|amqps?)://[^:/@[:space:]]+:[^@[:space:]]+@'
            check "$f" "key, token or password written directly in the code" \
                '(api[_-]?key|secret|token|passw(or)?d|pwd)[A-Za-z0-9_]*["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'[:space:]]{12,}["'"'"']' -i
        fi
    done
    IFS=$OLDIFS
}

# --- What to check ------------------------------------------------------------

MODE=$1
case "$MODE" in
    "")
        scan
        ;;
    --all)
        FROM=$EMPTY_TREE
        TO=HEAD
        scan
        ;;
    --commits)
        shift
        commits=$(git rev-list "$@") || cannot_run
        for c in $commits; do
            # Compare each commit with the one before it (the very first
            # commit has none, so compare it with "nothing").
            if git rev-parse -q --verify "$c^1" > /dev/null 2>&1; then
                FROM="$c^1"
            else
                FROM=$EMPTY_TREE
            fi
            TO=$c
            WHERE="   (commit $(git rev-parse --short "$c"))"
            scan
        done
        ;;
    *)
        echo "Usage: check-secrets.sh [--all | --commits <range>]"
        exit 1
        ;;
esac

# --- Result -------------------------------------------------------------------

if [ $fail -ne 0 ]; then
    echo ""
    if [ "$MODE" = "" ]; then
        echo "Secret check FAILED - nothing was committed."
        echo "Move the value into .env (ignored by git) and read it by name in the code."
    else
        echo "Secret check FAILED - a secret is in the repository or its history."
        echo "Deleting it is not enough, it stays in the history."
    fi
    echo "If a real key was ever pushed to GitHub: revoke it now and create a new one."
    echo "False alarm? Add a comment containing  not-a-secret  on that line."
    exit 1
fi

echo "Secret check passed."
exit 0
