#!/bin/bash

###############################################################################
# Advanced Vulnerability Script
# Uses jq for simple and fast processing
# Data source: Red Hat Security Advisory API
###############################################################################

set -euo pipefail

# Color codes
RED='\033[0;31m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

usage() {
    echo "Usage: $0 <version> [format]"
    echo "Formats: table, csv, json"
    echo "Examples:"
    echo "  $0 4.21"
    echo "  $0 4.12 csv"
    exit 1
}

# parse optional flags and positional args
ADVISORY_PREFIXES=''
PARSED=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --advisory-prefix)
            if [ "$#" -lt 2 ]; then
                echo "Usage: $0 --advisory-prefix PREFIXES <version> [format]" >&2
                exit 1
            fi
            ADVISORY_PREFIXES="$2"
            shift 2
            ;;
        *)
            PARSED+=("$1")
            shift
            ;;
    esac
done

if [ ${#PARSED[@]} -lt 1 ]; then
    usage
fi

VERSION=${PARSED[0]}
FORMAT=${PARSED[1]:-table}

# Validate version
if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}Error: Invalid version format. Use 4.21 or 4.12${NC}" >&2
    exit 1
fi

API_URL="https://access.redhat.com/hydra/rest/securitydata/cve.json?product=Red%20Hat%20OpenShift%20Container%20Platform%20${VERSION}&per_page=1000"

echo -e "${BLUE}[*] Fetching vulnerabilities for OpenShift ${VERSION}...${NC}" >&2

# Fetch data to a temp file; fail loudly instead of reporting an API error as "no vulnerabilities"
RESPONSE_FILE=$(mktemp)
trap 'rm -f "$RESPONSE_FILE"' EXIT
if ! curl -sS -f --retry 2 --connect-timeout 10 --max-time 30 "$API_URL" -o "$RESPONSE_FILE"; then
    echo -e "${RED}Error: Failed to fetch vulnerabilities from API for OpenShift ${VERSION}${NC}" >&2
    exit 1
fi

# Check if jq is available
if command -v jq &> /dev/null; then
    if ! jq -e 'type == "array"' "$RESPONSE_FILE" > /dev/null 2>&1; then
        echo -e "${RED}Error: Unexpected API response (not a JSON array)${NC}" >&2
        exit 1
    fi

    # Advisory prefix filter: any() keeps each CVE once, however many advisories match
    PREFIX_REGEX=''
    if [ -n "$ADVISORY_PREFIXES" ]; then
        IFS=, read -r -a PF <<< "$ADVISORY_PREFIXES"
        for p in "${PF[@]}"; do
            p=$(echo "$p" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')
            [ -n "$p" ] && PREFIX_REGEX="${PREFIX_REGEX:+${PREFIX_REGEX}|}${p}"
        done
    fi
    JQ_FILTER='.[] | select($re == "" or any(.advisories[]?; test("^(" + $re + ")"; "i")))'
    jq_run() { jq --arg re "$PREFIX_REGEX" "$@" "$RESPONSE_FILE"; }

    COUNT=$(jq_run "[ $JQ_FILTER ] | length")
    [ "$COUNT" -eq 0 ] && echo -e "[!] Warning: no CVEs matched for OpenShift ${VERSION} - check that this version exists" >&2

    case "$FORMAT" in
        json)
            jq_run "[ $JQ_FILTER ]"
            ;;
        csv)
            echo "CVE,Severity,Date,Bugzilla,Description"
            jq_run -r "$JQ_FILTER | [.CVE, .severity, .public_date, .bugzilla, .bugzilla_description] | @csv"
            ;;
        table|*)
            echo ""
            echo "═══════════════════════════════════════════════════════════════════════════════"
            echo "OpenShift ${VERSION} - Vulnerabilities Report"
            echo "═══════════════════════════════════════════════════════════════════════════════"
            echo ""

            if [ "$COUNT" -eq 0 ]; then
                echo "No vulnerabilities found."
            else
                printf '%-16s %-10s %s\n' "CVE ID" "Severity" "Date"
                echo "─────────────────────────────────────────────────────────────────────────────"
                jq_run -r "$JQ_FILTER | [.CVE, .severity, (.public_date // \"\")[0:10]] | @tsv" |
                    while IFS=$'\t' read -r cve sev date; do
                        printf '%-16s %-10s %s\n' "$cve" "$sev" "$date"
                    done
            fi

            echo ""
            echo "Total: $COUNT vulnerabilities found"
            echo ""
            ;;
    esac
else
    # Fallback to Python if jq not available (data read from the temp file, values via env)
    ADV_PREFIXES="$ADVISORY_PREFIXES" FORMAT="$FORMAT" OCP_VERSION="$VERSION" \
    python3 - "$RESPONSE_FILE" << 'PYTHON_EOF'
import csv
import json
import os
import sys

try:
    data = json.load(open(sys.argv[1]))
except json.JSONDecodeError as e:
    print(f"Error: Invalid JSON response - {e}", file=sys.stderr)
    sys.exit(1)

if isinstance(data, dict):
    data = data.get('data', [])

# Filter by advisory prefixes passed from shell via ADV_PREFIXES
adv = os.environ.get('ADV_PREFIXES', '').strip()
if adv:
    prefixes = tuple(p.strip().upper() for p in adv.split(',') if p.strip())
    if prefixes:
        data = [item for item in data if any(a.upper().startswith(prefixes) for a in (item.get('advisories') or []))]

if not data:
    print(f"[!] Warning: no CVEs matched for OpenShift {os.environ['OCP_VERSION']} - check that this version exists", file=sys.stderr)

format_type = os.environ['FORMAT']

if format_type == "csv":
    writer = csv.writer(sys.stdout)
    writer.writerow(["CVE", "Severity", "Date", "Bugzilla", "Description"])
    for item in data:
        writer.writerow([item.get('CVE', ''), item.get('severity', ''), item.get('public_date', ''),
                         item.get('bugzilla', ''), item.get('bugzilla_description', '')])
elif format_type == "json":
    print(json.dumps(data, indent=2))
else:  # table
    print()
    print("═" * 80)
    print(f"OpenShift {os.environ['OCP_VERSION']} - Vulnerabilities Report")
    print("═" * 80)
    print()

    if not data:
        print("No vulnerabilities found.")
    else:
        print(f"{'CVE ID':<16} {'Severity':<10} {'Date'}")
        print("-" * 80)
        for item in data:
            cve = item.get('CVE', 'N/A')
            severity = item.get('severity', 'N/A')
            date = (item.get('public_date') or 'N/A')[:10]
            print(f"{cve:<16} {severity:<10} {date}")

    print()
    print(f"Total: {len(data)} vulnerabilities found")
    print()
PYTHON_EOF
fi

echo -e "${BLUE}[*] Report generation complete${NC}" >&2
