# OpenShift Vulnerability Scanner

A comprehensive bash script to query and list vulnerabilities affecting specific OpenShift versions.

## Features

- **Multiple Output Formats**: Table, CSV, and JSON
- **Severity Filtering**: Filter by critical, high, medium, or low severity
- **Version Validation**: Ensures correct version format
- **Data Source Integration**: Supports Red Hat Security Advisories, NVD, and local data
- **Color-coded Output**: Enhanced readability
- **Cross-platform**: Works on Linux and macOS

## Installation

1. Copy the script to your workspace:
```bash
chmod +x get_vulnerabilities.sh
```

2. Optional: Install the `packaging` Python library for better version comparison:
```bash
pip install packaging
```

## Usage

### Basic Usage

```bash
# List all vulnerabilities for OpenShift 4.12.0
./get_vulnerabilities.sh 4.12.0

# List vulnerabilities in CSV format
./get_vulnerabilities.sh 4.12.0 csv

# List vulnerabilities in JSON format
./get_vulnerabilities.sh 4.12.0 json
```

### Filter by Severity

```bash
# Show only critical vulnerabilities
./get_vulnerabilities.sh 4.12.0 table critical

# Show only high severity vulnerabilities in CSV
./get_vulnerabilities.sh 4.11.5 csv high
```

### Examples

```bash
# Table format (default)
./get_vulnerabilities.sh 4.12.0

# CSV export for spreadsheets
./get_vulnerabilities.sh 4.12.0 csv > vulns_4.12.0.csv

# JSON for programmatic processing
./get_vulnerabilities.sh 4.12.0 json > vulns_4.12.0.json

# Filter critical vulnerabilities in table format
./get_vulnerabilities.sh 4.12.0 table critical

# Export high-severity vulnerabilities to CSV
./get_vulnerabilities.sh 4.11.5 csv high > critical_vulns.csv
```

## Output Formats

### Table Format (Default)
```
═════════════════════════════════════════════════════════════════════════════
OpenShift Vulnerabilities Report
═════════════════════════════════════════════════════════════════════════════

CVE ID          Severity   Score    Published
────────────────────────────────────────────────────────────────────────────
CVE-2024-1234   HIGH       7.5      2024-01-15
  Title: OpenShift Kubernetes Engine Vulnerability
  Description: A flaw was found in OpenShift Kubernetes Engine...
  Fixed in: 4.10.51, 4.11.41, 4.12.11
  CVSS Vector: CVSS:3.1/AV:L/AU:L/C:H/I:H/A:H
```

### CSV Format
```
id,title,severity,score,published,fixed_versions,cvss_vector
CVE-2024-1234,OpenShift Kubernetes Engine Vulnerability,high,7.5,2024-01-15,"4.10.51;4.11.41;4.12.11",CVSS:3.1/AV:L/AU:L/C:H/I:H/A:H
```

### JSON Format
```json
{
  "vulnerabilities": [
    {
      "id": "CVE-2024-1234",
      "title": "OpenShift Kubernetes Engine Vulnerability",
      "severity": "high",
      "score": 7.5,
      "affected_versions": ["4.10.0-4.10.50", "4.11.0-4.11.40"],
      "published": "2024-01-15",
      "cvss_vector": "CVSS:3.1/AV:L/AU:L/C:H/I:H/A:H"
    }
  ],
  "count": 1
}
```

## Data Sources

The script attempts to fetch data from multiple sources:

1. **Red Hat Security Advisories**: Official Red Hat security data
2. **National Vulnerability Database (NVD)**: NIST's vulnerability database
3. **Local Data**: Built-in sample data for demonstrations

## Extending the Script

### Adding Custom Vulnerability Data

Edit the `parse_local_vulnerabilities()` function to include your custom vulnerability data:

```bash
parse_local_vulnerabilities() {
    local version=$1
    
    cat > "$TEMP_DIR/vulns.json" << 'EOF'
{
  "vulnerabilities": [
    {
      "id": "CVE-XXXX-XXXXX",
      "title": "Your Vulnerability Title",
      "severity": "high",
      "score": 7.5,
      "affected_versions": ["4.12.0-4.12.10"],
      "description": "Vulnerability description",
      "fixed_versions": ["4.12.11"],
      "published": "2024-01-15",
      "cvss_vector": "CVSS:3.1/AV:L/AU:L/C:H/I:H/A:H"
    }
  ]
}
EOF
}
```

### Integrating with Red Hat Security Data

The script can be extended to parse Red Hat's official OVAL data. See the included `get_vulnerabilities_advanced.sh` for implementation details.

### Using with External APIs

For production environments, consider:

1. **Red Hat Security API**: https://access.redhat.com/security/data/
2. **NVD API**: https://services.nvd.nist.gov/rest/json/cves/1.0
3. **Grype**: Binary vulnerability scanner (recommended for container images)

## Requirements

- Bash 4.0 or later
- `curl` (for fetching remote data)
- `python3` (for JSON processing)
- Optional: `packaging` Python library (for enhanced version comparison)

## Exit Codes

- `0`: Successful execution
- `1`: Invalid version format or missing required arguments

## Limitations

- Local data contains sample vulnerabilities for demonstration
- Remote data sources require internet connectivity
- Some APIs may have rate limiting

## Production Recommendations

For production use, consider:

1. Caching results to avoid repeated API calls
2. Scheduling regular updates of vulnerability data
3. Integrating with vulnerability management platforms
4. Using official Red Hat security channels
5. Implementing alerting for new critical vulnerabilities

## Support

For issues or improvements, refer to your OpenShift documentation:
- https://docs.openshift.com/
- https://access.redhat.com/security/
