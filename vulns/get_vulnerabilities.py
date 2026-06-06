#!/usr/bin/env python3

"""
OpenShift Vulnerability Scanner - Python Version
Query and list vulnerabilities affecting specific OpenShift versions
"""

import argparse
import json
import sys
import requests
from datetime import datetime
from typing import List, Dict, Optional
import re
from pathlib import Path

class VulnerabilityScanner:
    """Main vulnerability scanner class"""
    
    # Sample vulnerability database
    SAMPLE_VULNS = [
        {
            "id": "CVE-2024-1234",
            "title": "OpenShift Kubernetes Engine Vulnerability",
            "severity": "high",
            "score": 7.5,
            "affected_versions": ["4.10.0-4.10.50", "4.11.0-4.11.40", "4.12.0-4.12.10"],
            "description": "A flaw was found in OpenShift Kubernetes Engine where improper validation allows local attackers to gain elevated privileges.",
            "fixed_versions": ["4.10.51", "4.11.41", "4.12.11"],
            "published": "2024-01-15",
            "cvss_vector": "CVSS:3.1/AV:L/AU:L/C:H/I:H/A:H",
            "url": "https://access.redhat.com/security/cve/cve-2024-1234"
        },
        {
            "id": "CVE-2024-5678",
            "title": "OpenShift API Server Denial of Service",
            "severity": "high",
            "score": 7.5,
            "affected_versions": ["4.11.0-4.11.50", "4.12.0-4.12.20"],
            "description": "A vulnerability in the OpenShift API Server allows remote unauthenticated attackers to cause a denial of service.",
            "fixed_versions": ["4.11.51", "4.12.21"],
            "published": "2024-02-10",
            "cvss_vector": "CVSS:3.1/AV:N/AU:N/C:N/I:N/A:H",
            "url": "https://access.redhat.com/security/cve/cve-2024-5678"
        },
        {
            "id": "CVE-2023-9101",
            "title": "OpenShift CLI Path Traversal",
            "severity": "medium",
            "score": 5.5,
            "affected_versions": ["4.10.0-4.10.60", "4.11.0-4.11.30"],
            "description": "Path traversal vulnerability in OpenShift CLI allows attackers to read arbitrary files.",
            "fixed_versions": ["4.10.61", "4.11.31"],
            "published": "2023-09-05",
            "cvss_vector": "CVSS:3.1/AV:L/AU:L/C:H/I:N/A:N",
            "url": "https://access.redhat.com/security/cve/cve-2023-9101"
        },
        {
            "id": "CVE-2024-1111",
            "title": "OpenShift Storage Plugin Integer Overflow",
            "severity": "critical",
            "score": 9.8,
            "affected_versions": ["4.11.0-4.11.20", "4.12.0-4.12.5"],
            "description": "Critical integer overflow in OpenShift storage plugin allows remote code execution.",
            "fixed_versions": ["4.11.21", "4.12.6"],
            "published": "2024-01-20",
            "cvss_vector": "CVSS:3.1/AV:N/AU:N/C:H/I:H/A:H",
            "url": "https://access.redhat.com/security/cve/cve-2024-1111"
        }
    ]
    
    def __init__(self):
        self.vulns = self.SAMPLE_VULNS.copy()
    
    def validate_version(self, version: str) -> bool:
        """Validate version format"""
        return bool(re.match(r'^\d+\.\d+(\.\d+)?$', version))
    
    def parse_version(self, version: str) -> tuple:
        """Parse version string into components"""
        parts = version.split('.')
        return tuple(int(p) for p in parts)
    
    def is_version_in_range(self, version: str, version_range: str) -> bool:
        """Check if a version is within a range (e.g., '4.10.0-4.10.50')"""
        if '-' not in version_range:
            return version == version_range
        
        try:
            start_str, end_str = version_range.split('-')
            start = self.parse_version(start_str)
            end = self.parse_version(end_str)
            target = self.parse_version(version)
            
            return start <= target <= end
        except (ValueError, AttributeError):
            return False
    
    def filter_vulnerabilities(self, version: str, severity: Optional[str] = None) -> List[Dict]:
        """Filter vulnerabilities for a specific version"""
        filtered = []
        
        for vuln in self.vulns:
            # Check if version is affected
            is_affected = any(
                self.is_version_in_range(version, affected)
                for affected in vuln.get('affected_versions', [])
            )
            
            if not is_affected:
                continue
            
            # Check severity filter
            if severity and vuln.get('severity', '').lower() != severity.lower():
                continue
            
            filtered.append(vuln)
        
        # Sort by severity and score
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        filtered.sort(key=lambda x: (
            severity_order.get(x.get('severity', 'low').lower(), 4),
            -float(x.get('score', 0))
        ))
        
        return filtered
    
    def fetch_from_nvd(self, version: str) -> List[Dict]:
        """Attempt to fetch data from NVD API"""
        try:
            url = f"https://services.nvd.nist.gov/rest/json/cves/1.0?keyword=openshift%20{version}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                return response.json().get('result', {}).get('CVE_Items', [])
        except Exception as e:
            print(f"Warning: Could not fetch from NVD: {e}", file=sys.stderr)
        return []
    
    def format_table(self, vulns: List[Dict], version: str) -> str:
        """Format vulnerabilities as table"""
        output = []
        output.append("\n" + "=" * 90)
        output.append(f"OpenShift {version} - Vulnerability Report")
        output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append("=" * 90 + "\n")
        
        if not vulns:
            output.append("No vulnerabilities found for the specified criteria.\n")
            return "\n".join(output)
        
        # Header
        output.append(f"{'CVE ID':<15} {'Severity':<10} {'Score':<7} {'Published':<12}")
        output.append("-" * 90)
        
        # Rows
        for vuln in vulns:
            cve_id = vuln.get('id', 'N/A')
            severity = vuln.get('severity', 'N/A').upper()
            score = vuln.get('score', 'N/A')
            published = vuln.get('published', 'N/A')
            
            output.append(f"{cve_id:<15} {severity:<10} {score:<7} {published:<12}")
            output.append(f"  Title: {vuln.get('title', 'N/A')}")
            output.append(f"  Description: {vuln.get('description', 'N/A')[:65]}...")
            output.append(f"  Fixed in: {', '.join(vuln.get('fixed_versions', []))}")
            output.append(f"  CVSS: {vuln.get('cvss_vector', 'N/A')}")
            if vuln.get('url'):
                output.append(f"  Reference: {vuln.get('url')}")
            output.append("")
        
        output.append(f"Total: {len(vulns)} vulnerabilities found\n")
        return "\n".join(output)
    
    def format_csv(self, vulns: List[Dict]) -> str:
        """Format vulnerabilities as CSV"""
        output = []
        output.append("CVE ID,Title,Severity,Score,Published,Fixed Versions,CVSS Vector,Reference")
        
        for vuln in vulns:
            row = [
                vuln.get('id', ''),
                f"\"{vuln.get('title', '')}\"",
                vuln.get('severity', ''),
                str(vuln.get('score', '')),
                vuln.get('published', ''),
                f"\"{';'.join(vuln.get('fixed_versions', []))}\"",
                vuln.get('cvss_vector', ''),
                vuln.get('url', '')
            ]
            output.append(",".join(row))
        
        return "\n".join(output)
    
    def format_json(self, vulns: List[Dict], version: str) -> str:
        """Format vulnerabilities as JSON"""
        data = {
            "version": version,
            "generated": datetime.now().isoformat(),
            "count": len(vulns),
            "vulnerabilities": vulns
        }
        return json.dumps(data, indent=2)
    
    def format_stats(self, vulns: List[Dict], version: str) -> str:
        """Generate statistics summary"""
        output = []
        output.append("\n" + "=" * 60)
        output.append(f"OpenShift {version} - Vulnerability Statistics")
        output.append("=" * 60 + "\n")
        output.append(f"Total Vulnerabilities: {len(vulns)}\n")
        
        if vulns:
            severity_counts = {}
            for vuln in vulns:
                severity = vuln.get('severity', 'unknown').lower()
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            output.append("By Severity:")
            for severity in ['critical', 'high', 'medium', 'low']:
                count = severity_counts.get(severity, 0)
                output.append(f"  {severity.upper()}: {count}")
            
            output.append(f"\nAverage CVSS Score: {sum(v.get('score', 0) for v in vulns) / len(vulns):.1f}")
        
        output.append("")
        return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description='OpenShift Vulnerability Scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s 4.12.0                          # List all vulnerabilities
  %(prog)s 4.12.0 --severity critical      # List critical vulnerabilities only
  %(prog)s 4.12.0 --format csv             # Export as CSV
  %(prog)s 4.12.0 --format json            # Export as JSON
  %(prog)s 4.12.0 --format stats           # Show statistics
        '''
    )
    
    parser.add_argument('version', help='OpenShift version (e.g., 4.12.0)')
    parser.add_argument(
        '--format', '-f',
        choices=['table', 'csv', 'json', 'stats'],
        default='table',
        help='Output format (default: table)'
    )
    parser.add_argument(
        '--severity', '-s',
        choices=['critical', 'high', 'medium', 'low'],
        help='Filter by severity level'
    )
    parser.add_argument(
        '--output', '-o',
        type=argparse.FileType('w'),
        default=sys.stdout,
        help='Output file (default: stdout)'
    )
    
    args = parser.parse_args()
    
    # Validate version
    scanner = VulnerabilityScanner()
    if not scanner.validate_version(args.version):
        print(f"Error: Invalid version format '{args.version}'", file=sys.stderr)
        print("Use format like: 4.12.0 or 4.11.5", file=sys.stderr)
        sys.exit(1)
    
    # Filter vulnerabilities
    vulns = scanner.filter_vulnerabilities(args.version, args.severity)
    
    # Format output
    if args.format == 'csv':
        output = scanner.format_csv(vulns)
    elif args.format == 'json':
        output = scanner.format_json(vulns, args.version)
    elif args.format == 'stats':
        output = scanner.format_stats(vulns, args.version)
    else:  # table
        output = scanner.format_table(vulns, args.version)
    
    # Write output
    args.output.write(output)
    args.output.write("\n")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
