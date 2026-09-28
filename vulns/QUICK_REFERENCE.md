# Quick Reference - OpenShift Vulnerability Scanner

## Available Scripts

You have **three** vulnerability scanning scripts:

1. **get_vulnerabilities.sh** - Bash script (recommended - use Red Hat API)
2. **get_vulnerabilities_advanced.sh** - Advanced bash with jq support
3. **get_vulnerabilities.py** - Python version (cross-platform, more features)

---

## Quick Start

### Using the Bash Script

```bash
# Basic usage (fetches real vulnerabilities from Red Hat API)
./get_vulnerabilities.sh 4.21

# Show in different formats
./get_vulnerabilities.sh 4.21 csv > report.csv
./get_vulnerabilities.sh 4.21 json > report.json

# Filter by severity
./get_vulnerabilities.sh 4.21 table important
./get_vulnerabilities.sh 4.21 csv moderate

# Lookup specific CVE details (NEW!)
./get_vulnerabilities.sh --cve CVE-2026-46300
```

### Using the Python Script

```bash
# Basic usage
./get_vulnerabilities.py 4.21

# Show in different formats
./get_vulnerabilities.py 4.21 --format csv > report.csv
./get_vulnerabilities.py 4.21 --format json > report.json
./get_vulnerabilities.py 4.21 --format stats

# Filter by severity
./get_vulnerabilities.py 4.21 --severity important
./get_vulnerabilities.py 4.21 -s moderate -f csv

# Lookup specific CVE details (NEW!)
./get_vulnerabilities.py --cve CVE-2026-46300
```

Filter by advisory prefixes (RHSA/RHBA):
```bash
./get_vulnerabilities.py 4.21 --format json --advisory-prefix RHSA,RHBA | jq '.vulnerabilities[]'
```

### Using the Advanced Bash Script

```bash
# Fastest execution (uses jq, falls back to Python if needed)
./get_vulnerabilities_advanced.sh 4.21

# With format options
./get_vulnerabilities_advanced.sh 4.21 csv
```

---

## CVE Details & Fix Status (NEW!)

Check if a specific CVE is fixed in your OpenShift versions:

```bash
# Get detailed information about a CVE
./get_vulnerabilities.py --cve CVE-2026-46300

# Or using bash
./get_vulnerabilities.sh --cve CVE-2026-46300
```

Output shows:
- CVE severity and publication date
- Which OpenShift versions have the fix
- Advisory references and package information
- Full description

## Complete Usage Examples

### Example 2: Export important vulnerabilities as CSV
```bash
./get_vulnerabilities.sh 4.21 csv important > important_vulns.csv
```

### Example 3: Get JSON data for programmatic processing
```bash
./get_vulnerabilities.py 4.21 --format json | jq '.vulnerabilities[] | select(.severity=="important")'
```

### Example 4: Generate vulnerability statistics
```bash
./get_vulnerabilities.py 4.21 --format stats
```

### Example 5: Check if a CVE is fixed in your version
```bash
# Get full details including which versions have fixes
./get_vulnerabilities.py --cve CVE-2026-46300

# Or extract just the fix information
./get_vulnerabilities.sh --cve CVE-2026-46300 | grep -A5 "Fixed in OpenShift"
```

This shows:
- Severity and publication date
- Which OpenShift versions have the fix (with advisory IDs)
- Which versions are still affected
- Detailed description

### Example 6: Check only important vulnerabilities
```bash
./get_vulnerabilities.sh 4.21 table important
```

### Example 7: Batch check multiple versions
```bash
for version in 4.19 4.20 4.21; do
    echo "=== Checking OpenShift $version ==="
    ./get_vulnerabilities.py $version --format stats
done
```

### Example 8: Create a vulnerability report with timestamp
```bash
VERSION="4.21"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
./get_vulnerabilities.sh $VERSION csv > "vulns_${VERSION}_${TIMESTAMP}.csv"
```

---

## Choosing Which Script

| Script | Best For | Language | Speed | Features |
|--------|----------|----------|-------|----------|
| **get_vulnerabilities.sh** | General use | Bash | Fast | All formats, good balance |
| **get_vulnerabilities_advanced.sh** | Fastest execution | Bash | Fastest | jq-based, lightweight |
| **get_vulnerabilities.py** | Advanced filtering | Python | Fast | Rich CLI, statistics, cross-platform |

---

## Output Format Reference

### Table Format (Default - with fix advisory)
```
════════════════════════════════════════════════════════════════════════════════════════════════════
OpenShift 4.12 - Vulnerabilities Report
════════════════════════════════════════════════════════════════════════════════════════════════════

CVE ID           Severity   Fix (4.12)        Date        Description
----------------------------------------------------------------------------------------------------------------------------------
CVE-2026-43037   CRITICAL   RHSA-2026:26528   2026-05-01  kernel: ip6_tunnel: clear skb2->cb[] in ip4ip6_err()
CVE-2023-49569   CRITICAL   RHSA-2024:0832    2024-01-09  go-git: Maliciously crafted Git server replies can lead to path traver

Total: 2 vulnerabilities found
Fix (4.12): advisory fixing the CVE in this stream; '-' = no fix listed, '?' = lookup failed
```

The **"Fix (X.Y)"** column shows the earliest Red Hat advisory that fixes the CVE in the requested stream
(from the CVE's `affected_release` data). `-` means Red Hat lists no fix for that stream, `?` means the
per-CVE lookup failed. The API does not expose the exact z-stream (e.g. 4.12.x) a fix shipped in; look up the
advisory to find it.

> **Note:** the product query returns every CVE associated with the version, **including ones already fixed**.
> Treat the list as "CVEs relevant to 4.12", not "open vulnerabilities". Also, a CVE's `advisories` list covers
> all Red Hat products, so `--advisory-prefix` matches advisories from any product, not only this stream.

### CSV Format
```csv
CVE,severity,public_date,bugzilla,description,advisories
CVE-2026-43037,critical,2026-05-01T00:00:00Z,2464351,kernel: ip6_tunnel: clear skb2->cb[] in ip4ip6_err(),RHSA-2026:28741;RHSA-2026:28742;...
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
      "advisories": ["RHSA-2026:21695", "..."],
      "bugzilla": "2477015",
      "bugzilla_description": "kernel: ...",
      "resource_url": "https://access.redhat.com/hydra/rest/securitydata/cve/CVE-2026-46300.json"
    }
  ],
  "source": "Red Hat Security Advisory API"
}
```

---

## Common Tasks

### Task: Create a weekly vulnerability report
```bash
#!/bin/bash
REPORT_DIR="./reports"
mkdir -p "$REPORT_DIR"

for version in 4.19 4.20 4.21; do
    echo "Generating report for OpenShift $version..."
    ./get_vulnerabilities.py "$version" --format csv \
        --output "$REPORT_DIR/vulns_${version}_$(date +%Y%m%d).csv"
done

echo "Reports generated in $REPORT_DIR"
```

### Task: Get only important issues
```bash
./get_vulnerabilities.py 4.21 --severity important --format table
```

### Task: Export for external tools
```bash
# Export as JSON for Splunk/ELK/other tools
./get_vulnerabilities.py 4.21 --format json > /var/log/ocp-vulns.json

# Export as CSV for Excel
./get_vulnerabilities.sh 4.21 csv > vulnerability_report.csv
```

### Task: Monitor specific severity levels
```bash
#!/bin/bash
VERSION=$1
SEVERITY=${2:-critical}

CRITICAL_COUNT=$(./get_vulnerabilities.py "$VERSION" --severity "$SEVERITY" --format json | jq '.count')

if [ "$CRITICAL_COUNT" -gt 0 ]; then
    echo "WARNING: Found $CRITICAL_COUNT $SEVERITY vulnerabilities in OpenShift $VERSION"
    # Send alert, create ticket, etc.
fi
```

---

## Troubleshooting

### "Command not found"
```bash
# Make sure scripts are executable
chmod +x get_vulnerabilities.sh
chmod +x get_vulnerabilities.py
```

### "Python3 not found"
```bash
# For Python script, ensure Python 3.6+ is installed
python3 --version

# Or use the bash version instead
./get_vulnerabilities.sh 4.12
```

### Network issues when fetching data
```bash
# All scripts retry failed requests, then exit with code 1 and an error on stderr.
# A network/API failure never produces an empty report.
curl -sSf 'https://access.redhat.com/hydra/rest/securitydata/cve.json?per_page=1' >/dev/null && echo "API reachable"
```

---

## Integration Examples

### With Jenkins
```groovy
pipeline {
    stages {
        stage('Scan Vulnerabilities') {
            steps {
                script {
                    sh './get_vulnerabilities.py ${OCP_VERSION} --format json > vulns.json'
                    def vulns = readJSON file: 'vulns.json'
                    if (vulns.count > 0) {
                        unstable("Found ${vulns.count} vulnerabilities")
                    }
                }
            }
        }
    }
}
```

### With Kubernetes CronJob
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ocp-vuln-scanner
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
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
              ./get_vulnerabilities.sh 4.12 csv > /reports/vulns_$(date +%Y%m%d).csv
            volumeMounts:
            - name: reports
              mountPath: /reports
          volumes:
          - name: reports
            persistentVolumeClaim:
              claimName: scanner-reports
          restartPolicy: OnFailure
```

---

## Support & Documentation

- Full documentation: See `VULNERABILITIES_README.md`
- Red Hat Security: https://access.redhat.com/security/
- OpenShift Docs: https://docs.openshift.com/
- CVE Database: https://cve.mitre.org/
