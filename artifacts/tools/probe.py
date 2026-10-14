#!/usr/bin/env python3
"""Open-loop fixed-rate latency probe for the admission-control pilot.

Sends requests at a fixed rate (open loop: the next request is scheduled at a
fixed time regardless of whether earlier responses have returned), records
scheduling lag, connect time, response time and outcome (ok / timeout / error),
then prints a JSON summary and optionally a raw per-request file.

Usage examples:
  python3 probe.py --mode http  --host 10.10.10.11 --port 80 --path /payload.bin --rate 100 --duration 20
  python3 probe.py --mode redis --host 10.10.10.12 --port 6379 --rate 100 --duration 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time


def pct(values, p):
    if not values:
        return None
    vals = sorted(values)
    k = int(round((p / 100.0) * (len(vals) - 1)))
    return vals[k]


async def http_once(host, port, path, timeout):
    t0 = time.perf_counter()
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    t1 = time.perf_counter()
    req = ("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (path, host)).encode()
    writer.write(req)
    await writer.drain()
    data = b""
    while True:
        chunk = await asyncio.wait_for(reader.read(65536), timeout)
        if not chunk:
            break
        data += chunk
        if len(data) > 1_000_000:
            break
    t2 = time.perf_counter()
    writer.close()
    ok = data.startswith(b"HTTP/1.1 200") or data.startswith(b"HTTP/1.0 200")
    return (t1 - t0) * 1000.0, (t2 - t0) * 1000.0, ok


async def redis_once(host, port, timeout):
    t0 = time.perf_counter()
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    t1 = time.perf_counter()
    writer.write(b"PING\r\n")
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout)
    t2 = time.perf_counter()
    writer.close()
    return (t1 - t0) * 1000.0, (t2 - t0) * 1000.0, line.strip() == b"+PONG"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["http", "redis"], default="http")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--path", default="/payload.bin")
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--raw")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    if args.port == 0:
        args.port = 80 if args.mode == "http" else 6379

    interval = 1.0 / args.rate
    start = time.perf_counter()
    deadline = start + args.duration
    records = []
    tasks = set()
    sent = 0
    next_t = start

    async def one(planned):
        actual = time.perf_counter()
        lag_ms = (actual - planned) * 1000.0
        try:
            if args.mode == "http":
                connect_ms, total_ms, ok = await http_once(args.host, args.port, args.path, args.timeout)
            else:
                connect_ms, total_ms, ok = await redis_once(args.host, args.port, args.timeout)
            records.append((planned, lag_ms, connect_ms, total_ms, "ok" if ok else "bad"))
        except asyncio.TimeoutError:
            records.append((planned, lag_ms, None, args.timeout * 1000.0, "timeout"))
        except Exception as exc:  # noqa: BLE001
            records.append((planned, lag_ms, None, None, type(exc).__name__))

    while time.perf_counter() < deadline:
        now = time.perf_counter()
        if now < next_t:
            await asyncio.sleep(min(next_t - now, 0.05))
            continue
        task = asyncio.create_task(one(next_t))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        sent += 1
        next_t += interval
        if len(tasks) > 5000:
            for pending in list(tasks):
                pending.cancel()
            break

    if tasks:
        await asyncio.wait(tasks, timeout=args.timeout + 1.0)

    lag_vals = []
    lat_ok = []
    connect_ok = []
    timeouts = 0
    errors = {}
    for _planned, lag_ms, connect_ms, total_ms, outcome in records:
        lag_vals.append(lag_ms)
        if outcome == "ok":
            lat_ok.append(total_ms)
            if connect_ms is not None:
                connect_ok.append(connect_ms)
        elif outcome == "timeout":
            timeouts += 1
        else:
            errors[outcome] = errors.get(outcome, 0) + 1

    out = {
        "tag": args.tag,
        "mode": args.mode,
        "target": "%s:%d" % (args.host, args.port),
        "rate_per_s": args.rate,
        "duration_s": args.duration,
        "planned": sent,
        "completed_ok": len(lat_ok),
        "timeouts": timeouts,
        "errors": errors,
        "schedule_lag_p99_ms": round(pct(lag_vals, 99), 3) if lag_vals else None,
        "p50_ms": round(pct(lat_ok, 50), 3) if lat_ok else None,
        "p90_ms": round(pct(lat_ok, 90), 3) if lat_ok else None,
        "p99_ms": round(pct(lat_ok, 99), 3) if lat_ok else None,
        "p999_ms": round(pct(lat_ok, 99.9), 3) if lat_ok else None,
        "max_ms": round(max(lat_ok), 3) if lat_ok else None,
        "connect_p99_ms": round(pct(connect_ok, 99), 3) if connect_ok else None,
    }
    print(json.dumps(out))

    if args.raw:
        with open(args.raw, "w") as fh:
            fh.write("planned_offset_s,lag_ms,connect_ms,total_ms,status\n")
            for planned, lag_ms, connect_ms, total_ms, outcome in sorted(records):
                fh.write("%.6f,%.3f,%s,%s,%s\n" % (
                    planned - start,
                    lag_ms,
                    "" if connect_ms is None else "%.3f" % connect_ms,
                    "" if total_ms is None else "%.3f" % total_ms,
                    outcome,
                ))


if __name__ == "__main__":
    asyncio.run(main())
