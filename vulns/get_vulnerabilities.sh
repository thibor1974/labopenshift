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

# Function to fetch and display CVE details
fetch_cve_details() {
    local cve_id=$1
    echo -e "${BLUE}[*] Fetching details for ${cve_id}...${NC}" >&2
    
    curl -s --connect-timeout 10 "https://access.redhat.com/hydra/rest/securitydata/cve/${cve_id}.json" 2>/dev/null | python3 -c "
import json, sys

try:
    cve_data = json.load(sys.stdin)
except json.JSONDecodeError as e:
    print(f'Error: Invalid JSON response - {e}', file=sys.stderr)
    sys.exit(1)

print()
print('═' * 80)
print(f\"CVE Details: {cve_data.get('name', 'Unknown')}\")
print('═' * 80)
print()

# Basic info
severity = cve_data.get('threat_severity', 'Unknown')
published = cve_data.get('public_date', 'Unknown')
print(f'Severity: {severity}')
print(f'Published: {published}')
    if cve_data.get('cvss3_scoring_vector'):
        print(f\"CVSS Vector: {cve_data.get('cvss3_scoring_vector')}\")
advisories = cve_data.get('advisories') or []
if advisories:
    print()
    print('Advisories:')
    print('-' * 80)
    for advisory in advisories:
        print(f'  {advisory}')
print()

# Fixed in versions
affected_releases = cve_data.get('affected_release', [])
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
package_states = cve_data.get('package_state', [])
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
"
    
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
    
    local api_url="https://access.redhat.com/hydra/rest/securitydata/cve.json?product=Red%20Hat%20OpenShift%20Container%20Platform%20${version}&per_page=1000"
    
    echo -e "${BLUE}[*] Fetching vulnerabilities for OpenShift ${version}...${NC}" >&2
    
    # Fetch data and process directly with Python
    curl -s --connect-timeout 10 "$api_url" 2>/dev/null | python3 -c "
import json, sys, csv, subprocess

severity_filter = '$severity_filter'.lower()
output_format = '$output_format'.lower()
version = '$version'
cve_cache = {}
advisory_prefixes = '$ADVISORY_PREFIXES'

def get_fixed_version(cve_id):
    '''Fetch CVE details and extract the earliest fixed version'''
    if cve_id in cve_cache:
        return cve_cache[cve_id]
    
    try:
        result = subprocess.run(
            ['curl', '-s', '--connect-timeout', '3', 
             f'https://access.redhat.com/hydra/rest/securitydata/cve/{cve_id}.json'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            cve_data = json.loads(result.stdout)
            affected_releases = cve_data.get('affected_release', [])
            ocp_releases = [r for r in affected_releases if 'OpenShift' in r.get('product_name', '')]
            
            if ocp_releases:
                versions = []
                for release in ocp_releases:
                    product = release.get('product_name', '')
                    parts = product.split()
                    if parts and parts[-1][0].isdigit():
                        version_str = parts[-1]
                        if version_str not in versions:
                            versions.append(version_str)
                
                if versions:
                    try:
                        versions_sorted = sorted(versions, key=lambda x: tuple(map(int, x.split('.'))))
                        fixed = versions_sorted[0]
                        cve_cache[cve_id] = fixed
                        return fixed
                    except:
                        pass
    except:
        pass
    
    cve_cache[cve_id] = 'N/A'
    return 'N/A'

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError as e:
    print(f'Error: Invalid JSON response - {e}', file=sys.stderr)
    data = []

# Convert to list if needed
if isinstance(data, dict):
    vulns = data.get('data', []) if 'data' in data else []
elif isinstance(data, list):
    vulns = data
else:
    vulns = []

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
    writer = csv.DictWriter(sys.stdout, fieldnames=['CVE', 'severity', 'public_date', 'bugzilla_id', 'impact', 'advisories'])
    writer.writeheader()
    for vuln in vulns:
        advisories = vuln.get('advisories') or []
        writer.writerow({
            'CVE': vuln.get('CVE', ''),
            'severity': vuln.get('severity', ''),
            'public_date': vuln.get('public_date', ''),
            'bugzilla_id': vuln.get('bugzilla_id', ''),
            'impact': vuln.get('impact', ''),
            'advisories': ';'.join(advisories)
        })
elif output_format == 'json':
    print(json.dumps({
        'version': version,
        'count': len(vulns),
        'vulnerabilities': vulns,
        'source': 'Red Hat Security Advisory API'
    }, indent=2))
else:  # table
    if not vulns:
        print()
        print('═' * 100)
        print(f'OpenShift {version} - Vulnerabilities Report')
        print('═' * 100)
        print()
        print('No vulnerabilities found for the specified criteria.')
        print()
    else:
        print()
        print('═' * 100)
        print(f'OpenShift {version} - Vulnerabilities Report')
        print('═' * 100)
        print()
        print(f\"{'CVE ID':<15} {'Severity':<12} {'Fixed In':<10} {'Date':<12} {'Impact':<20} {'Advisories':<35}\")
        print('-' * 130)
        
        for vuln in vulns:
            cve = vuln.get('CVE', 'N/A')
            severity = vuln.get('severity', 'N/A').upper()
            date = vuln.get('public_date', 'N/A')[:10]
            impact = vuln.get('impact', 'N/A')[:18]
            fixed_in = get_fixed_version(cve)
            advisories = ";".join(vuln.get('advisories') or [])[:33]
            print(f\"{cve:<15} {severity:<12} {fixed_in:<10} {date:<12} {impact:<20} {advisories:<35}\")
        
        print()
        print(f'Total: {len(vulns)} vulnerabilities found')
        print()
"
    
    echo -e "${BLUE}[*] Report generation complete${NC}" >&2
}

main "$@"
