# Deployment Environment — Berton Vineyards Bottling App

Context for coding agents. This documents the VM that hosts the containerised
application, how it is reached, and the environment constraints that affect how
the Docker Compose stack must be configured. Managed by .nxt IT (Andrew Mott / Mark).

Last verified: 2026-07-13 (tablet test network added).

---

## 1. Access path (how a human reaches the host)

The Azure Linux VM is **not** directly reachable. The only network route that
currently exists into the Azure network terminates at the ServerVLAN, where a
Windows RDS host lives. That Windows host acts as the jump box.

```
Local workstation
  └─ RDP → RDSH01 (Windows, behind RDS Gateway + Duo MFA)
       └─ SSH → BV-AZ-DockerHost01 (10.0.0.4)  ← the Docker host
```

Two-stage auth on RDP:
1. **RDS Gateway** — Duo Push to phone. **No UI** — the client appears to hang
   on "connecting…" while it waits for the push to be approved. This is normal.
2. **Desktop login** — standard Windows prompt, MFA-backed account credentials.

From RDSH01, SSH to the Docker host uses a saved SSH config + key staged under
the user profile on RDSH01. Target: `azureuser@10.0.0.4`.

> Note: the SSH private key currently lives only on RDSH01, so RDSH01 is at
> present the sole path in. Getting the key onto the developer workstation (and
> opening a direct route) is a pending follow-up with .nxt IT — not required for
> deployment testing.

---

## 2. Host facts

| Property        | Value                                   |
| --------------- | --------------------------------------- |
| Hostname        | `BV-AZ-DockerHost01`                     |
| Internal IP     | `10.0.0.4` (Azure ServerVLAN)            |
| Login user      | `azureuser`                              |
| OS              | Ubuntu (Azure-hosted)                    |
| Docker          | `29.3.1` (Canonical **snap** package)    |
| Docker Compose  | `v5.1.1` (`docker compose`, plugin form) |

Compose is the v2 plugin syntax: `docker compose ...` (space), **not**
`docker-compose` (hyphen).

---

## 3. Network topology (reference)

The Docker host sits on the Azure side of a site-to-site tunnel back to the
on-prem Yenda site. Application code does not need to care about this chain —
`10.0.0.4` is reachable from RDSH01 and that's the operational surface — but it's
recorded here in case a service needs to reach an on-prem VLAN later.

```
BV-AZ-DockerHost01 (10.0.0.4)
  ↓ Azure Route Table
BV-AZ-pfSense (10.0.254.4)   [BV-AZ-pfSense.australiaeast.cloudapp.azure.com]
  ↓ WireGuard Tunnel
10.111.1.1 (Azure) ↕ 10.111.1.2 (Yenda)
  ↓
pfSense.ad.bertonvineyards.com.au
  ↓ VLAN Routing
Destination Network
```

On-prem VLANs (only ServerVLAN → Azure is open today; others opened on request):

| VLAN | Name            | VLAN | Name            |
| ---- | --------------- | ---- | --------------- |
| 100  | VoiceLAN        | 700  | BVPrintLAN      |
| 200  | BVEndpointLAN   | 800  | BVGuest         |
| 300  | BVServerLAN     | 900  | ITManagementLAN |
| 400  | BVInfraLAN      | 1000 | BVNASLAN        |
| 500  | VinWizardLAN    | 1100 | BVJasonLAN      |
| 600  | I2R/PLC         |      |                 |
| 601  | AutomationLAN   |      |                 |

> Relevant later: **BVPrintLAN (700)** is where the pallet-tag / label printer
> will live, and this route is **not yet open** to the Azure network. Any
> print-path integration will require .nxt IT to open ServerVLAN→PrintLAN (or a
> print relay). Do not assume printer reachability from the container today.

---

## 4. Tablet test network (for on-floor device testing)

.nxt IT (Mark) has stood up a dedicated Wi-Fi network for testing the Samsung
Galaxy Tab A9+ tablets against the app.

| Property          | Value                                          |
| ----------------- | ---------------------------------------------- |
| SSID              | `BV-Infra`                                      |
| PSK               | Held in Hudu (secure share); not stored here    |
| Tablet subnet     | `10.110.77.0/24`                                |
| Gateway (on-prem) | `pfSense.ad.bertonvineyards.com.au` = `10.110.77.1` |

A route exists from `10.110.77.0/24` → **BV-AZ-DockerHost01 (10.0.0.4)**. .nxt IT
has verified the host side (10.0.0.4 → 10.110.77.1 reachable). This means a
tablet on `BV-Infra` can reach the Docker host directly, so once the app is
listening on a host port, tablets hit it at `http://10.0.0.4:PORT`.

> This is the intended access path for device testing — distinct from the
> RDSH01 SSH path, which is for host administration only. Tablets do **not** go
> through RDSH01.

Connectivity test (from a tablet on BV-Infra): reach `10.0.0.4` — e.g. browser
to `http://10.0.0.4` (or the app port once running), or ping from a terminal
app. Confirms the route Mark configured is live before app deployment.

---

## 5. Docker permissions

Fresh host: `azureuser` was **not** in the `docker` group initially, so
`docker ps` returned:

```
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

Resolved with:

```bash
sudo usermod -aG docker $USER
newgrp docker      # or reconnect the SSH session for group membership to apply
docker ps          # now works without sudo
```

**Gotcha:** `usermod` does **not** apply the group to an already-open shell. If
`docker ps` / `docker pull` still returns the socket permission error after the
`usermod`, the current session predates the change. Check with `id` (look for
`docker` in the group list); if absent, run `newgrp docker` or reconnect SSH.

To test the daemon / host independently of user group membership, use `sudo`
(the daemon runs as root regardless): `sudo docker ps`, `sudo docker pull hello-world`.
The daemon is confirmed healthy.

---

## 6. Constraints that affect Compose configuration

**Docker is snap-confined (Canonical package).** This is the single most
important thing to design around. The snap build restricts Docker's filesystem
access outside the user's home directory. Consequences:

- **Keep the project directory and all bind-mounted volumes under
  `/home/azureuser/`.** Bind mounts pointing at `/opt`, `/srv`, `/etc`, or other
  paths outside home may fail with access errors that a normal apt install would
  not throw. Prefer named volumes or home-relative paths.
- Recommended project root: `/home/azureuser/bottling-app/` (adjust to taste,
  but stay under home).

**Deployment-readiness checklist for the stack** (FastAPI + async SQLAlchemy +
Alembic + PostgreSQL + Jinja2/JSON API + WeasyPrint + pypdf/pikepdf):

- Compose file should live at the project root under `/home/azureuser/`.
- Postgres data volume: use a **named volume** (e.g. `pgdata:`) rather than a
  host bind mount to sidestep snap confinement entirely.
- Any host bind mounts (uploaded PDFs, generated output, config) must resolve
  under `/home/azureuser/...`.
- WeasyPrint needs its native deps (Pango, Cairo, GDK-PixBuf, fonts) **inside**
  the app image — confirm the Dockerfile installs them; the host being snap
  Docker doesn't help or hurt here, but a slim base image will miss them.
- Alembic migrations should run as an explicit step (entrypoint script or a
  one-shot `migrate` service that runs `alembic upgrade head` before the web
  service accepts traffic), not implicitly at import time.
- Expose the app on a host port. Verify locally on the VM first
  (`curl http://localhost:PORT/health`), then from a tablet on the `BV-Infra`
  network at `http://10.0.0.4:PORT` — that route is now live (see §4), so tablet
  access no longer needs a further VLAN route opened.
- **Bind to `0.0.0.0`, not `127.0.0.1`.** Publish the container port to the host
  (Compose `ports:`) so tablets on 10.110.77.0/24 can reach it — a loopback-only
  bind will pass the local curl test but be unreachable from the tablet.
- Printer/label path (BVPrintLAN) is **out of scope for this deployment test** —
  route not yet open. MVP already excludes it; keep it stubbed/manual.

---

## 7. Open items

- [x] Tablet test network (`BV-Infra`, 10.110.77.0/24) provisioned with route to
      10.0.0.4 — done by .nxt IT. **Pending:** confirm from a tablet end-to-end.
- [x] `azureuser` added to `docker` group. **Pending:** confirm with .nxt IT
      they're comfortable with it (docker group is root-equivalent on the host).
- [ ] Confirm outbound internet from the Docker host (needed to `docker pull`
      base images / build) — verify before first deploy via `sudo docker pull
      hello-world`.
- [ ] SSH private key onto developer workstation + direct route (remove hard
      dependency on RDSH01 as sole entry) — not urgent.
- [ ] VLAN routes still to open as needed: PrintLAN (700) for label printer;
      others per integration needs.
