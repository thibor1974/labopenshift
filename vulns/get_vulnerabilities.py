#!/usr/bin/env python3

"""
OpenShift Vulnerability Scanner - Python Version
Query vulnerabilities affecting specific OpenShift versions using Red Hat Security API
"""

import argparse
import json
import sys
import subprocess
from datetime import datetime
from typing import List, Dict, Optional

class VulnerabilityScanner:
    """Vulnerability scanner using Red Hat Security API"""
    
    def __init__(self):
        self.api_base = "https://access.redhat.com/hydra/rest/securitydata/cve.json"
    
    def validate_version(self, version: str) -> bool:
        """Validate version format (e.g., 4.21, 4.12)"""
        parts = version.split('.')
        if len(parts) != 2:
            return False
        return all(part.isdigit() for part in parts)
    
    def fetch_vulnerabilities(self, version: str) -> List[Dict]:
        """Fetch vulnerabilities from Red Hat API"""
        url = f"{self.api_base}?product=Red%20Hat%20OpenShift%20Container%20Platform%20{version}&per_page=1000"
        
        try:
            print(f"[*] Fetching vulnerabilities for OpenShift {version}...", file=sys.stderr)
            
            # Use curl instead of urllib to avoid 403 errors
            import subprocess
            result = subprocess.run(
                ['curl', '-s', '--connect-timeout', '10', url],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                print(f"[!] Curl error: {result.stderr}", file=sys.stderr)
                return []
            
            data = json.loads(result.stdout)
            
            # Handle both list and dict responses
            if isinstance(data, dict):
                return data.get('data', []) if 'data' in data else []
            elif isinstance(data, list):
                return data
            else:
                return []
        
        except json.JSONDecodeError:
            print(f"[!] Error parsing JSON response", file=sys.stderr)
            return []
        except Exception as e:
            print(f"[!] Unexpected error: {e}", file=sys.stderr)
            return []
    
    def filter_vulnerabilities(self, vulns: List[Dict], severity: Optional[str] = None) -> List[Dict]:
        """Filter vulnerabilities by severity"""
        if not severity:
            return vulns
        
        severity_lower = severity.lower()
        return [v for v in vulns if v.get('severity', '').lower() == severity_lower]
    
    def sort_vulnerabilities(self, vulns: List[Dict]) -> List[Dict]:
        """Sort vulnerabilities by severity"""
        severity_order = {'critical': 0, 'important': 1, 'moderate': 2, 'low': 3}
        return sorted(vulns, key=lambda x: severity_order.get(x.get('severity', 'low').lower(), 4))
    
    def format_table(self, vulns: List[Dict], version: str) -> str:
        """Format as human-readable table"""
        output = []
        output.append("")
        output.append("═" * 80)
        output.append(f"OpenShift {version} - Vulnerabilities Report")
        output.append("═" * 80)
        output.append("")
        
        if not vulns:
            output.append("No vulnerabilities found for the specified criteria.")
            output.append("")
            return "\n".join(output)
        
        # Header
        output.append(f"{'CVE ID':<15} {'Severity':<12} {'Date':<12} {'Impact':<20}")
        output.append("-" * 80)
        
        # Rows
        for vuln in vulns:
            cve = vuln.get('CVE', 'N/A')
            severity = vuln.get('severity', 'N/A').upper()
            date = vuln.get('public_date', 'N/A')
            impact = vuln.get('impact', 'N/A')[:18]
            
            output.append(f"{cve:<15} {severity:<12} {date:<12} {impact:<20}")
        
        output.append("")
        output.append(f"Total: {len(vulns)} vulnerabilities found")
        output.append("")
        
        return "\n".join(output)
    
    def format_csv(self, vulns: List[Dict]) -> str:
        """Format as CSV"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['CVE', 'severity', 'public_date', 'bugzilla_id', 'impact'])
        writer.writeheader()
        
        for vuln in vulns:
            writer.writerow({
                'CVE': vuln.get('CVE', ''),
                'severity': vuln.get('severity', ''),
                'public_date': vuln.get('public_date', ''),
                'bugzilla_id': vuln.get('bugzilla_id', ''),
                'impact': vuln.get('impact', '')
            })
        
        return output.getvalue()
    
    def format_json(self, vulns: List[Dict], version: str) -> str:
        """Format as JSON"""
        data = {
            "version": version,
            "count": len(vulns),
            "vulnerabilities": vulns,
            "generated": datetime.now().isoformat(),
            "source": "Red Hat Security Advisory API"
        }
        return json.dumps(data, indent=2)
    
    def format_stats(self, vulns: List[Dict], version: str) -> str:
        """Generate statistics summary"""
        output = []
        output.append("")
        output.append("=" * 60)
        output.append(f"OpenShift {version} - Vulnerability Statistics")
        output.append("=" * 60)
        output.append("")
        output.append(f"Total Vulnerabilities: {len(vulns)}\n")
        
        if vulns:
            severity_counts = {}
            for vuln in vulns:
                severity = vuln.get('severity', 'unknown').lower()
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            output.append("By Severity:")
            for severity in ['critical', 'important', 'moderate', 'low']:
                count = severity_counts.get(severity, 0)
                output.append(f"  {severity.upper()}: {count}")
        
        output.append("")
        return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description='OpenShift Vulnerability Scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s 4.21                          # List all vulnerabilities
  %(prog)s 4.12 --severity critical      # List critical vulnerabilities only
  %(prog)s 4.12 --format csv             # Export as CSV
  %(prog)s 4.12 --format json            # Export as JSON
  %(prog)s 4.12 --format stats           # Show statistics
        '''
    )
    
    parser.add_argument('version', help='OpenShift version (e.g., 4.21, 4.12)')
    parser.add_argument(
        '--format', '-f',
        choices=['table', 'csv', 'json', 'stats'],
        default='table',
        help='Output format (default: table)'
    )
    parser.add_argument(
        '--severity', '-s',
        choices=['critical', 'important', 'moderate', 'low'],
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
        print("Use format like: 4.21 or 4.12", file=sys.stderr)
        sys.exit(1)
    
    # Fetch vulnerabilities
    vulns = scanner.fetch_vulnerabilities(args.version)
    
    # Filter and sort
    vulns = scanner.filter_vulnerabilities(vulns, args.severity)
    vulns = scanner.sort_vulnerabilities(vulns)
    
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
    
    if args.format == 'table':
        print(f"[*] Report generation complete", file=sys.stderr)
    
    sys.exit(0)


if __name__ == '__main__':
    main()
