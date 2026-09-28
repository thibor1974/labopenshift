# OpenShift Vulnerability Scanner - Summary

## What You've Got

A comprehensive vulnerability scanning solution with **three complementary tools** for querying **real vulnerabilities** affecting OpenShift versions using the official Red Hat Security API.

### 📁 Files in This Directory

```
vulns/
├── get_vulnerabilities.sh           # Main bash script (RECOMMENDED)
├── get_vulnerabilities_advanced.sh  # Advanced bash with jq support
├── get_vulnerabilities.py           # Python version with advanced features
├── VULNERABILITIES_README.md        # Comprehensive documentation
├── QUICK_REFERENCE.md              # Quick reference guide & examples
└── SUMMARY.md                       # This file
```

---

## 🚀 Quick Start

### Option 1: Bash (Recommended for most users)
```bash
./get_vulnerabilities.sh 4.21
./get_vulnerabilities.sh 4.21 csv > report.csv
./get_vulnerabilities.sh --cve CVE-2026-46300    # Check if a CVE is fixed
```

### Option 2: Python (Rich CLI)
```bash
./get_vulnerabilities.py 4.21
./get_vulnerabilities.py 4.21 --severity important --format table
./get_vulnerabilities.py 4.21 --format stats
./get_vulnerabilities.py --cve CVE-2026-46300    # Check if a CVE is fixed
```

### Option 3: Advanced Bash (jq-based, fastest)
```bash
./get_vulnerabilities_advanced.sh 4.21
./get_vulnerabilities_advanced.sh 4.21 csv
```

---

## � CVE Details & Fix Status (NEW!)

Check if a specific CVE is fixed in which OpenShift versions:

```bash
./get_vulnerabilities.py --cve CVE-2026-46300
# or
./get_vulnerabilities.sh --cve CVE-2026-46300
```

Shows:
- ✅ Which OpenShift versions have the fix (with advisories)
- ✅ Which versions are still vulnerable
- ✅ CVE severity and publication date
- ✅ Full vulnerability description

Example output:
```
Fixed in OpenShift versions:
  Product: Red Hat OpenShift Container Platform 4.12
    Advisory: RHSA-2026:21695
    
  Product: Red Hat OpenShift Container Platform 4.21
    Advisory: RHBA-2026:20032
```

---

## �📊 Data Source

✅ **Real Red Hat Security API** - Actual vulnerability data for OpenShift versions
- Uses: `https://access.redhat.com/hydra/rest/securitydata/cve.json`
- Returns: Current CVE data, severity levels, publication dates, and more

---

## 📖 Usage Examples

### List all vulnerabilities for a version
```bash
./get_vulnerabilities.py 4.21
```
Output: 27 vulnerabilities for OpenShift 4.21 (19 important, 8 moderate)

### Get only important/critical vulnerabilities
```bash
./get_vulnerabilities.py 4.21 --severity important
```

### Export to CSV for analysis
```bash
./get_vulnerabilities.sh 4.21 csv > vulnerabilities.csv
```

### Generate statistics
```bash
./get_vulnerabilities.py 4.21 --format stats
```

### Export to JSON for programmatic use
```bash
./get_vulnerabilities.sh 4.21 json > data.json
```

### Batch check multiple versions
```bash
for version in 4.20 4.21; do
    echo "=== OpenShift $version ==="
    ./get_vulnerabilities.py $version --format stats
done
```

---

## 🔧 Which Script to Use?

| Need | Recommended |
|------|-----|
| Quick check | `./get_vulnerabilities.py 4.21` |
| CSV export | `./get_vulnerabilities.sh 4.21 csv` |
| Statistics | `./get_vulnerabilities.py 4.21 --format stats` |
| Fastest execution | `./get_vulnerabilities_advanced.sh 4.21` |
| Filtering by severity | `./get_vulnerabilities.py 4.21 --severity important` |
| JSON output | `./get_vulnerabilities.sh 4.21 json` |

---

## 📋 Output Formats

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
    {"CVE": "CVE-2026-46300", "severity": "important", ...}
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

---

## 🎯 Common Tasks

### Create a vulnerability report with timestamp
```bash
VERSION="4.21"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
./get_vulnerabilities.sh $VERSION csv > "vulns_${VERSION}_${TIMESTAMP}.csv"
```

### Monitor for new vulnerabilities
```bash
#!/bin/bash
VERSION=$1
CURRENT=$(./get_vulnerabilities.py "$VERSION" --format json | jq '.count')

if [ "$CURRENT" -gt 0 ]; then
    echo "Found $CURRENT vulnerabilities in OpenShift $VERSION"
fi
```

### Check only important vulnerabilities
```bash
./get_vulnerabilities.sh 4.21 table important
```

### Export for external tools
```bash
./get_vulnerabilities.py 4.21 --format json | curl -X POST http://dashboard.local/api/vulns -d @-
```

---

## 🔌 Integration Examples

### Jenkins Pipeline
```groovy
stage('Scan Vulnerabilities') {
    steps {
        sh './get_vulnerabilities.py ${OCP_VERSION} --format json > vulns.json'
        def vulns = readJSON file: 'vulns.json'
        if (vulns.count > 10) {
            unstable("Found ${vulns.count} vulnerabilities")
        }
    }
}
```

### Bash Script (Daily Report)
```bash
#!/bin/bash
REPORT_DIR="./vulnerability_reports"
mkdir -p "$REPORT_DIR"

for version in 4.19 4.20 4.21; do
    ./get_vulnerabilities.sh $version csv > \
        "$REPORT_DIR/vulns_${version}_$(date +%Y%m%d).csv"
done
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

---

## ✅ Tested & Working

✓ All scripts produce real output  
✓ Fetches from official Red Hat Security API  
✓ Multiple output formats (table, CSV, JSON, stats)  
✓ Severity filtering (critical, important, moderate, low)  
✓ Exits with code 1 (never an empty report) when the API is unreachable  
✓ Table view ~10 seconds (per-CVE fix lookups run in parallel); CSV/JSON/stats ~1-2 seconds  
✓ Works on macOS and Linux  

---

## 📞 Support

For more information:
- Red Hat Security: https://access.redhat.com/security/
- OpenShift Documentation: https://docs.openshift.com/
- CVE Database: https://cve.mitre.org/
