# OpenShift Vulnerability Scanner

A comprehensive bash/Python solution to query **real vulnerabilities** affecting specific OpenShift versions using the official Red Hat Security API.

## Features

✅ **Real-time Data** - Fetches from official Red Hat Security Advisory API  
✅ **Multiple Output Formats** - Table, CSV, JSON, and Statistics  
✅ **Severity Filtering** - Filter by critical, important, moderate, low  
✅ **Version Validation** - Enforces correct version format (X.Y)  
✅ **Fast Performance** - Results in seconds  
✅ **Cross-platform** - Works on Linux and macOS  
✅ **Three Implementations** - Bash, Advanced Bash, and Python options  

## Installation

Scripts are ready to use immediately:
```bash
chmod +x *.sh *.py
```

## Usage

### Basic Usage

```bash
# List all vulnerabilities for OpenShift 4.21
./get_vulnerabilities.sh 4.21

# List vulnerabilities in CSV format
./get_vulnerabilities.sh 4.21 csv

# List vulnerabilities in JSON format
./get_vulnerabilities.sh 4.21 json

# Show statistics for OpenShift 4.21
./get_vulnerabilities.py 4.21 --format stats

# Lookup details and fix status for a specific CVE
./get_vulnerabilities.py --cve CVE-2026-46300
./get_vulnerabilities.sh --cve CVE-2026-46300
```

### CVE Details & Fix Status (NEW!)

Check if a specific CVE is fixed and in which versions:

```bash
# Get comprehensive details about a CVE
./get_vulnerabilities.py --cve CVE-2026-46300
```

Shows:
- CVE severity and publication date
- CVSS vector (if available)
- **Which OpenShift versions have fixes** (with advisory IDs)
- **Which versions are still affected**
- Full vulnerability description

Example scenario:
```bash
# You found CVE-2026-46300 in your environment
# Check if upgrading to 4.21 will fix it:
./get_vulnerabilities.sh --cve CVE-2026-46300

# Output shows it's fixed in 4.21, 4.20, 4.18, etc.
# and provides the specific advisory/package details
```

### Filter by Severity

```bash
# Show only important vulnerabilities (bash)
./get_vulnerabilities.sh 4.21 table important

# Show only important vulnerabilities in CSV
./get_vulnerabilities.sh 4.21 csv important

# Python version with severity filter
./get_vulnerabilities.py 4.21 --severity important
```

### Examples

```bash
# Table format (default)
./get_vulnerabilities.sh 4.21

# CSV export for spreadsheets
./get_vulnerabilities.sh 4.21 csv > vulns_4.21.csv

# JSON for programmatic processing
./get_vulnerabilities.sh 4.21 json > vulns_4.21.json

# Statistics summary
./get_vulnerabilities.py 4.21 --format stats

# Export important vulnerabilities to CSV
./get_vulnerabilities.sh 4.21 csv important > important_vulns.csv

# Python with all options
./get_vulnerabilities.py 4.21 --severity important --format csv --output report.csv

# Advanced bash script (fastest)
./get_vulnerabilities_advanced.sh 4.21 csv > report.csv
```

## Output Formats

### Table Format (Default - with Fixed Version Info)
```
════════════════════════════════════════════════════════════════════════════════════════════════════
OpenShift 4.21 - Vulnerabilities Report
════════════════════════════════════════════════════════════════════════════════════════════════════

CVE ID          Severity     Fixed In   Date         Impact                             
────────────────────────────────────────────────────────────────────────────────────────────────────
CVE-2026-46300  IMPORTANT    4.12       2026-05-13T12:00:00Z N/A                
CVE-2026-41674  IMPORTANT    4.2        2026-05-07T03:47:51Z N/A                
CVE-2026-43284  IMPORTANT    4.12       2026-05-07T00:00:00Z N/A                

Total: 27 vulnerabilities found
```

**New Feature:** The "Fixed In" column shows the earliest OpenShift version where the vulnerability is fixed, helping you determine which upgrade resolves the issue.

### CSV Format
```csv
CVE,severity,public_date,bugzilla_id,impact
CVE-2026-46300,important,2026-05-13T12:00:00Z,,
CVE-2026-41674,important,2026-05-07T03:47:51Z,,
CVE-2026-43284,important,2026-05-07T00:00:00Z,,
```

### JSON Format
```json
{
  "version": "4.21",
  "count": 27,
  "vulnerabilities": [
    {
      "CVE": "CVE-2026-46300",
      "severity": "important",
      "public_date": "2026-05-13T12:00:00Z",
      "bugzilla_id": "2477015",
      "impact": "N/A"
    }
  ],
  "source": "Red Hat Security Advisory API"
}
```

### Statistics Format
```
============================================================
OpenShift 4.21 - Vulnerability Statistics
============================================================

Total Vulnerabilities: 27

By Severity:
  CRITICAL: 0
  IMPORTANT: 19
  MODERATE: 8
  LOW: 0
```

## Data Sources

The scripts fetch data from:
- **Red Hat Security Advisory API**: Official vulnerability database
- URL: `https://access.redhat.com/hydra/rest/securitydata/cve.json`
- Returns: Real-time CVE data for all OpenShift versions

## Script Comparison

| Feature | Bash | Python | Advanced |
|---------|------|--------|----------|
| Table output | ✓ | ✓ | ✓ |
| CSV output | ✓ | ✓ | ✓ |
| JSON output | ✓ | ✓ | ✗ |
| Statistics | ✗ | ✓ | ✗ |
| Severity filter | ✓ | ✓ | ✗ |
| Speed | Fast | Fast | Fastest |
| jq required | ✗ | ✗ | Optional |

## Version Format

The scripts expect version format: **X.Y** (e.g., `4.21`, `4.20`, `4.19`)

Do NOT use:
- ❌ `4.21.0` (with patch version)
- ❌ `4.21.x` (with wildcard)

## Requirements

- Bash 4.0+ (for bash scripts)
- Python 3.6+ (for Python script)
- `curl` (for API calls)
- Optional: `jq` (for advanced bash script, has fallback)

## Exit Codes

- `0`: Successful execution
- `1`: Invalid version format or error

## Common Tasks

### List vulnerabilities for a single version
```bash
./get_vulnerabilities.sh 4.21
```

### Export to CSV for compliance reports
```bash
./get_vulnerabilities.sh 4.21 csv > vulnerability_report_$(date +%Y%m%d).csv
```

### Check multiple versions
```bash
for version in 4.19 4.20 4.21; do
    echo "=== OpenShift $version ==="
    ./get_vulnerabilities.py $version --format stats
done
```

### Monitor only critical vulnerabilities
```bash
CRITICAL=$(./get_vulnerabilities.sh 4.21 | grep CRITICAL | wc -l)
echo "Critical vulnerabilities: $CRITICAL"
```

### Export for vulnerability management system
```bash
./get_vulnerabilities.sh 4.21 json | curl -X POST http://vuln-mgmt.local/api/import -d @-
```

## Production Usage

### Scheduling daily scans
```bash
# Add to crontab
0 2 * * * /path/to/vulns/get_vulnerabilities.sh 4.21 csv > /reports/vulns_$(date +\%Y\%m\%d).csv
```

### Integrating with monitoring
```bash
#!/bin/bash
COUNT=$(./get_vulnerabilities.py 4.21 --format json | jq '.count')
if [ "$COUNT" -gt 20 ]; then
    # Send alert
    mail -s "High vulnerability count" admin@example.com
fi
```

### Kubernetes CronJob
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ocp-vuln-scanner
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: scanner
            image: quay.io/my-org/ocp-scanner:latest
            command:
            - /bin/bash
            - -c
            - |
              ./get_vulnerabilities.sh 4.21 csv > /reports/vulns_$(date +%Y%m%d).csv
```

## Supported OpenShift Versions

The scripts work with any OpenShift version available in Red Hat Security API:
- 4.1 through 4.21+ (as of last update)
- Enterprise versions (3.11, etc.) - check Red Hat docs

## Support

For more information:
- Red Hat Security: https://access.redhat.com/security/
- OpenShift Docs: https://docs.openshift.com/
- CVE Database: https://cve.mitre.org/
