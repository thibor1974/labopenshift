#!/usr/bin/env python3

"""
List all OpenShift releases available for a stream (e.g. 4.21), and the
update channels (candidate / fast / stable / eus) each release is in.
Uses the OpenShift update graph API (Cincinnati), the same source as `oc adm upgrade`.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from typing import Dict, List

GRAPH_API = "https://api.openshift.com/api/upgrades_info/v1/graph"
CHANNELS = ['candidate', 'fast', 'stable', 'eus']


class FetchError(Exception):
    """Raised when the update graph API cannot be reached or returns invalid data"""


def fetch_json(url: str, attempts: int = 3) -> Dict:
    """Fetch JSON with curl, retrying on failure"""
    cmd = ['curl', '-sS', '-f', '--connect-timeout', '10', '--max-time', '30',
           '-H', 'Accept: application/json', url]
    error = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as e:
                raise FetchError(f"{url}: invalid JSON response: {e}")
        error = result.stderr.strip()
    raise FetchError(f"{url}: {error}")


def version_key(version: str):
    """Sort 4.21.0-ec.1 < 4.21.0-rc.1 < 4.21.0 < 4.21.10"""
    match = re.match(r'(\d+)\.(\d+)\.(\d+)(?:-(\w+)\.(\d+))?', version)
    if not match:
        return (0, 0, 0, 0, '', 0)
    major, minor, patch, pre, pre_num = match.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or '', int(pre_num or 0))


def list_versions(stream: str, arch: str, channels: List[str]) -> Dict[str, Dict]:
    """Return {version: {'channels': [...], 'url': errata url}} for releases of the stream"""
    versions = {}
    for channel in channels:
        graph = fetch_json(f"{GRAPH_API}?channel={channel}-{stream}&arch={arch}")
        for node in graph.get('nodes', []):
            version = node['version']
            # A channel also lists older-stream releases you can update from; keep only this stream
            if not version.startswith(stream + '.'):
                continue
            entry = versions.setdefault(version, {'channels': [], 'url': node.get('metadata', {}).get('url', '')})
            entry['channels'].append(channel)
    return dict(sorted(versions.items(), key=lambda item: version_key(item[0])))


def format_table(versions: Dict[str, Dict], stream: str, arch: str, channels: List[str]) -> str:
    lines = [f"OpenShift {stream} releases ({arch}): {len(versions)}", "=" * 80]
    lines.append(f"  {'Version':<16}" + "".join(f"{c:<11}" for c in channels) + "Errata")
    lines.append("-" * 80)
    for version, entry in versions.items():
        marks = "".join(f"{'✓' if c in entry['channels'] else '-':<11}" for c in channels)
        lines.append(f"  {version:<16}{marks}{entry['url']}")
    lines.append("-" * 80)
    for channel in channels:
        latest = [v for v, e in versions.items() if channel in e['channels']]
        lines.append(f"  Latest in {channel + '-' + stream:<16} {latest[-1] if latest else '(none)'}")
    return "\n".join(lines)


def format_csv(versions: Dict[str, Dict], channels: List[str]) -> str:
    lines = ["version," + ",".join(channels) + ",errata"]
    for version, entry in versions.items():
        flags = ",".join('yes' if c in entry['channels'] else 'no' for c in channels)
        lines.append(f"{version},{flags},{entry['url']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="List all OpenShift releases available for a stream, per update channel",
        epilog="Examples:\n"
               "  %(prog)s 4.21\n"
               "  %(prog)s 4.21 --channel stable\n"
               "  %(prog)s 4.20 --format csv > 4.20.csv\n"
               "  %(prog)s 4.21 --arch arm64 --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('stream', help="OpenShift stream, e.g. 4.21")
    parser.add_argument('--channel', '-c', choices=CHANNELS, action='append',
                        help="Only query this channel (repeatable). Default: all channels")
    parser.add_argument('--arch', '-a', default='amd64', choices=['amd64', 'arm64', 'ppc64le', 's390x', 'multi'],
                        help="Architecture (default: amd64)")
    parser.add_argument('--format', '-f', default='table', choices=['table', 'csv', 'json', 'list'],
                        help="Output format (default: table); 'list' prints one version per line")
    args = parser.parse_args()

    if not re.fullmatch(r'\d+\.\d+', args.stream):
        parser.error(f"invalid stream '{args.stream}', expected e.g. 4.21")
    channels = args.channel or CHANNELS

    try:
        versions = list_versions(args.stream, args.arch, channels)
    except FetchError as e:
        print(f"Error: cannot query the update graph API: {e}", file=sys.stderr)
        sys.exit(2)

    if not versions:
        print(f"No releases found for {args.stream} in channels: {', '.join(channels)}", file=sys.stderr)
        sys.exit(1)

    if args.format == 'json':
        print(json.dumps({'stream': args.stream, 'arch': args.arch, 'versions': versions}, indent=2))
    elif args.format == 'csv':
        print(format_csv(versions, channels))
    elif args.format == 'list':
        print("\n".join(versions))
    else:
        print(format_table(versions, args.stream, args.arch, channels))


if __name__ == '__main__':
    main()
