import dns.resolver
import socket
import time
import statistics
import concurrent.futures
import os

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich import box

SERVERS = [
    "london", "amsterdam", "paris", "frankfurt", "madrid",
    "istanbul", "bangalore", "hongkong", "singapore", "seoul", "tokyo",
]

RTMP_PORT   = 1935
PROBE_COUNT = 10
UPLOAD_SIZE = 4 * 1024 * 1024

console = Console()


def resolve(prefix, domain="restream.io"):
    fqdn = f"{prefix}.{domain}"
    try:
        return fqdn, str(dns.resolver.resolve(fqdn, 'A')[0])
    except:
        return fqdn, None


def measure_latency(ip):
    latencies, lost = [], 0
    for _ in range(PROBE_COUNT):
        try:
            start = time.perf_counter()
            sock  = socket.create_connection((ip, RTMP_PORT), timeout=3)
            latencies.append((time.perf_counter() - start) * 1000)
            sock.close()
        except:
            lost += 1
        time.sleep(0.05)
    if not latencies:
        return None
    return {
        "lat_avg":     round(statistics.mean(latencies), 1),
        "jitter":      round(statistics.stdev(latencies), 1) if len(latencies) > 1 else 0.0,
        "packet_loss": round((lost / PROBE_COUNT) * 100),
    }


def measure_upload(ip):
    try:
        sock  = socket.create_connection((ip, RTMP_PORT), timeout=10)
        chunk = os.urandom(65536)
        sent, start = 0, time.perf_counter()
        while sent < UPLOAD_SIZE:
            n = sock.send(chunk)
            if not n: break
            sent += n
        elapsed = time.perf_counter() - start
        sock.close()
        return round((sent * 8) / elapsed / 1_000_000, 1) if elapsed and sent else None
    except:
        return None


def score(r):
    return r["lat_avg"] + r["jitter"] * 2 + r["packet_loss"] * 10 - (r["upload_mbps"] or 0) * 0.5


def test_server(prefix, progress, task):
    fqdn, ip = resolve(prefix)
    progress.advance(task)
    if not ip:
        return None
    metrics = measure_latency(ip)
    if not metrics:
        return {"name": prefix.capitalize(), "ok": False}
    return {"name": prefix.capitalize(), "ok": True, "upload_mbps": measure_upload(ip), **metrics}


def main():
    results = []
    with Progress(
        SpinnerColumn(), 
        TextColumn("  [cyan]Recherche du meilleur serveur...[/cyan]"), 
        BarColumn(bar_width=20),
        console=console, 
        transient=True
    ) as progress:
        task = progress.add_task("", total=len(SERVERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(SERVERS)) as executor:
            for future in concurrent.futures.as_completed(
                {executor.submit(test_server, s, progress, task): s for s in SERVERS}
            ):
                r = future.result()
                if r: results.append(r)

    reachable = sorted([r for r in results if r["ok"]], key=score)

    if reachable:
        best = reachable[0]
        console.print(f"✅ [bold green]Test terminé ![/bold green]")
        console.print(f"👉 Le meilleur serveur pour vous est : [bold magenta]{best['name']}[/bold magenta]")
        
        if len(reachable) > 1:
            autres = ", ".join(r['name'] for r in reachable[1:4])
            console.print(f"   [dim](Alternatives acceptables : {autres})[/dim]")
    else:
        console.print("❌ [bold red]Connexion impossible. Vérifiez internet.[/bold red]")

if __name__ == "__main__":
    main()