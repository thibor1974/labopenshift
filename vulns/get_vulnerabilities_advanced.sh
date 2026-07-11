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
    echo -e "${RED}Error: Invalid version format. Use 4.21 or 4.12${NC}"
    exit 1
fi

API_URL="https://access.redhat.com/hydra/rest/securitydata/cve.json?product=Red%20Hat%20OpenShift%20Container%20Platform%20${VERSION}&per_page=1000"

echo -e "${BLUE}[*] Fetching vulnerabilities for OpenShift ${VERSION}...${NC}" >&2

# Fetch data
RESPONSE=$(curl -s --connect-timeout 10 "$API_URL" 2>/dev/null || echo "[]")

# Build jq filter if advisory prefixes provided
JQ_FILTER='.[]'
if [ -n "$ADVISORY_PREFIXES" ]; then
    IFS=, read -r -a PF <<< "$ADVISORY_PREFIXES"
    regex='^('
    sep=''
    for p in "${PF[@]}"; do
        p=$(echo "$p" | tr '[:lower:]' '[:upper:]')
        regex="${regex}${sep}${p}-"
        sep='|'
    done
    regex="${regex})"
    JQ_FILTER=".[] | select(.advisories and (.advisories[] | test(\"${regex}\")))"
fi

# Check if jq is available
if command -v jq &> /dev/null; then
    case "$FORMAT" in
        json)
            if [ -n "$ADVISORY_PREFIXES" ]; then
                echo "$RESPONSE" | jq "[ $JQ_FILTER ]"
            else
                echo "$RESPONSE" | jq '.'
            fi
            ;;
        csv)
            echo "CVE,Severity,Date,Bugzilla,Impact"
            echo "$RESPONSE" | jq -r "$JQ_FILTER | [.CVE, .severity, .public_date, .bugzilla_id, .impact] | @csv" 2>/dev/null || true
            ;;
        table|*)
            echo ""
            echo "═══════════════════════════════════════════════════════════════════════════════"
            echo "OpenShift ${VERSION} - Vulnerabilities Report"
            echo "═══════════════════════════════════════════════════════════════════════════════"
            echo ""
            
                COUNT=$(echo "$RESPONSE" | jq "[ $JQ_FILTER ] | length" 2>/dev/null || echo 0)
            
            if [ "$COUNT" -eq 0 ]; then
                echo "No vulnerabilities found."
            else
                echo "CVE ID           Severity      Date"
                echo "─────────────────────────────────────────────────────────────────────────────"
                echo "$RESPONSE" | jq -r "$JQ_FILTER | [.CVE, .severity, .public_date] | @tsv" 2>/dev/null || true
            fi
            
            echo ""
            echo "Total: $COUNT vulnerabilities found"
            echo ""
            ;;
    esac
else
    # Fallback to Python if jq not available
    export ADV_PREFIXES="$ADVISORY_PREFIXES"
    python3 << PYTHON_EOF
import json
import sys
import os

try:
    data = json.loads('$RESPONSE')
except:
    data = []

if isinstance(data, dict):
    data = data.get('data', []) if 'data' in data else []

# Filter by advisory prefixes passed from shell via ADV_PREFIXES
adv = os.environ.get('ADV_PREFIXES', '').strip()
if adv:
    prefixes = tuple(p.strip().upper() for p in adv.split(',') if p.strip())
    if prefixes:
        data = [item for item in data if any(a.upper().startswith(prefixes) for a in (item.get('advisories') or []))]

format_type = "$FORMAT"

if format_type == "csv":
    print("CVE,Severity,Date,Bugzilla,Impact")
    for item in data:
        cve = item.get('CVE', '')
        severity = item.get('severity', '')
        date = item.get('public_date', '')
        bugzilla = item.get('bugzilla_id', '')
        impact = item.get('impact', '').replace(',', ';')
        print(f'{cve},{severity},{date},{bugzilla},"{impact}"')
elif format_type == "json":
    print(json.dumps(data, indent=2))
else:  # table
    print()
    print("═" * 80)
    print("OpenShift $VERSION - Vulnerabilities Report")
    print("═" * 80)
    print()
    
    if not data:
        print("No vulnerabilities found.")
    else:
        print(f"{'CVE ID':<15} {'Severity':<12} {'Date':<12}")
        print("-" * 80)
        for item in data:
            cve = item.get('CVE', 'N/A')
            severity = item.get('severity', 'N/A').upper()
            date = item.get('public_date', 'N/A')
            print(f"{cve:<15} {severity:<12} {date:<12}")
    
    print()
    print(f"Total: {len(data)} vulnerabilities found")
    print()
PYTHON_EOF
fi

echo -e "${BLUE}[*] Report generation complete${NC}" >&2
