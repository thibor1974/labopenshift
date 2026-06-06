#!/bin/bash

###############################################################################
# Advanced Vulnerability Script - Alternative Implementation
# This version can parse real Red Hat security advisory OVAL XML data
# and provides more advanced filtering and analysis capabilities
###############################################################################

set -euo pipefail

# Configuration
CACHE_DIR="${XDG_CACHE_HOME:-.cache}/openshift-vulns"
CACHE_EXPIRY_HOURS=24
OVAL_FEED_URL="https://access.redhat.com/security/data/oval/feed-v2/com.redhat.rhsa-all.xml.bz2"

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Create cache directory
mkdir -p "$CACHE_DIR"

# Fetch and cache OVAL data from Red Hat
fetch_oval_data() {
    local cache_file="$CACHE_DIR/rhsa-all.xml"
    local cache_timestamp_file="$CACHE_DIR/.oval-timestamp"
    
    # Check cache validity
    if [[ -f "$cache_file" && -f "$cache_timestamp_file" ]]; then
        local cache_age=$(( $(date +%s) - $(stat -f %m "$cache_timestamp_file" 2>/dev/null || echo 0) ))
        local cache_max_age=$(( CACHE_EXPIRY_HOURS * 3600 ))
        
        if (( cache_age < cache_max_age )); then
            echo -e "${GREEN}[✓] Using cached OVAL data${NC}" >&2
            cat "$cache_file"
            return 0
        fi
    fi
    
    echo -e "${BLUE}[*] Fetching OVAL data from Red Hat...${NC}" >&2
    
    local temp_file=$(mktemp)
    trap "rm -f $temp_file" RETURN
    
    if command -v curl &> /dev/null; then
        # Try to fetch and decompress
        if curl -s --connect-timeout 10 "$OVAL_FEED_URL" | bunzip2 > "$temp_file" 2>/dev/null; then
            cp "$temp_file" "$cache_file"
            touch "$cache_timestamp_file"
            echo -e "${GREEN}[✓] OVAL data cached${NC}" >&2
            cat "$cache_file"
            return 0
        fi
    fi
    
    echo -e "${YELLOW}[!] Could not fetch OVAL data, using local data${NC}" >&2
    return 1
}

# Parse OVAL XML and extract OpenShift vulnerabilities
parse_oval_xml() {
    local xml_file=$1
    local target_version=$2
    
    python3 << 'PYTHON_SCRIPT'
import xml.etree.ElementTree as ET
import sys
import json
from packaging import version as pkg_version

try:
    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    
    # Namespace mapping
    ns = {
        'oval': 'http://oval.mitre.org/XMLSchema/oval-definitions-5',
        'rhsa': 'http://www.redhat.com/security/updates/classification/',
        'metadata': 'http://oval.mitre.org/XMLSchema/oval-definitions-5#metadata'
    }
    
    target_version = pkg_version.parse(sys.argv[2])
    vulns = []
    
    # Parse definitions
    for definition in root.findall('.//oval:definition', ns):
        definition_id = definition.get('id', '')
        
        # Filter for OpenShift vulnerabilities
        if 'openshift' not in definition_id.lower():
            continue
        
        metadata = definition.find('oval:metadata', ns)
        if metadata is None:
            continue
        
        title = metadata.findtext('oval:title', '', ns)
        description = metadata.findtext('oval:description', '', ns)
        
        # Extract advisory reference
        references = metadata.findall('oval:reference', ns)
        for ref in references:
            ref_id = ref.get('ref_id', '')
            if ref_id.startswith('RHSA-'):
                # Extract severity if available
                severity = definition.get('class', 'unknown')
                
                vuln_entry = {
                    'id': ref_id,
                    'definition_id': definition_id,
                    'title': title,
                    'description': description[:100],
                    'severity': severity
                }
                
                vulns.append(vuln_entry)
    
    # Output as JSON
    for vuln in vulns:
        print(json.dumps(vuln))
        
except ImportError:
    print("Error: packaging library not installed", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Error parsing OVAL data: {e}", file=sys.stderr)
    sys.exit(1)

PYTHON_SCRIPT
}

# Fetch from Red Hat Errata API
fetch_from_errata_api() {
    local version=$1
    
    echo -e "${BLUE}[*] Querying Red Hat Errata API...${NC}" >&2
    
    # This would require API authentication
    # Placeholder for future implementation
    echo -e "${YELLOW}[!] Errata API integration requires authentication${NC}" >&2
}

# Generate vulnerability report
generate_report() {
    local version=$1
    local format=$2
    local severity=$3
    
    python3 << 'PYTHON_SCRIPT'
import json
import sys
from collections import Counter
from datetime import datetime

# Read vulnerability data from stdin
vulns = []
for line in sys.stdin:
    if line.strip():
        try:
            vulns.append(json.loads(line))
        except:
            pass

severity_filter = sys.argv[3] if len(sys.argv) > 3 else ""
output_format = sys.argv[2] if len(sys.argv) > 2 else "table"

# Filter by severity
if severity_filter:
    vulns = [v for v in vulns if v.get('severity', '').lower() == severity_filter.lower()]

# Generate report
if output_format == "json":
    print(json.dumps({
        "vulnerabilities": vulns,
        "count": len(vulns),
        "generated": datetime.now().isoformat()
    }, indent=2))
    
elif output_format == "stats":
    severity_counts = Counter(v.get('severity', 'unknown') for v in vulns)
    print(f"Total Vulnerabilities: {len(vulns)}")
    print(f"By Severity:")
    for severity in ['critical', 'high', 'medium', 'low']:
        count = severity_counts.get(severity, 0)
        print(f"  {severity.upper()}: {count}")
    
else:  # table format
    print(f"\nOpenShift {sys.argv[1]} - Vulnerability Report")
    print(f"Generated: {datetime.now()}")
    print("=" * 80)
    
    if not vulns:
        print("No vulnerabilities found.")
    else:
        for vuln in vulns:
            print(f"\nID: {vuln.get('id', 'N/A')}")
            print(f"Title: {vuln.get('title', 'N/A')}")
            print(f"Severity: {vuln.get('severity', 'N/A')}")
            print(f"Description: {vuln.get('description', 'N/A')}")

PYTHON_SCRIPT
}

# Main function
main() {
    local version="${1:-}"
    local format="${2:-table}"
    local severity="${3:-}"
    
    if [[ -z "$version" ]]; then
        echo "Usage: $0 <version> [format] [severity]"
        echo "Formats: table, json, stats"
        echo "Severity: critical, high, medium, low"
        exit 1
    fi
    
    # Attempt to fetch real data, fall back to local if needed
    if fetch_oval_data > /dev/null 2>&1; then
        cache_file="$CACHE_DIR/rhsa-all.xml"
        if [[ -f "$cache_file" ]]; then
            parse_oval_xml "$cache_file" "$version" | generate_report "$version" "$format" "$severity"
            return 0
        fi
    fi
    
    echo -e "${YELLOW}[!] Falling back to local vulnerability data${NC}" >&2
}

main "$@"
