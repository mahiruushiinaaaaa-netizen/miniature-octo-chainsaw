"""
devops_tools.py – DevOps, deployment, and infrastructure tools.

Covers: service management, port scanning, SSL checks, DNS lookup,
cron/scheduled tasks, log analysis, and deployment helpers.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def port_check(host: str = "localhost", port: int = 0, scan_range: str = "") -> dict[str, Any]:
    """Check if a port is open or scan a range of ports.
    
    - Single port: port_check(host="localhost", port=8080)
    - Range scan: port_check(host="localhost", scan_range="8000-8100")
    """
    if scan_range:
        try:
            start, end = map(int, scan_range.split("-"))
            open_ports = []
            for p in range(start, min(end + 1, start + 200)):
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.3)
                        if s.connect_ex((host, p)) == 0:
                            open_ports.append(p)
                except Exception:
                    pass
            return {"success": True, "result": f"Open ports on {host} ({scan_range}): {open_ports or 'none'}"}
        except ValueError:
            return {"success": False, "error": "Invalid range format. Use: start-end (e.g. 8000-8100)"}
    
    if not port:
        return {"success": False, "error": "Specify port number or scan_range"}
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            result = s.connect_ex((host, port))
            if result == 0:
                return {"success": True, "result": f"Port {port} on {host} is OPEN"}
            else:
                return {"success": True, "result": f"Port {port} on {host} is CLOSED"}
    except socket.gaierror:
        return {"success": False, "error": f"Cannot resolve host: {host}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def dns_lookup(domain: str, record_type: str = "A") -> dict[str, Any]:
    """Perform DNS lookup for a domain."""
    try:
        if record_type.upper() == "A":
            results = socket.getaddrinfo(domain, None, socket.AF_INET)
            ips = list(set(r[4][0] for r in results))
            return {"success": True, "result": f"DNS A records for {domain}: {', '.join(ips)}"}
        elif record_type.upper() == "AAAA":
            results = socket.getaddrinfo(domain, None, socket.AF_INET6)
            ips = list(set(r[4][0] for r in results))
            return {"success": True, "result": f"DNS AAAA records for {domain}: {', '.join(ips)}"}
        else:
            # Use nslookup for other types
            result = subprocess.run(
                ["nslookup", "-type=" + record_type, domain],
                capture_output=True, text=True, timeout=10
            )
            return {"success": True, "result": result.stdout.strip()}
    except socket.gaierror as e:
        return {"success": False, "error": f"DNS lookup failed: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ssl_check(host: str, port: int = 443) -> dict[str, Any]:
    """Check SSL certificate details for a host."""
    import ssl as ssl_mod
    try:
        ctx = ssl_mod.create_default_context()
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                subject = dict(x[0] for x in cert.get("subject", []))
                issuer = dict(x[0] for x in cert.get("issuer", []))
                not_after = cert.get("notAfter", "unknown")
                not_before = cert.get("notBefore", "unknown")
                san = cert.get("subjectAltName", [])
                
                lines = [
                    f"SSL Certificate for {host}:{port}",
                    f"  Subject: {subject.get('commonName', 'N/A')}",
                    f"  Issuer: {issuer.get('organizationName', 'N/A')}",
                    f"  Valid from: {not_before}",
                    f"  Valid until: {not_after}",
                    f"  SANs: {', '.join(s[1] for s in san[:10])}",
                    f"  Protocol: {ssock.version()}",
                ]
                return {"success": True, "result": "\n".join(lines)}
    except ssl_mod.SSLCertVerificationError as e:
        return {"success": False, "error": f"SSL verification failed: {e}"}
    except Exception as e:
        return {"success": False, "error": f"SSL check failed: {e}"}


def service_manage(operation: str, service: str = "") -> dict[str, Any]:
    """Manage system services (Windows services or systemctl).
    
    Operations: list, status, start, stop, restart
    """
    op = operation.lower().strip()
    
    if os.name == "nt":
        # Windows services
        if op == "list":
            try:
                r = subprocess.run(["sc", "query", "type=", "service", "state=", "all"],
                                   capture_output=True, text=True, timeout=10)
                # Parse into readable format
                services = []
                current = {}
                for line in r.stdout.split("\n"):
                    if "SERVICE_NAME:" in line:
                        if current:
                            services.append(current)
                        current = {"name": line.split(":", 1)[1].strip()}
                    elif "STATE" in line and ":" in line:
                        current["state"] = line.split(":", 1)[1].strip()
                if current:
                    services.append(current)
                output = "\n".join(f"{s['name']}: {s.get('state', 'unknown')}" for s in services[:50])
                return {"success": True, "result": output or "No services found"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        elif op == "status":
            if not service:
                return {"success": False, "error": "Service name required"}
            try:
                r = subprocess.run(["sc", "query", service], capture_output=True, text=True, timeout=10)
                return {"success": r.returncode == 0, "result": r.stdout.strip() if r.returncode == 0 else r.stderr.strip()}
            except Exception as e:
                return {"success": False, "error": str(e)}
        elif op in ("start", "stop"):
            if not service:
                return {"success": False, "error": "Service name required"}
            try:
                r = subprocess.run(["sc", op, service], capture_output=True, text=True, timeout=15)
                return {"success": r.returncode == 0, "result": r.stdout.strip() or "Done"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        elif op == "restart":
            if not service:
                return {"success": False, "error": "Service name required"}
            subprocess.run(["sc", "stop", service], capture_output=True, timeout=10)
            time.sleep(1)
            r = subprocess.run(["sc", "start", service], capture_output=True, text=True, timeout=15)
            return {"success": r.returncode == 0, "result": r.stdout.strip() or "Restarted"}
    else:
        # Linux systemctl
        if op == "list":
            r = subprocess.run(["systemctl", "list-units", "--type=service", "--no-pager"],
                               capture_output=True, text=True, timeout=10)
            return {"success": True, "result": r.stdout[:3000]}
        elif op == "status":
            r = subprocess.run(["systemctl", "status", service, "--no-pager"],
                               capture_output=True, text=True, timeout=10)
            return {"success": True, "result": r.stdout[:2000]}
        elif op in ("start", "stop", "restart"):
            r = subprocess.run(["sudo", "systemctl", op, service],
                               capture_output=True, text=True, timeout=15)
            return {"success": r.returncode == 0, "result": r.stdout.strip() or "Done"}
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def log_analyze(path: str, lines: int = 50, pattern: str = "", level: str = "") -> dict[str, Any]:
    """Analyze log files - tail, filter by pattern or level.
    
    - level: 'error', 'warn', 'info', 'debug'
    - pattern: regex to filter lines
    """
    file_path = Path(path)
    if not file_path.exists():
        return {"success": False, "error": f"Log file not found: {path}"}
    
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        all_lines = content.splitlines()
        
        # Filter by level
        if level:
            level_upper = level.upper()
            all_lines = [l for l in all_lines if level_upper in l.upper()]
        
        # Filter by pattern
        if pattern:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                all_lines = [l for l in all_lines if regex.search(l)]
            except re.error as e:
                return {"success": False, "error": f"Invalid regex: {e}"}
        
        # Take last N lines
        result_lines = all_lines[-lines:]
        
        output = f"Log: {path} ({len(all_lines)} matching lines, showing last {len(result_lines)})\n"
        output += "\n".join(result_lines)
        
        if len(output) > 5000:
            output = output[:5000] + "\n...[truncated]"
        
        return {"success": True, "result": output}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cron_manage(operation: str, schedule: str = "", command: str = "", job_id: str = "") -> dict[str, Any]:
    """Manage scheduled tasks (Windows Task Scheduler / Linux cron).
    
    Operations: list, add, remove
    """
    op = operation.lower().strip()
    
    if os.name == "nt":
        if op == "list":
            try:
                r = subprocess.run(["schtasks", "/query", "/fo", "TABLE", "/nh"],
                                   capture_output=True, text=True, timeout=10)
                output = r.stdout.strip()[:3000] if r.returncode == 0 else r.stderr.strip()
                return {"success": r.returncode == 0, "result": output}
            except Exception as e:
                return {"success": False, "error": str(e)}
        elif op == "add":
            if not schedule or not command or not job_id:
                return {"success": False, "error": "Need schedule, command, and job_id"}
            try:
                r = subprocess.run(
                    ["schtasks", "/create", "/tn", job_id, "/tr", command, "/sc", schedule, "/f"],
                    capture_output=True, text=True, timeout=10
                )
                return {"success": r.returncode == 0, "result": r.stdout.strip() or "Task created"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        elif op == "remove":
            if not job_id:
                return {"success": False, "error": "job_id required"}
            try:
                r = subprocess.run(["schtasks", "/delete", "/tn", job_id, "/f"],
                                   capture_output=True, text=True, timeout=10)
                return {"success": r.returncode == 0, "result": r.stdout.strip() or "Task removed"}
            except Exception as e:
                return {"success": False, "error": str(e)}
    else:
        if op == "list":
            r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            return {"success": True, "result": r.stdout.strip() or "No cron jobs"}
        elif op == "add":
            if not schedule or not command:
                return {"success": False, "error": "Need schedule and command"}
            # Append to crontab
            existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
            new_cron = existing.strip() + f"\n{schedule} {command}\n"
            r = subprocess.run(["crontab", "-"], input=new_cron, capture_output=True, text=True, timeout=5)
            return {"success": r.returncode == 0, "result": "Cron job added"}
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def network_info(query: str = "all") -> dict[str, Any]:
    """Get network information: interfaces, connections, routing table."""
    q = query.lower().strip()
    
    try:
        if os.name == "nt":
            if q in ("all", "interfaces"):
                r = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, timeout=10)
                output = r.stdout[:3000]
            elif q == "connections":
                r = subprocess.run(["netstat", "-an"], capture_output=True, text=True, timeout=10)
                output = r.stdout[:3000]
            elif q == "routes":
                r = subprocess.run(["route", "print"], capture_output=True, text=True, timeout=10)
                output = r.stdout[:3000]
            elif q == "dns":
                r = subprocess.run(["ipconfig", "/displaydns"], capture_output=True, text=True, timeout=10)
                output = r.stdout[:3000]
            else:
                output = "Unknown query. Use: all, interfaces, connections, routes, dns"
        else:
            if q in ("all", "interfaces"):
                r = subprocess.run(["ip", "addr"], capture_output=True, text=True, timeout=10)
                output = r.stdout[:3000]
            elif q == "connections":
                r = subprocess.run(["ss", "-tuln"], capture_output=True, text=True, timeout=10)
                output = r.stdout[:3000]
            elif q == "routes":
                r = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=10)
                output = r.stdout[:3000]
            else:
                output = "Unknown query. Use: all, interfaces, connections, routes"
        
        return {"success": True, "result": output}
    except Exception as e:
        return {"success": False, "error": str(e)}
