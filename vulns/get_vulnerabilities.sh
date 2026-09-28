#!/bin/bash

###############################################################################
# Script: get_vulnerabilities.sh
# Purpose: List vulnerabilities affecting a specific OpenShift version
# Usage: ./get_vulnerabilities.sh [version] [format] [severity]
#        ./get_vulnerabilities.sh --cve CVE-XXXX-XXXX
#
# Arguments:
#   version   - OpenShift version (e.g., 4.12, 4.21) - REQUIRED
#   format    - Output format: json, csv, table (default: table)
#   severity  - Filter by severity: critical, important, moderate, low (optional)
#   --cve     - Lookup fix status for a specific CVE
#
# Examples:
#   ./get_vulnerabilities.sh 4.21
#   ./get_vulnerabilities.sh 4.12 csv
#   ./get_vulnerabilities.sh 4.12 table critical
#   ./get_vulnerabilities.sh --cve CVE-2026-46300
###############################################################################

set -euo pipefail

# Remove the temp file even when Python exits with an error (set -e)
tmpf=''
trap 'rm -f "$tmpf"' EXIT

# Color codes for output
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to display usage
usage() {
    echo "Usage: $0 <version> [format] [severity]"
    echo "   or: $0 --cve CVE-ID"
    echo ""
    echo "Arguments:"
    echo "  version   - OpenShift version (e.g., 4.21, 4.12)"
    echo "  format    - Output format: json, csv, table (default: table)"
    echo "  severity  - Filter by severity: critical, important, moderate, low"
    echo "  --cve     - Lookup details for a specific CVE"
    echo ""
    echo "Examples:"
    echo "  $0 4.21"
    echo "  $0 4.12 csv"
    echo "  $0 4.12 table critical"
    echo "  $0 --cve CVE-2026-46300"
    exit 1
}

# Function to validate version format
validate_version() {
    local version=$1
    if ! [[ $version =~ ^[0-9]+\.[0-9]+$ ]]; then
        echo -e "${RED}Error: Invalid version format. Use format like 4.21 or 4.12${NC}" >&2
        exit 1
    fi
}

# Curl with retries and fail-on-http-error
curl_retry() {
    local url="$1"
    local out="${2:-/dev/stdout}"
    local max_attempts=3
    local attempt=1
    local sleep_for=1

    while [ $attempt -le $max_attempts ]; do
        if curl -sS --connect-timeout 10 --max-time 30 -f "$url" -o "$out"; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep $sleep_for
        sleep_for=$((sleep_for * 2))
    done

    return 22
}

# Function to fetch and display CVE details
fetch_cve_details() {
    local cve_id=$1
    echo -e "${BLUE}[*] Fetching details for ${cve_id}...${NC}" >&2

    tmpf=$(mktemp)
    if ! curl_retry "https://access.redhat.com/hydra/rest/securitydata/cve/${cve_id}.json" "$tmpf"; then
        echo -e "${RED}Error: Failed to fetch CVE details for ${cve_id}${NC}" >&2
        rm -f "$tmpf"
        return 1
    fi

    python3 - "$tmpf" <<'PY'
import json, sys

try:
    cve_data = json.load(open(sys.argv[1]))
except json.JSONDecodeError as e:
    print(f'Error: Invalid JSON response - {e}', file=sys.stderr)
    sys.exit(1)

print()
print('═' * 80)
print(f"CVE Details: {cve_data.get('name', 'Unknown')}")
print('═' * 80)
print()

# Basic info
severity = cve_data.get('threat_severity', 'Unknown')
published = cve_data.get('public_date', 'Unknown')
print(f'Severity: {severity}')
print(f'Published: {published}')
cvss3 = cve_data.get('cvss3') or {}
if cvss3.get('cvss3_base_score'):
    print(f"CVSS3 Score: {cvss3.get('cvss3_base_score')}")
if cvss3.get('cvss3_scoring_vector'):
    print(f"CVSS3 Vector: {cvss3.get('cvss3_scoring_vector')}")
print()

# Fixed in versions
affected_releases = cve_data.get('affected_release') or []
ocp_releases = [r for r in affected_releases if 'OpenShift' in r.get('product_name', '')]

if ocp_releases:
    print('Fixed in OpenShift versions:')
    print('-' * 80)
    for release in ocp_releases:
        product = release.get('product_name', 'N/A')
        advisory = release.get('advisory', 'N/A')
        package = release.get('package', 'N/A')
        print(f'  Product: {product}')
        print(f'    Advisory: {advisory}')
        print(f'    Package: {package}')
        print()

# Status by version
package_states = cve_data.get('package_state') or []
ocp_states = [p for p in package_states if 'OpenShift' in p.get('product_name', '')]

if ocp_states:
    print('Status by OpenShift version:')
    print('-' * 80)
    for state in ocp_states:
        product = state.get('product_name', 'N/A')
        fix_state = state.get('fix_state', 'Unknown')
        print(f'  {product}: {fix_state}')
    print()

# Description
if cve_data.get('details'):
    print('Description:')
    print('-' * 80)
    for detail in cve_data.get('details', []):
        print(f'  {detail}')
    print()
PY
    rm -f "$tmpf"

    echo -e "${BLUE}[*] CVE lookup complete${NC}" >&2
}

# Main execution
main() {
    # Extract optional flags (e.g. --advisory-prefix) and rebuild positional params
    ADVISORY_PREFIXES=''
    PARSED_ARGS=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --advisory-prefix)
                if [ "$#" -lt 2 ]; then
                    echo -e "${RED}Error: --advisory-prefix requires a value (comma-separated prefixes)${NC}" >&2
                    usage
                fi
                ADVISORY_PREFIXES="$2"
                shift 2
                ;;
            *)
                PARSED_ARGS+=("$1")
                shift
                ;;
        esac
    done
    # restore positional parameters for normal processing
    set -- "${PARSED_ARGS[@]:-}"

    # Handle --cve flag
    if [ "$#" -gt 0 ] && [ "$1" = "--cve" ]; then
        if [ "$#" -lt 2 ]; then
            echo -e "${RED}Error: --cve requires a CVE ID${NC}" >&2
            usage
        fi
        if ! [[ $2 =~ ^CVE-[0-9]{4}-[0-9]+$ ]]; then
            echo -e "${RED}Error: Invalid CVE ID '$2'. Use format like CVE-2026-46300${NC}" >&2
            exit 1
        fi
        fetch_cve_details "$2"
        return 0
    fi
    
    local version="${1:-}"
    local output_format="${2:-table}"
    local severity_filter="${3:-}"
    
    if [ -z "$version" ]; then
        usage
    fi
    
    validate_version "$version"

    case "$output_format" in
        table|csv|json) ;;
        *) echo -e "${RED}Error: Invalid format '${output_format}'. Use table, csv or json${NC}" >&2; exit 1 ;;
    esac
    case "$severity_filter" in
        ''|critical|important|moderate|low) ;;
        *) echo -e "${RED}Error: Invalid severity '${severity_filter}'. Use critical, important, moderate or low${NC}" >&2; exit 1 ;;
    esac

    local api_url="https://access.redhat.com/hydra/rest/securitydata/cve.json?product=Red%20Hat%20OpenShift%20Container%20Platform%20${version}&per_page=1000"
    
    echo -e "${BLUE}[*] Fetching vulnerabilities for OpenShift ${version}...${NC}" >&2

    tmpf=$(mktemp)
    if ! curl_retry "$api_url" "$tmpf"; then
        echo -e "${RED}Error: Failed to fetch vulnerabilities from API for OpenShift ${version}${NC}" >&2
        rm -f "$tmpf"
        return 1
    fi

    # Process with Python. Values are passed via the environment (never pasted
    # into the code) and the heredoc is quoted so the shell does not expand it.
    SEVERITY_FILTER="$severity_filter" OUTPUT_FORMAT="$output_format" OCP_VERSION="$version" \
    ADVISORY_PREFIXES="$ADVISORY_PREFIXES" python3 - "$tmpf" <<'PY'
import json, os, sys, csv, subprocess
from concurrent.futures import ThreadPoolExecutor

severity_filter = os.environ['SEVERITY_FILTER'].lower()
output_format = os.environ['OUTPUT_FORMAT'].lower()
version = os.environ['OCP_VERSION']
advisory_prefixes = os.environ['ADVISORY_PREFIXES']
product_name = f'Red Hat OpenShift Container Platform {version}'

def fetch_detail(cve_id):
    '''Fetch CVE details (None on failure)'''
    try:
        result = subprocess.run(
            ['curl', '-sS', '-f', '--retry', '2', '--connect-timeout', '5', '--max-time', '15',
             f'https://access.redhat.com/hydra/rest/securitydata/cve/{cve_id}.json'],
            capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None

def advisory_key(advisory):
    '''Sort key for advisory IDs like RHSA-2026:54206 (year, number)'''
    try:
        year, number = advisory.split('-', 1)[1].split(':')
        return (int(year), int(number))
    except (IndexError, ValueError):
        return (9999, 0)

def fix_advisory(cve_data):
    '''Earliest advisory fixing the CVE in the target stream ('-' none listed, '?' lookup failed)'''
    if cve_data is None:
        return '?'
    advisories = {r.get('advisory') for r in cve_data.get('affected_release') or []
                  if r.get('product_name') == product_name and r.get('advisory')}
    return min(advisories, key=advisory_key) if advisories else '-'

try:
    data = json.load(open(sys.argv[1]))
except json.JSONDecodeError as e:
    print(f'Error: Invalid JSON response - {e}', file=sys.stderr)
    sys.exit(1)

# Convert to list if needed
if isinstance(data, dict):
    data = data.get('data', [])
if not isinstance(data, list):
    print(f'Error: Unexpected API response type {type(data).__name__}', file=sys.stderr)
    sys.exit(1)
vulns = data
if not vulns:
    print(f'[!] Warning: the API returned no CVEs for OpenShift {version} - check that this version exists', file=sys.stderr)
elif len(vulns) >= 1000:
    print('[!] Warning: 1000 results returned, output may be truncated (get_vulnerabilities.py paginates)', file=sys.stderr)

# Filter by severity
if severity_filter:
    vulns = [v for v in vulns if v.get('severity', '').lower() == severity_filter]

# Sort by severity
severity_order = {'critical': 0, 'important': 1, 'moderate': 2, 'low': 3}
vulns.sort(key=lambda x: severity_order.get(x.get('severity', 'low').lower(), 4))

# Filter by advisory prefixes (passed from shell via --advisory-prefix)
if advisory_prefixes:
    prefixes = tuple(p.strip().upper() for p in advisory_prefixes.split(',') if p.strip())
    if prefixes:
        vulns = [v for v in vulns if any(a.upper().startswith(prefixes) for a in (v.get('advisories') or []))]

# Output in requested format
if output_format == 'csv':
    writer = csv.DictWriter(sys.stdout, fieldnames=['CVE', 'severity', 'public_date', 'bugzilla', 'description', 'advisories'])
    writer.writeheader()
    for vuln in vulns:
        writer.writerow({
            'CVE': vuln.get('CVE', ''),
            'severity': vuln.get('severity', ''),
            'public_date': vuln.get('public_date', ''),
            'bugzilla': vuln.get('bugzilla', ''),
            'description': vuln.get('bugzilla_description', ''),
            'advisories': ';'.join(vuln.get('advisories') or [])
        })
elif output_format == 'json':
    print(json.dumps({
        'version': version,
        'count': len(vulns),
        'vulnerabilities': vulns,
        'source': 'Red Hat Security Advisory API'
    }, indent=2))
else:  # table
    print()
    print('═' * 100)
    print(f'OpenShift {version} - Vulnerabilities Report')
    print('═' * 100)
    print()
    if not vulns:
        print('No vulnerabilities found for the specified criteria.')
        print()
    else:
        print(f'[*] Fetching fix status for {len(vulns)} CVEs...', file=sys.stderr)
        with ThreadPoolExecutor(max_workers=8) as pool:
            details = list(pool.map(fetch_detail, [v.get('CVE', '') for v in vulns]))

        fix_header = f'Fix ({version})'
        print(f"{'CVE ID':<16} {'Severity':<10} {fix_header:<17} {'Date':<11} {'Description'}")
        print('-' * 130)
        for vuln, detail in zip(vulns, details):
            cve = vuln.get('CVE', 'N/A')
            severity = vuln.get('severity', 'N/A').upper()
            date = (vuln.get('public_date') or 'N/A')[:10]
            description = (vuln.get('bugzilla_description') or '')[:70]
            print(f"{cve:<16} {severity:<10} {fix_advisory(detail):<17} {date:<11} {description}")

        print()
        print(f'Total: {len(vulns)} vulnerabilities found')
        print(f"Fix ({version}): advisory fixing the CVE in this stream; '-' = no fix listed, '?' = lookup failed")
        print()
PY
    rm -f "$tmpf"

    echo -e "${BLUE}[*] Report generation complete${NC}" >&2
}

main "$@"
