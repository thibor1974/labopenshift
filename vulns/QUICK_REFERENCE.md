# Quick Reference - OpenShift Vulnerability Scripts

## Available Scripts

You have **three** vulnerability scanning scripts:

1. **get_vulnerabilities.sh** - Bash script (recommended for most use cases)
2. **get_vulnerabilities_advanced.sh** - Advanced bash with Red Hat OVAL parsing
3. **get_vulnerabilities.py** - Python version (cross-platform, more features)

---

## Quick Start

### Using the Bash Script

```bash
# Basic usage
./get_vulnerabilities.sh 4.12.0

# Show in different formats
./get_vulnerabilities.sh 4.12.0 csv > report.csv
./get_vulnerabilities.sh 4.12.0 json > report.json

# Filter by severity
./get_vulnerabilities.sh 4.12.0 table critical
./get_vulnerabilities.sh 4.12.0 csv high
```

### Using the Python Script

```bash
# Basic usage
./get_vulnerabilities.py 4.12.0

# Show in different formats
./get_vulnerabilities.py 4.12.0 --format csv > report.csv
./get_vulnerabilities.py 4.12.0 --format json > report.json
./get_vulnerabilities.py 4.12.0 --format stats

# Filter by severity
./get_vulnerabilities.py 4.12.0 --severity critical
./get_vulnerabilities.py 4.12.0 -s high -f csv
```

---

## Complete Usage Examples

### Example 1: Get all vulnerabilities for OpenShift 4.12.0
```bash
./get_vulnerabilities.sh 4.12.0
```

Output: Human-readable table with CVE details

### Example 2: Export critical vulnerabilities as CSV
```bash
./get_vulnerabilities.sh 4.12.0 csv critical > critical_vulns.csv
```

### Example 3: Get JSON data for programmatic processing
```bash
./get_vulnerabilities.py 4.12.0 --format json | jq '.vulnerabilities[] | select(.severity=="critical")'
```

### Example 4: Generate vulnerability statistics
```bash
./get_vulnerabilities.py 4.12.0 --format stats
```

Output:
```
============================================================
OpenShift 4.12.0 - Vulnerability Statistics
============================================================

Total Vulnerabilities: 4

By Severity:
  CRITICAL: 1
  HIGH: 2
  MEDIUM: 1

Average CVSS Score: 7.3
```

### Example 5: Check only high-severity vulnerabilities
```bash
./get_vulnerabilities.sh 4.11.5 table high
```

### Example 6: Batch check multiple versions
```bash
for version in 4.10.0 4.11.0 4.12.0; do
    echo "=== Checking OpenShift $version ==="
    ./get_vulnerabilities.py $version --format stats
done
```

### Example 7: Create a vulnerability report with timestamp
```bash
VERSION="4.12.0"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
./get_vulnerabilities.sh $VERSION csv > "vulns_${VERSION}_${TIMESTAMP}.csv"
```

---

## Choosing Which Script

| Script | Best For | Language | Features |
|--------|----------|----------|----------|
| **get_vulnerabilities.sh** | General use | Bash | Simple, fast, multiple formats |
| **get_vulnerabilities_advanced.sh** | Red Hat OVAL parsing | Bash | Parse official Red Hat security data |
| **get_vulnerabilities.py** | Advanced filtering | Python | Rich CLI, statistics, cross-platform |

---

## Output Format Reference

### Table Format
```
═══════════════════════════════════════════════════════════════════════════════
OpenShift Vulnerabilities Report
═══════════════════════════════════════════════════════════════════════════════

CVE ID          Severity   Score    Published
───────────────────────────────────────────────────────────────────────────────
CVE-2024-1234   HIGH       7.5      2024-01-15
  Title: OpenShift Kubernetes Engine Vulnerability
  Description: A flaw was found in OpenShift Kubernetes Engine...
  Fixed in: 4.10.51, 4.11.41, 4.12.11
  CVSS Vector: CVSS:3.1/AV:L/AU:L/C:H/I:H/A:H
```

### CSV Format
```csv
CVE ID,Title,Severity,Score,Published,Fixed Versions,CVSS Vector
CVE-2024-1234,"OpenShift Kubernetes Engine Vulnerability",high,7.5,2024-01-15,"4.10.51;4.11.41;4.12.11",CVSS:3.1/AV:L/AU:L/C:H/I:H/A:H
```

### JSON Format
```json
{
  "version": "4.12.0",
  "generated": "2024-06-06T10:30:45.123456",
  "count": 2,
  "vulnerabilities": [
    {
      "id": "CVE-2024-1234",
      "title": "OpenShift Kubernetes Engine Vulnerability",
      "severity": "high",
      ...
    }
  ]
}
```

---

## Common Tasks

### Task: Create a weekly vulnerability report
```bash
#!/bin/bash
REPORT_DIR="./reports"
mkdir -p "$REPORT_DIR"

for version in 4.10.0 4.11.0 4.12.0; do
    echo "Generating report for OpenShift $version..."
    ./get_vulnerabilities.py "$version" --format csv \
        --output "$REPORT_DIR/vulns_${version}_$(date +%Y%m%d).csv"
done

echo "Reports generated in $REPORT_DIR"
```

### Task: Get only critical issues
```bash
./get_vulnerabilities.py 4.12.0 --severity critical --format table
```

### Task: Export for external tools
```bash
# Export as JSON for Splunk/ELK/other tools
./get_vulnerabilities.py 4.12.0 --format json > /var/log/ocp-vulns.json

# Export as CSV for Excel
./get_vulnerabilities.sh 4.12.0 csv > vulnerability_report.csv
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
./get_vulnerabilities.sh 4.12.0
```

### "No module named packaging"
```bash
# For enhanced version comparison in bash script
pip install packaging

# Bash script will work without it, but with reduced accuracy
```

### Network issues when fetching data
```bash
# Scripts work with local data if network is unavailable
# Remote data sources will gracefully fall back to local samples
./get_vulnerabilities.sh 4.12.0
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
              ./get_vulnerabilities.sh 4.12.0 csv > /reports/vulns_$(date +%Y%m%d).csv
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
