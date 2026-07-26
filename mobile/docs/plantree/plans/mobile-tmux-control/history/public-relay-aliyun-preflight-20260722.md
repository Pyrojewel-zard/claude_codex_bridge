# Public Relay Alibaba Cloud Preflight — 2026-07-22

Status: Blocked before deployment; no remote mutation performed

## Target

- public IPv4: `47.120.71.142`
- private IPv4: `172.26.93.57`
- intended relay name: `relay.seemlab.top`
- existing workload: RustDesk relay plus other network services

## Source Readiness

Both current working source and `main` contain only
`LocalRelayServerHarness`. Its source comment explicitly states that it never
opens a public listener. No production WSS relay, one-time invitation store,
host connector, or Flutter production E2EE transport exists yet.

Therefore the Alibaba Cloud host cannot truthfully be declared a working CCB
Relay until Packages A-D in
[the deployment plan](../topics/public-relay-invitation-and-aliyun-deployment.md)
land and pass local gates.

## External Read-Only Findings

- SSH host keys already exist in the local `known_hosts` file.
- Local historical key `/home/bfly/Download/l3miyao.pem` was offered to
  `root@47.120.71.142` but rejected by the server. The current default Ed25519
  key and other local historical key candidates were also rejected.
- TCP `22`, `80`, `443`, `9993`, and `21114` through `21119` are reachable.
- `80/443` are served by `nginx/1.18.0 (Ubuntu)`.
- Direct HTTPS currently serves the `www.architec.top` virtual host and its
  certificate expired on `2026-06-22`.
- `relay.seemlab.top` had no public A record in the AliDNS DNS-over-HTTPS
  response at preflight time.

No systemd unit, Nginx file, firewall/security-group rule, process, key, DNS
record, or RustDesk service was changed.

## Non-Conflict Deployment Position

After SSH and source readiness are restored:

1. inventory remote `ss`, systemd, Nginx, firewall, disk, users, and RustDesk
   configuration before writing anything;
2. run CCB Relay as a dedicated unprivileged user and bind it only to a newly
   verified free loopback port;
3. add an independent `relay.seemlab.top` Nginx SNI/Host virtual server on
   existing `443` that proxies WSS to that loopback port;
4. leave RustDesk ports `21114-21119`, ZeroTier `9993`, RustDesk units, data,
   keys, and current Nginx virtual hosts untouched;
5. validate Nginx with `nginx -t`, start only the new relay unit, and compare
   RustDesk service/port health before and after;
6. add the DNS A record and obtain a hostname-valid certificate only after the
   isolated loopback service is healthy.

## Blockers

1. Restore SSH access using an authorized public key. Do not replace the
   instance key pair through a stop/start operation while RustDesk availability
   matters; prefer Alibaba Cloud Workbench/Cloud Assistant or console access to
   append a dedicated public key.
2. Implement and review the production Relay Packages A-D. The local harness
   must not be deployed as production.
3. Add `relay.seemlab.top -> 47.120.71.142` after the operator confirms DNS
   authority.
4. Repair or isolate the existing expired `www.architec.top` certificate
   separately; CCB Relay deployment must not silently rewrite that site.

## Next Verification

Once SSH succeeds, capture a remote read-only inventory and choose a free
loopback port. Once production relay code exists, deploy to a staging path and
run the complete
[public Android Emulator acceptance plan](../topics/public-relay-android-emulator-acceptance.md).
