#!/bin/bash

###############################################################################
# Script: get_vulnerabilities.sh
# Purpose: List vulnerabilities affecting a specific OpenShift version
# Usage: ./get_vulnerabilities.sh [version] [format] [severity]
#
# Arguments:
#   version   - OpenShift version (e.g., 4.12.0, 4.11.5) - REQUIRED
#   format    - Output format: json, csv, table (default: table)
#   severity  - Filter by severity: critical, high, medium, low (optional)
#
# Examples:
#   ./get_vulnerabilities.sh 4.12.0
#   ./get_vulnerabilities.sh 4.11.5 csv critical
#   ./get_vulnerabilities.sh 4.12.0 json
###############################################################################

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
OUTPUT_FORMAT="${2:-table}"
SEVERITY_FILTER="${3:-}"
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Function to display usage
usage() {
    echo "Usage: $0 <version> [format] [severity]"
    echo ""
    echo "Arguments:"
    echo "  version   - OpenShift version (e.g., 4.12.0, 4.11.5)"
    echo "  format    - Output format: json, csv, table (default: table)"
    echo "  severity  - Filter by severity: critical, high, medium, low"
    echo ""
    echo "Examples:"
    echo "  $0 4.12.0"
    echo "  $0 4.11.5 csv critical"
    echo "  $0 4.12.0 json"
    exit 1
}

# Function to validate version format
validate_version() {
    local version=$1
    if ! [[ $version =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
        echo -e "${RED}Error: Invalid version format. Use format like 4.12.0${NC}"
        exit 1
    fi
}

# Function to fetch from Red Hat Security Advisory API
fetch_red_hat_advisories() {
    local version=$1
    local api_url_all_bz2="https://access.redhat.com/security/data/oval/feed-v2/com.redhat.rhsa-all.xml.bz2"
    
    echo -e "${BLUE}[*] Fetching Red Hat Security Advisories for OpenShift ${version}...${NC}" >&2
    
    # Try to fetch and decompress OVAL data (.xml.bz2)
    if command -v curl &> /dev/null; then
        for url in "$api_url_all_bz2"; do
            if curl -sfL --connect-timeout 10 "$url" -o "$TEMP_DIR/advisories.xml.bz2" 2>/dev/null; then
                if python3 - "$TEMP_DIR/advisories.xml.bz2" "$TEMP_DIR/advisories.xml" << 'PYTHON_SCRIPT'
import bz2
import sys

try:
    with bz2.open(sys.argv[1], "rb") as src, open(sys.argv[2], "wb") as dst:
        dst.write(src.read())
except Exception:
    raise SystemExit(1)
PYTHON_SCRIPT
                then
                    return 0
                fi
            fi
        done
    fi
}

# Function to fetch from NVD (National Vulnerability Database)
fetch_nvd_data() {
    local version=$1
    local search_query="openshift%20${version}"
    local api_url="https://services.nvd.nist.gov/rest/json/cves/1.0?keyword=${search_query}"
    
    echo -e "${BLUE}[*] Fetching NVD data for OpenShift ${version}...${NC}" >&2
    
    if command -v curl &> /dev/null; then
        curl -s --connect-timeout 5 "$api_url" > "$TEMP_DIR/nvd.json" 2>/dev/null || true
    fi
}

# Function to parse and extract vulnerabilities from Red Hat OVAL XML
parse_red_hat_oval_vulnerabilities() {
    local version=$1
    local input_xml="$TEMP_DIR/advisories.xml"
    
    if [[ ! -s "$input_xml" ]]; then
        return 0
    fi
    
    python3 - "$input_xml" "$version" "$SEVERITY_FILTER" << 'PYTHON_SCRIPT'
import json
import re
import sys
import xml.etree.ElementTree as ET


def local_name(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def find_first_text(elem, names):
    wanted = set(names)
    for child in elem.iter():
        if local_name(child.tag) in wanted and child.text:
            text = child.text.strip()
            if text:
                return text
    return ""


def find_all_refs(metadata):
    refs = []
    for child in metadata.iter():
        if local_name(child.tag) == "reference":
            source = (child.attrib.get("source") or "").strip()
            ref_id = (child.attrib.get("ref_id") or "").strip()
            if ref_id:
                refs.append((source, ref_id))
    return refs


def find_severity(metadata):
    for child in metadata.iter():
        if local_name(child.tag) == "severity" and child.text:
            sev = child.text.strip().lower()
            if sev:
                return sev
    return "unknown"


def find_cvss_score(metadata):
    score_tags = {
        "cvss3_base_score",
        "cvss_base_score",
        "cvss3_score",
        "cvss_score",
    }
    score_text = find_first_text(metadata, score_tags)
    if not score_text:
        return None
    try:
        return float(score_text)
    except Exception:
        return None


def find_published(metadata):
    for child in metadata.iter():
        if local_name(child.tag) in {"issued", "updated", "date"}:
            date_val = (child.attrib.get("date") or "").strip()
            if date_val:
                return date_val
            if child.text and child.text.strip():
                return child.text.strip()
    return "N/A"


def find_platform_texts(metadata):
    platforms = []
    for child in metadata.iter():
        if local_name(child.tag) == "platform" and child.text:
            text = child.text.strip()
            if text:
                platforms.append(text)
    return platforms


input_xml = sys.argv[1]
target_version = sys.argv[2]
severity_filter = sys.argv[3].lower().strip()
major_minor = ".".join(target_version.split(".")[:2])

try:
    tree = ET.parse(input_xml)
    root = tree.getroot()
except Exception:
    sys.exit(0)

definitions = [elem for elem in root.iter() if local_name(elem.tag) == "definition"]
for definition in definitions:
    metadata = None
    for child in definition:
        if local_name(child.tag) == "metadata":
            metadata = child
            break
    if metadata is None:
        continue
    
    title = find_first_text(metadata, {"title"})
    description = find_first_text(metadata, {"description"})
    blob = " ".join(text.strip() for text in definition.itertext() if text and text.strip()).lower()
    
    if "openshift" not in blob:
        continue
    
    version_matches = set(re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", blob))
    if version_matches and target_version not in version_matches and major_minor not in version_matches:
        continue
    
    severity = find_severity(metadata)
    if severity_filter and severity != severity_filter:
        continue
    
    score = find_cvss_score(metadata)
    published = find_published(metadata)
    references = find_all_refs(metadata)
    cve_ids = sorted({ref_id for source, ref_id in references if ref_id.startswith("CVE-")})
    
    entry_ids = cve_ids if cve_ids else ["N/A"]
    for entry_id in entry_ids:
        record = {
            "id": entry_id,
            "title": title or "N/A",
            "severity": severity or "unknown",
            "score": score if score is not None else "N/A",
            "affected_versions": sorted(version_matches) if version_matches else [major_minor],
            "description": description or "N/A",
            "fixed_versions": [],
            "published": published,
            "cvss_vector": "N/A"
        }
        print(json.dumps(record))
PYTHON_SCRIPT
}


# Function to output as table
output_table() {
    local input_file=$1
    
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}OpenShift Vulnerabilities Report${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    python3 - "$input_file" << 'PYTHON_SCRIPT'
import json
import sys

try:
    vulns = []
    with open(sys.argv[1], 'r') as f:
        for line in f:
            if line.strip():
                try:
                    vulns.append(json.loads(line))
                except:
                    pass
    
    if not vulns:
        print("No vulnerabilities found for the specified criteria.")
        sys.exit(0)
    
    # Format and print table
    print(f"{'CVE ID':<15} {'Severity':<10} {'Score':<8} {'Published':<12}")
    print("-" * 60)
    
    for vuln in vulns:
        cve_id = vuln.get('id', 'N/A')
        severity = vuln.get('severity', 'N/A').upper()
        score = vuln.get('score', 'N/A')
        published = vuln.get('published', 'N/A')
        
        print(f"{cve_id:<15} {severity:<10} {score:<8} {published:<12}")
        print(f"  Title: {vuln.get('title', 'N/A')}")
        print(f"  Description: {vuln.get('description', 'N/A')[:60]}...")
        print(f"  Fixed in: {', '.join(vuln.get('fixed_versions', []))}")
        print(f"  CVSS Vector: {vuln.get('cvss_vector', 'N/A')}")
        print()
except Exception as e:
    print(f"Error processing vulnerabilities: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT
}

# Function to output as CSV
output_csv() {
    local input_file=$1
    
    python3 - "$input_file" << 'PYTHON_SCRIPT'
import json
import sys
import csv

vulns = []
with open(sys.argv[1], 'r') as f:
    for line in f:
        if line.strip():
            try:
                vulns.append(json.loads(line))
            except:
                pass

if vulns:
    writer = csv.DictWriter(sys.stdout, fieldnames=['id', 'title', 'severity', 'score', 'published', 'fixed_versions', 'cvss_vector'])
    writer.writeheader()
    for vuln in vulns:
        writer.writerow({
            'id': vuln.get('id'),
            'title': vuln.get('title'),
            'severity': vuln.get('severity'),
            'score': vuln.get('score'),
            'published': vuln.get('published'),
            'fixed_versions': ';'.join(vuln.get('fixed_versions', [])),
            'cvss_vector': vuln.get('cvss_vector')
        })
PYTHON_SCRIPT
}

# Function to output as JSON
output_json() {
    local input_file=$1
    
    python3 - "$input_file" << 'PYTHON_SCRIPT'
import json
import sys

vulns = []
with open(sys.argv[1], 'r') as f:
    for line in f:
        if line.strip():
            try:
                vulns.append(json.loads(line))
            except:
                pass

print(json.dumps({"vulnerabilities": vulns, "count": len(vulns)}, indent=2))
PYTHON_SCRIPT
}

# Main execution
main() {
    local version="${1:-}"
    
    if [ -z "$version" ]; then
        usage
    fi
    
    validate_version "$version"
    
    echo -e "${BLUE}[*] Gathering vulnerability data for OpenShift ${version}...${NC}" >&2
    
    # Fetch data from various sources
    fetch_red_hat_advisories "$version"
    fetch_nvd_data "$version"
    filtered_data=$(parse_red_hat_oval_vulnerabilities "$version")
    filtered_file="$TEMP_DIR/filtered_vulns.jsonl"
    printf '%s\n' "$filtered_data" > "$filtered_file"
    
    # Output in requested format
    case "$OUTPUT_FORMAT" in
        json)
            output_json "$filtered_file"
            ;;
        csv)
            output_csv "$filtered_file"
            ;;
        table|*)
            output_table "$filtered_file"
            ;;
    esac
    
    echo -e "${BLUE}[*] Report generation complete${NC}" >&2
}

main "$@"
