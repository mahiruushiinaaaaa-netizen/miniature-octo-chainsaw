"""
net_ops.py – Network diagnostics and utilities.
Platform-aware: Windows-first with Unix fallbacks.
"""
from __future__ import annotations

import os
import platform
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def net_op(operation: str, target: str, options: str = "") -> dict[str, Any]:
    """Network diagnostics and utilities.

    Operations:
    - ping: ping a host (target: hostname/IP, options: count e.g. '4')
    - dns: DNS lookup (target: hostname)
    - port_check: check if port is open (target: 'host:port')
    - download: download file (target: URL, options: output filename)
    - whois: domain info (target: domain)
    - traceroute: trace network path (target: hostname)
    - local_ip: show local network interfaces
    - port_scan: scan common ports (target: hostname, options: port range e.g. '80-443')
    """
    operation = operation.lower().strip()

    if operation == "ping":
        return _ping(target, options)
    elif operation == "dns":
        return _dns_lookup(target)
    elif operation == "port_check":
        return _port_check(target)
    elif operation == "download":
        return _download(target, options)
    elif operation == "whois":
        return _whois(target)
    elif operation == "traceroute":
        return _traceroute(target)
    elif operation == "local_ip":
        return _local_ip()
    elif operation == "port_scan":
        return _port_scan(target, options)
    else:
        return {"success": False, "error": f"Unknown operation: '{operation}'. Available: ping, dns, port_check, download, whois, traceroute, local_ip, port_scan"}


def _ping(host: str, options: str = "") -> dict[str, Any]:
    """Ping a host."""
    if not host:
        return {"success": False, "error": "Host required. Usage: target='google.com'"}

    count = "4"
    if options.strip().isdigit():
        count = options.strip()

    try:
        if platform.system() == "Windows":
            cmd = ["ping", "-n", count, host]
        else:
            cmd = ["ping", "-c", count, host]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
        if len(output) > 2000:
            output = output[:2000] + "\n...[truncated]"
        return {"success": result.returncode == 0, "result" if result.returncode == 0 else "error": output or "Ping failed (no response)"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Ping to {host} timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _dns_lookup(host: str) -> dict[str, Any]:
    """DNS lookup using socket."""
    if not host:
        return {"success": False, "error": "Hostname required"}

    try:
        results = []
        # Get all address info
        infos = socket.getaddrinfo(host, None)
        seen = set()
        for family, socktype, proto, canonname, sockaddr in infos:
            ip = sockaddr[0]
            if ip not in seen:
                seen.add(ip)
                family_name = "IPv4" if family == socket.AF_INET else "IPv6"
                results.append(f"  {family_name}: {ip}")

        # Reverse lookup
        try:
            hostname, _, _ = socket.gethostbyaddr(list(seen)[0]) if seen else ("", [], [])
            if hostname:
                results.append(f"  Reverse DNS: {hostname}")
        except (socket.herror, socket.gaierror, IndexError):
            pass

        if not results:
            return {"success": False, "error": f"No DNS records found for {host}"}

        return {"success": True, "result": f"DNS lookup for {host}:\n" + "\n".join(results)}
    except socket.gaierror as e:
        return {"success": False, "error": f"DNS lookup failed for {host}: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _port_check(target: str) -> dict[str, Any]:
    """Check if a port is open. Target format: 'host:port'."""
    if ":" not in target:
        return {"success": False, "error": "Format: 'host:port' (e.g. 'localhost:8080')"}

    parts = target.rsplit(":", 1)
    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        return {"success": False, "error": f"Invalid port: '{parts[1]}'"}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            return {"success": True, "result": f"Port {port} on {host} is OPEN"}
        else:
            return {"success": True, "result": f"Port {port} on {host} is CLOSED"}
    except socket.gaierror:
        return {"success": False, "error": f"Cannot resolve host: {host}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _download(url: str, output: str = "") -> dict[str, Any]:
    """Download a file from URL."""
    if not url:
        return {"success": False, "error": "URL required"}

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Determine output filename
    if not output:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        output = Path(parsed.path).name or "download"

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAI/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            # Check size (limit 100MB)
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > 100 * 1024 * 1024:
                return {"success": False, "error": f"File too large: {int(content_length) / 1024 / 1024:.1f}MB (max 100MB)"}

            # Download
            data = response.read()
            output_path.write_bytes(data)

            size_kb = len(data) / 1024
            return {"success": True, "result": f"Downloaded {url}\n  Saved to: {output_path}\n  Size: {size_kb:.1f} KB"}

    except urllib.error.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"success": False, "error": f"Connection error: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _whois(domain: str) -> dict[str, Any]:
    """Domain whois lookup."""
    if not domain:
        return {"success": False, "error": "Domain required"}

    # Try system whois command
    import shutil
    if shutil.which("whois"):
        try:
            result = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=15)
            output = result.stdout.strip()
            if output:
                if len(output) > 3000:
                    output = output[:3000] + "\n...[truncated]"
                return {"success": True, "result": output}
        except Exception:
            pass

    # Fallback: socket-based whois
    try:
        # Determine whois server
        tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
        whois_servers = {"com": "whois.verisign-grs.com", "net": "whois.verisign-grs.com", "org": "whois.pir.org", "io": "whois.nic.io"}
        server = whois_servers.get(tld, f"whois.nic.{tld}")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((server, 43))
        sock.send((domain + "\r\n").encode())

        response = b""
        while True:
            data = sock.recv(4096)
            if not data:
                break
            response += data
        sock.close()

        output = response.decode("utf-8", errors="replace").strip()
        if len(output) > 3000:
            output = output[:3000] + "\n...[truncated]"
        return {"success": True, "result": output or "No whois data found"}
    except Exception as e:
        return {"success": False, "error": f"Whois lookup failed: {e}"}


def _traceroute(host: str) -> dict[str, Any]:
    """Trace network path to host."""
    if not host:
        return {"success": False, "error": "Host required"}

    try:
        if platform.system() == "Windows":
            cmd = ["tracert", "-d", "-h", "15", host]
        else:
            cmd = ["traceroute", "-n", "-m", "15", host]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = (result.stdout + result.stderr).strip()
        if len(output) > 3000:
            output = output[:3000] + "\n...[truncated]"
        return {"success": True, "result": output or "Traceroute completed (no output)"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Traceroute timed out after 60s"}
    except FileNotFoundError:
        return {"success": False, "error": "traceroute/tracert not found on system"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _local_ip() -> dict[str, Any]:
    """Show local network interfaces."""
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        results = [f"Hostname: {hostname}", f"Primary IP: {local_ip}"]

        # Get all IPs
        try:
            all_ips = socket.getaddrinfo(hostname, None)
            seen = set()
            for _, _, _, _, addr in all_ips:
                ip = addr[0]
                if ip not in seen and not ip.startswith("::"):
                    seen.add(ip)
                    results.append(f"  {ip}")
        except Exception:
            pass

        return {"success": True, "result": "\n".join(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _port_scan(host: str, options: str = "") -> dict[str, Any]:
    """Scan common ports on a host."""
    if not host:
        return {"success": False, "error": "Host required"}

    # Parse port range
    if options and "-" in options:
        try:
            start, end = options.split("-")
            ports = list(range(int(start), int(end) + 1))
        except ValueError:
            ports = [21, 22, 25, 53, 80, 110, 143, 443, 993, 995, 3306, 5432, 6379, 8080, 8443]
    else:
        ports = [21, 22, 25, 53, 80, 110, 143, 443, 993, 995, 3306, 5432, 6379, 8080, 8443]

    # Limit scan size
    if len(ports) > 100:
        ports = ports[:100]

    open_ports = []
    for port in ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                service = _get_service_name(port)
                open_ports.append(f"  {port}/tcp  OPEN  {service}")
        except Exception:
            continue

    if open_ports:
        return {"success": True, "result": f"Port scan for {host}:\n" + "\n".join(open_ports)}
    return {"success": True, "result": f"No open ports found on {host} (scanned {len(ports)} ports)"}


def _get_service_name(port: int) -> str:
    """Get common service name for a port."""
    services = {
        21: "FTP", 22: "SSH", 25: "SMTP", 53: "DNS", 80: "HTTP",
        110: "POP3", 143: "IMAP", 443: "HTTPS", 993: "IMAPS", 995: "POP3S",
        3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
        27017: "MongoDB", 5672: "RabbitMQ", 9200: "Elasticsearch",
    }
    return services.get(port, "")
