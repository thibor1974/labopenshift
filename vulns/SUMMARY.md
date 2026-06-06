# OpenShift Vulnerability Scanner - Summary

## What You've Got

A comprehensive vulnerability scanning solution with **three complementary tools** for querying vulnerabilities affecting OpenShift versions.

### 📁 Files in This Directory

```
vulns/
├── get_vulnerabilities.sh           # Main bash script (RECOMMENDED)
├── get_vulnerabilities_advanced.sh  # Advanced bash with Red Hat OVAL parsing
├── get_vulnerabilities.py           # Python version with advanced features
├── VULNERABILITIES_README.md        # Comprehensive documentation
├── QUICK_REFERENCE.md              # Quick reference guide & examples
└── SUMMARY.md                       # This file
```

---

## 🚀 Quick Start

### Option 1: Bash (Recommended for most users)
```bash
./get_vulnerabilities.sh 4.12.0
./get_vulnerabilities.sh 4.12.0 csv > report.csv
./get_vulnerabilities.sh 4.12.0 json > report.json
```

### Option 2: Python (More features)
```bash
./get_vulnerabilities.py 4.12.0
./get_vulnerabilities.py 4.12.0 --severity critical --format table
./get_vulnerabilities.py 4.12.0 --format stats
```

---

## 📊 Key Features

✅ **Multiple Output Formats**
- Table (human-readable with colors)
- CSV (for Excel/data analysis)
- JSON (for programmatic use)
- Statistics (summary view)

✅ **Filtering Capabilities**
- Filter by OpenShift version
- Filter by severity level (critical, high, medium, low)
- Version range matching (e.g., 4.12.0-4.12.10)

✅ **Data Sources**
- Red Hat Security Advisories API
- National Vulnerability Database (NVD)
- Local sample data (for demo/testing)
- Can be extended with custom sources

✅ **Production-Ready**
- Color-coded output
- Error handling
- Version validation
- Caching support
- Cross-platform (Linux/macOS)

---

## 📖 Usage Examples

### List all vulnerabilities for a version
```bash
./get_vulnerabilities.py 4.12.0
```

### Get critical vulnerabilities only
```bash
./get_vulnerabilities.py 4.12.0 --severity critical
./get_vulnerabilities.sh 4.12.0 table critical
```

### Export for reporting
```bash
./get_vulnerabilities.py 4.12.0 --format csv > vulnerabilities.csv
./get_vulnerabilities.sh 4.12.0 json > data.json
```

### Generate statistics
```bash
./get_vulnerabilities.py 4.12.0 --format stats
```

### Batch process multiple versions
```bash
for version in 4.10.0 4.11.0 4.12.0; do
    ./get_vulnerabilities.py $version --format csv > vuln_$version.csv
done
```

---

## 🔧 Which Script to Use?

| Need | Use |
|------|-----|
| Quick vulnerability check | `get_vulnerabilities.py` |
| Simple bash automation | `get_vulnerabilities.sh` |
| Parse Red Hat OVAL data | `get_vulnerabilities_advanced.sh` |
| Integration with other tools | `get_vulnerabilities.py --format json` |
| Export to Excel | `get_vulnerabilities.sh 4.12.0 csv` |

---

## 📝 Sample Data Included

The scripts include sample vulnerability data for demonstration:

- **CVE-2024-1234**: Kubernetes Engine Vulnerability (HIGH)
- **CVE-2024-5678**: API Server DoS (HIGH)  
- **CVE-2023-9101**: CLI Path Traversal (MEDIUM)
- **CVE-2024-1111**: Storage Plugin Integer Overflow (CRITICAL)

This allows testing without requiring network access.

---

## 🔌 Integration Examples

### Jenkins Pipeline
```groovy
stage('Scan Vulnerabilities') {
    steps {
        sh './get_vulnerabilities.py ${OCP_VERSION} --format json > vulns.json'
    }
}
```

### Cron Job (Daily Scans)
```bash
#!/bin/bash
REPORT_DIR="./vulnerability_reports"
mkdir -p "$REPORT_DIR"

for version in 4.10.0 4.11.0 4.12.0; do
    ./get_vulnerabilities.sh $version csv > \
        "$REPORT_DIR/vulns_${version}_$(date +%Y%m%d).csv"
done
```

### Kubernetes CronJob
```yaml
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: scanner
            command: [./get_vulnerabilities.sh, 4.12.0, csv]
```

---

## 📋 Output Formats

### Table
```
═════════════════════════════════════════════════════
CVE ID          Severity   Score    Published
─────────────────────────────────────────────────────
CVE-2024-1111   CRITICAL   9.8      2024-01-20
  Title: OpenShift Storage Plugin Integer Overflow
  Fixed in: 4.11.21, 4.12.6
```

### CSV
```csv
CVE ID,Title,Severity,Score,Published,Fixed Versions
CVE-2024-1111,OpenShift Storage Plugin...,critical,9.8,2024-01-20,"4.11.21;4.12.6"
```

### JSON
```json
{
  "version": "4.12.0",
  "count": 3,
  "vulnerabilities": [
    {"id": "CVE-2024-1111", "severity": "critical", ...}
  ]
}
```

---

## 🎯 Common Tasks

### Create Weekly Vulnerability Report
```bash
#!/bin/bash
./get_vulnerabilities.py 4.12.0 --format csv \
    > "vulnerability_report_$(date +%Y%m%d).csv"
```

### Find All Critical Issues
```bash
./get_vulnerabilities.py 4.12.0 --severity critical --format table
```

### Monitor for New Vulnerabilities
```bash
CURRENT=$(./get_vulnerabilities.py 4.12.0 --format json | jq '.count')
if [ "$CURRENT" -gt 0 ]; then
    echo "ALERT: $CURRENT vulnerabilities found!"
fi
```

### Export for Security Dashboard
```bash
./get_vulnerabilities.py 4.12.0 --format json | \
    curl -X POST http://dashboard.local/api/vulns -d @-
```

---

## 🔍 Advanced Features

### Extend with Custom Data
Edit the vulnerability database in either script to add your own data.

### Parse Official Red Hat Data
Use `get_vulnerabilities_advanced.sh` to parse Red Hat's official OVAL security feed.

### Cache Remote Data
The advanced script automatically caches Red Hat data for 24 hours.

### Severity Filtering
Quickly focus on critical issues:
```bash
./get_vulnerabilities.py 4.12.0 --severity critical
```

---

## ⚠️ Known Limitations

- Sample data is included for demo purposes
- Remote data sources require internet connectivity
- Some APIs may have rate limiting
- Red Hat data requires proper authentication in production

---

## 📚 Documentation

- **QUICK_REFERENCE.md** - Copy-paste examples and quick answers
- **VULNERABILITIES_README.md** - Full detailed documentation
- Run `./get_vulnerabilities.py --help` for help

---

## 🚀 Next Steps

1. **Test it out:**
   ```bash
   ./get_vulnerabilities.py 4.12.0
   ```

2. **Try different formats:**
   ```bash
   ./get_vulnerabilities.sh 4.12.0 csv
   ```

3. **Filter by severity:**
   ```bash
   ./get_vulnerabilities.py 4.12.0 --severity critical
   ```

4. **Integrate into your automation:**
   - Add to CI/CD pipelines
   - Schedule regular scans
   - Export for compliance reports

---

## 📞 Support

For more information:
- Red Hat Security: https://access.redhat.com/security/
- OpenShift Documentation: https://docs.openshift.com/
- CVE Search: https://cve.mitre.org/
