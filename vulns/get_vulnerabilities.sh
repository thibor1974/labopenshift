#!/bin/bash

###############################################################################
# Script: get_vulnerabilities.sh
# Purpose: List vulnerabilities affecting a specific OpenShift version
# Usage: ./get_vulnerabilities.sh [version] [format] [severity]
#
# Arguments:
#   version   - OpenShift version (e.g., 4.12, 4.21) - REQUIRED
#   format    - Output format: json, csv, table (default: table)
#   severity  - Filter by severity: critical, important, moderate, low (optional)
#
# Examples:
#   ./get_vulnerabilities.sh 4.21
#   ./get_vulnerabilities.sh 4.12 csv
#   ./get_vulnerabilities.sh 4.12 table critical
###############################################################################

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to display usage
usage() {
    echo "Usage: $0 <version> [format] [severity]"
    echo ""
    echo "Arguments:"
    echo "  version   - OpenShift version (e.g., 4.21, 4.12)"
    echo "  format    - Output format: json, csv, table (default: table)"
    echo "  severity  - Filter by severity: critical, important, moderate, low"
    echo ""
    echo "Examples:"
    echo "  $0 4.21"
    echo "  $0 4.12 csv"
    echo "  $0 4.12 table critical"
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

# Main execution
main() {
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
import json, sys, csv

severity_filter = '$severity_filter'.lower()
output_format = '$output_format'.lower()
version = '$version'

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

# Output in requested format
if output_format == 'csv':
    writer = csv.DictWriter(sys.stdout, fieldnames=['CVE', 'severity', 'public_date', 'bugzilla_id', 'impact'])
    writer.writeheader()
    for vuln in vulns:
        writer.writerow({
            'CVE': vuln.get('CVE', ''),
            'severity': vuln.get('severity', ''),
            'public_date': vuln.get('public_date', ''),
            'bugzilla_id': vuln.get('bugzilla_id', ''),
            'impact': vuln.get('impact', '')
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
        print('═' * 80)
        print(f'OpenShift {version} - Vulnerabilities Report')
        print('═' * 80)
        print()
        print('No vulnerabilities found for the specified criteria.')
        print()
    else:
        print()
        print('═' * 80)
        print(f'OpenShift {version} - Vulnerabilities Report')
        print('═' * 80)
        print()
        print(f\"{'CVE ID':<15} {'Severity':<12} {'Date':<12} {'Impact':<20}\")
        print('-' * 80)
        
        for vuln in vulns:
            cve = vuln.get('CVE', 'N/A')
            severity = vuln.get('severity', 'N/A').upper()
            date = vuln.get('public_date', 'N/A')
            impact = vuln.get('impact', 'N/A')[:18]
            print(f\"{cve:<15} {severity:<12} {date:<12} {impact:<20}\")
        
        print()
        print(f'Total: {len(vulns)} vulnerabilities found')
        print()
"
    
    echo -e "${BLUE}[*] Report generation complete${NC}" >&2
}

main "$@"
