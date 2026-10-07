#!/usr/bin/env python3

"""
List all OpenShift releases available for a stream (e.g. 4.21), and the
update channels (candidate / fast / stable / eus) each release is in.
Uses the OpenShift update graph API (Cincinnati), the same source as `oc adm upgrade`.
Release dates come from the errata "Issued" date; pre-releases (ec/rc) have no errata,
so their build date from the mirror's release.txt is shown instead (marked with *).
"""

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

GRAPH_API = "https://api.openshift.com/api/upgrades_info/v1/graph"
MIRROR_BASE = "https://mirror.openshift.com/pub/openshift-v4"
CHANNELS = ['candidate', 'fast', 'stable', 'eus']
MIRROR_ARCH = {'amd64': 'x86_64', 'arm64': 'aarch64', 'ppc64le': 'ppc64le', 's390x': 's390x', 'multi': 'multi'}


class FetchError(Exception):
    """Raised when the update graph API cannot be reached or returns invalid data"""


def fetch_text(url: str, attempts: int = 3, accept: Optional[str] = None) -> str:
    """Fetch a URL with curl, retrying on failure"""
    cmd = ['curl', '-sS', '-f', '-L', '--connect-timeout', '10', '--max-time', '30']
    if accept:
        cmd += ['-H', f'Accept: {accept}']
    error = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        result = subprocess.run(cmd + [url], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        error = result.stderr.strip()
        if 'error: 404' in error:  # not transient, don't retry
            break
    raise FetchError(f"{url}: {error}")


def fetch_json(url: str) -> Dict:
    text = fetch_text(url, accept='application/json')
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise FetchError(f"{url}: invalid JSON response: {e}")


def release_date(version: str, errata_url: str, arch: str) -> str:
    """Errata issued date (YYYY-MM-DD) for GA releases; build date + '*' for pre-releases.
    Returns '' when no date can be found."""
    if '-' not in version and errata_url:
        try:
            match = re.search(r'<dt>Issued:</dt>\s*<dd>([\d-]+)</dd>', fetch_text(errata_url))
            if match:
                return match.group(1)
        except FetchError:
            pass
    # Pre-release (its errata link is a placeholder shared by all RCs) or errata page unavailable
    try:
        release_txt = fetch_text(f"{MIRROR_BASE}/{MIRROR_ARCH[arch]}/clients/ocp/{version}/release.txt", attempts=1)
        match = re.search(r'^Created:\s*(\d{4}-\d{2}-\d{2})', release_txt, re.MULTILINE)
        if match:
            return match.group(1) + '*'
    except FetchError:
        pass
    return ''


def add_dates(versions: Dict[str, Dict], arch: str, workers: int = 8):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        dates = pool.map(lambda item: release_date(item[0], item[1]['url'], arch), versions.items())
        for entry, date in zip(versions.values(), dates):
            entry['date'] = date


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
    with_dates = any('date' in e for e in versions.values())
    width = 100 if with_dates else 88
    date_header = f"{'Released':<13}" if with_dates else ""
    lines = [f"OpenShift {stream} releases ({arch}): {len(versions)}", "=" * width]
    lines.append(f"  {'Version':<16}{date_header}" + "".join(f"{c:<11}" for c in channels) + "Errata")
    lines.append("-" * width)
    for version, entry in versions.items():
        date = f"{entry.get('date') or '-':<13}" if with_dates else ""
        marks = "".join(f"{'✓' if c in entry['channels'] else '-':<11}" for c in channels)
        lines.append(f"  {version:<16}{date}{marks}{entry['url']}")
    lines.append("-" * width)
    for channel in channels:
        latest = [v for v, e in versions.items() if channel in e['channels']]
        released = f"  (released {versions[latest[-1]]['date']})" if latest and versions[latest[-1]].get('date') else ""
        lines.append(f"  Latest in {channel + '-' + stream:<16} {latest[-1] if latest else '(none)'}{released}")
    if any(e.get('date', '').endswith('*') for e in versions.values()):
        lines.append("\n  * pre-release: build date (no errata)")
    return "\n".join(lines)


def format_csv(versions: Dict[str, Dict], channels: List[str]) -> str:
    with_dates = any('date' in e for e in versions.values())
    lines = ["version," + ("release_date," if with_dates else "") + ",".join(channels) + ",errata"]
    for version, entry in versions.items():
        date = f"{entry.get('date', '')}," if with_dates else ""
        flags = ",".join('yes' if c in entry['channels'] else 'no' for c in channels)
        lines.append(f"{version},{date}{flags},{entry['url']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="List all OpenShift releases available for a stream, per update channel",
        epilog="Examples:\n"
               "  %(prog)s 4.21\n"
               "  %(prog)s 4.21 --channel stable\n"
               "  %(prog)s 4.20 --format csv > 4.20.csv\n"
               "  %(prog)s 4.21 --arch arm64 --format json\n"
               "  %(prog)s 4.21 --no-dates          # faster: skip the release date lookups",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('stream', help="OpenShift stream, e.g. 4.21")
    parser.add_argument('--channel', '-c', choices=CHANNELS, action='append',
                        help="Only query this channel (repeatable). Default: all channels")
    parser.add_argument('--arch', '-a', default='amd64', choices=['amd64', 'arm64', 'ppc64le', 's390x', 'multi'],
                        help="Architecture (default: amd64)")
    parser.add_argument('--format', '-f', default='table', choices=['table', 'csv', 'json', 'list'],
                        help="Output format (default: table); 'list' prints one version per line")
    parser.add_argument('--no-dates', action='store_true',
                        help="Don't look up release dates (one request per release)")
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

    if not args.no_dates and args.format != 'list':
        add_dates(versions, args.arch)

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
