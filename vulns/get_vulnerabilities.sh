#!/bin/bash

###############################################################################
# Script: get_vulnerabilities.sh
# Purpose: List vulnerabilities affecting a specific OpenShift version, with the
#          OpenShift release that fixes each one (or its fix status)
# Usage: ./get_vulnerabilities.sh [options] <version> [format] [severity]
#        ./get_vulnerabilities.sh --cve CVE-XXXX-XXXX
#
# Thin wrapper around get_vulnerabilities.py (which holds all the logic),
# keeping the positional-argument interface.
#
# Arguments:
#   version   - OpenShift stream (e.g., 4.21) or full release (e.g., 4.21.17) - REQUIRED.
#               With a full release, each CVE is also checked against it (fixed / VULNERABLE)
#   format    - Output format: json, csv, table (default: table)
#   severity  - Filter by severity: critical, important, moderate, low (optional)
#
# Options:
#   --cve CVE-ID              Fix status of one CVE for every OpenShift version
#   --advisory-prefix LIST    Only CVEs with advisories starting with LIST (e.g. RHSA,RHBA)
#   --include-unfixed         Also list CVEs not fixed in this version (slow: a few minutes)
#   --no-fix                  Skip the fix lookups (faster)
#
# Examples:
#   ./get_vulnerabilities.sh 4.21
#   ./get_vulnerabilities.sh 4.21.17 table important
#   ./get_vulnerabilities.sh 4.12 csv
#   ./get_vulnerabilities.sh 4.12 table critical
#   ./get_vulnerabilities.sh --include-unfixed 4.12 csv important
#   ./get_vulnerabilities.sh --cve CVE-2026-46300
###############################################################################

set -euo pipefail

RED='\033[0;31m'
NC='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="${SCRIPT_DIR}/get_vulnerabilities.py"

usage() {
    echo "Usage: $0 [options] <version> [format] [severity]"
    echo "   or: $0 --cve CVE-ID"
    echo ""
    echo "Arguments:"
    echo "  version   - OpenShift stream (e.g., 4.21) or full release (e.g., 4.21.17)"
    echo "  format    - Output format: json, csv, table (default: table)"
    echo "  severity  - Filter by severity: critical, important, moderate, low"
    echo ""
    echo "Options:"
    echo "  --cve CVE-ID              Fix status of one CVE for every OpenShift version"
    echo "  --advisory-prefix LIST    Only CVEs with advisories starting with LIST (e.g. RHSA,RHBA)"
    echo "  --include-unfixed         Also list CVEs not fixed in this version (slow: a few minutes)"
    echo "  --no-fix                  Skip the fix lookups (faster)"
    echo ""
    echo "Examples:"
    echo "  $0 4.21"
    echo "  $0 4.21.17 table important"
    echo "  $0 4.12 csv"
    echo "  $0 4.12 table critical"
    echo "  $0 --include-unfixed 4.12 csv important"
    echo "  $0 --cve CVE-2026-46300"
    exit 1
}

error() {
    echo -e "${RED}Error: $*${NC}" >&2
    exit 1
}

OPTS=()
POSITIONAL=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --cve)
            [ "$#" -ge 2 ] || error "--cve requires a CVE ID"
            [[ $2 =~ ^CVE-[0-9]{4}-[0-9]+$ ]] || error "Invalid CVE ID '$2'. Use format like CVE-2026-46300"
            exec python3 "$PY_SCRIPT" --cve "$2"
            ;;
        --advisory-prefix)
            [ "$#" -ge 2 ] || error "--advisory-prefix requires a value (comma-separated prefixes)"
            OPTS+=(--advisory-prefix "$2")
            shift 2
            ;;
        --include-unfixed|--no-fix)
            OPTS+=("$1")
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            error "Unknown option '$1'"
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

[ "${#POSITIONAL[@]}" -ge 1 ] || usage
version="${POSITIONAL[0]}"
output_format="${POSITIONAL[1]:-table}"
severity_filter="${POSITIONAL[2]:-}"

[[ $version =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || error "Invalid version format. Use format like 4.21 or 4.21.17"
case "$output_format" in
    table|csv|json) ;;
    *) error "Invalid format '${output_format}'. Use table, csv or json" ;;
esac
case "$severity_filter" in
    '') ;;
    critical|important|moderate|low) OPTS+=(--severity "$severity_filter") ;;
    *) error "Invalid severity '${severity_filter}'. Use critical, important, moderate or low" ;;
esac

# ${OPTS[@]+...} keeps bash 3.2 (macOS) happy with an empty array under set -u
exec python3 "$PY_SCRIPT" "$version" --format "$output_format" ${OPTS[@]+"${OPTS[@]}"}
