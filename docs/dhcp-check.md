# Onsite DHCP quick check

**English** · [简体中文](dhcp-check.zh-CN.md) · [Documentation](README.md)

Use Make on a Linux test host attached to the target device VLAN to check DHCP requests and replies. Requires Python 3.11+, Make, and raw packet privileges (usually root). No Nmap, third-party Python package, or online installation is needed.

The script uses the selected interface's MAC and sends Discover from `0.0.0.0:68` to `255.255.255.255:67`. By default, it sends three times within 15 seconds, collecting and deduplicating Offers matching the transaction and MAC. It never sends Request, accepts a lease, configures IP/routes, or changes Kubernetes, Relay, or firewall configuration. DHCP/NICo may still record the test MAC or a temporary allocation.

Show all parameters and examples (no root or network traffic required):

```bash
make dhcp-check HELP=1
# Equivalent entry
make dhcp-check-help
```

Without `IFACE`, `make dhcp-check` also displays help only. `make dhcp-check --help` invokes GNU Make's own help; it cannot pass that option to the script.

## Commands

Run from the PXEye repository root on the Linux test host. Select an enabled Ethernet/VLAN interface attached to the target VLAN:

```bash
ip -br link
sudo make dhcp-check IFACE=eno1
```

Replace `eno1` with the actual interface. Success on one VLAN does not cover others, and successful ping does not establish DHCP broadcast or Relay connectivity.

If the expected server and subnet are known, check them too; replace example addresses with onsite values:

```bash
sudo make dhcp-check IFACE=eno1 \
  DHCP_SERVER=192.0.2.10 DHCP_SUBNET=192.0.2.0/24
```

`DHCP_SERVER` compares Option 54 (Server Identifier), not the UDP source IP; NAT can make them differ. Without it, receiving an Offer does not establish that NICo replied.

To keep evidence, specify a new JSON file path whose parent directory exists:

```bash
sudo make dhcp-check IFACE=eno1 \
  DHCP_REPORT="/tmp/dhcp-check-$(date +%Y%m%d%H%M%S).json"
```

The report contains interface, MAC, transaction ID, expectations, each Offer, transmission count, and result. Existing files are not overwritten.

## Parameters

| Make variable | Default | Purpose |
| --- | --- | --- |
| `IFACE` | Required | Actual client interface |
| `DHCP_TIMEOUT` | `15` | Total wait, 1–120 seconds |
| `DHCP_ATTEMPTS` | `3` | Discover transmissions, 1–5, evenly spaced within the wait |
| `DHCP_MAC` | Interface MAC | Optional client MAC; a mismatch with the Ethernet MAC may trigger DHCP snooping |
| `DHCP_SERVER` | Identity unchecked | Expected Option 54 server IPv4 |
| `DHCP_SUBNET` | Subnet unchecked | Expected offered IPv4 CIDR; does not check allocation pool bounds |
| `DHCP_REPORT` | No file | Optional JSON report path |

Reserved MACs may receive their reserved address. Servers restricted to registered MACs may ignore a new test MAC. The tool does not alter these policies.

## Results and diagnosis

`OFFER` shows Server Identifier, source IP, offered address, masks, gateways, DNS, NTP, and boot information. Absent fields remain empty.

| RESULT | Script exit code | Meaning |
| --- | --- | --- |
| `pass` | `0` | At least one Offer meets the supplied conditions; without conditions, only confirms receipt |
| `no_offer` | `1` | No matching Offer; check VLAN/Relay/UDP ingress and return path, then NICo subnet, pool, and MAC policy |
| `error` | `2` | Argument, interface, raw packet permission, or report file error |
| `mismatch` | `3` | Offers received, but none match the expected server or subnet |
| Interrupted | `130` | User interrupted; interface configuration unchanged |

Multiple servers trigger a note. An expected Offer does not eliminate competing-server concerns. Make displays the failing script status but usually returns `2` itself; automation needing exact distinctions should read JSON `exit_code` or invoke the script using arguments from `python3 tools/dhcp-check.py --help`.

If the client sends Discover but server logs show no matching MAC/transaction, investigate ingress. If the server sends Offer but the client does not receive it, investigate return paths, ACLs, snooping, and NAT. A timeout alone does not prove a server process failure.

## Acceptance boundary

This command tests the actual interface's broadcast path. It does not enter a Kind network namespace or bypass physical ingress. A ClusterIP-only DHCP Service in Kind usually cannot receive physical broadcasts directly; an actual reachable UDP entrance, network attachment, or Relay is required. NodePort alone does not forward physical broadcasts.

After an Offer, use a dedicated test device to complete Discover → Offer → Request → ACK, and reach boot HTTP, DNS, and NTP from its network. Pod IPs/ClusterIPs in Option 54 or DNS/NTP options require an actual reachable route. See the [pre-installation checklist](pre-installation-checklist.md); Helm Ready and this check cannot replace physical installation acceptance.

The existing `tools/dhcp-discover.py` remains a Nmap compatibility tool. This entry uses the separate `tools/dhcp-check.py`.
