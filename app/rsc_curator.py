r"""Kurasi otomatis file export konfigurasi MikroTik (.rsc) untuk UKK PT Nusantara Digital.

Penjelasan Teknis (1-2 kalimat): Modul ini mem-parsing sintaks export RouterOS (`.rsc`)
termasuk line-continuation `\` dan memverifikasi kesesuaian topologi, VLSM, DHCP, NAT,
firewall, keamanan router, queue bandwidth, switch VLAN, serta wireless AP terhadap soal UKK.
"""

from __future__ import annotations

import re
from typing import Any


def _join_continuations(text: str) -> list[str]:
    lines: list[str] = []
    buf = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        stripped = line.strip()
        if not buf:
            if not stripped or stripped.startswith("#"):
                continue
            buf = stripped
        else:
            buf = f"{buf} {stripped}"
        if buf.endswith("\\"):
            buf = buf[:-1].rstrip()
            continue
        lines.append(buf)
        buf = ""
    if buf:
        lines.append(buf)
    return lines


def _parse_params(rest: str) -> dict[str, str]:
    params: dict[str, str] = {}
    positionals: list[str] = []
    i = 0
    n = len(rest)
    while i < n:
        while i < n and rest[i].isspace():
            i += 1
        if i >= n:
            break
        if rest[i] == "[":
            depth = 1
            start = i + 1
            i += 1
            while i < n and depth > 0:
                if rest[i] == "[":
                    depth += 1
                elif rest[i] == "]":
                    depth -= 1
                i += 1
            bracket_txt = rest[start : i - 1].strip()
            if bracket_txt:
                params["_target"] = bracket_txt
            continue

        # Baca satu token hingga spasi (hormati tanda kutip)
        start = i
        in_quote = False
        while i < n:
            ch = rest[i]
            if ch == "\\" and in_quote and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_quote = not in_quote
                i += 1
                continue
            if not in_quote and ch.isspace():
                break
            i += 1
        token = rest[start:i]
        if "=" not in token:
            positionals.append(token)
            continue
        key, raw_val = token.split("=", 1)
        key = key.strip()
        if raw_val.startswith('"') and raw_val.endswith('"') and len(raw_val) >= 2:
            raw_val = raw_val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        params[key] = raw_val
    if positionals:
        params["_positional"] = " ".join(positionals)
    return params


def parse_rsc(text: str) -> list[dict[str, Any]]:
    """Parse teks .rsc MikroTik menjadi daftar command terstruktur."""
    commands: list[dict[str, Any]] = []
    current_section = ""
    for line in _join_continuations(text):
        if line.startswith("/"):
            parts = line.split()
            section_tokens: list[str] = []
            rest_idx = len(parts)
            actions = {"add", "set", "enable", "disable", "remove", "print"}
            for idx, part in enumerate(parts):
                if idx > 0 and part in actions:
                    rest_idx = idx
                    break
                section_tokens.append(part)
            current_section = " ".join(section_tokens)
            if rest_idx < len(parts):
                action = parts[rest_idx]
                rest = " ".join(parts[rest_idx + 1 :])
                commands.append(
                    {
                        "section": current_section,
                        "action": action,
                        "params": _parse_params(rest),
                        "raw": line,
                    }
                )
        else:
            parts = line.split(None, 1)
            action = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            commands.append(
                {
                    "section": current_section,
                    "action": action,
                    "params": _parse_params(rest),
                    "raw": line,
                }
            )
    return commands


def _norm_limit(val: str) -> str:
    v = (val or "").strip().lower().replace(" ", "")
    aliases = {
        "2000k": "2m",
        "2048k": "2m",
        "2097152": "2m",
        "2000000": "2m",
        "8000k": "8m",
        "8192k": "8m",
        "8388608": "8m",
        "8000000": "8m",
    }
    if "/" in v:
        left, right = v.split("/", 1)
        left = aliases.get(left, left)
        right = aliases.get(right, right)
        return f"{left}/{right}"
    return aliases.get(v, v)


def _find(commands: list[dict[str, Any]], section: str) -> list[dict[str, Any]]:
    sec = section.lower()
    return [c for c in commands if c["section"].lower() == sec]


def _make_check(
    key: str,
    label: str,
    unit_kode: str,
    status: str,
    score: int,
    detail: str,
    evidence: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "unit_kode": unit_kode,
        "status": status,
        "recommended_score": score,
        "detail": detail,
        "evidence": evidence[:240],
    }


def _match_indicator(unit_kode: str, text: str, check_by_key: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if unit_kode not in {
        "J.611000.010.02",
        "J.611000.011.02",
        "J.611000.012.02",
        "J.611000.006.01",
        "J.611000.020.01",
        "J.611000.022.01",
    }:
        return None
    t = text.lower()
    rules_map: list[tuple[list[str], str]] = [
        (["identity"], "identity"),
        (["ether1-wan", "ether2-lan"], "interfaces"),
        (["192.168.205", "ip wan"], "wan_ip"),
        (["1.1.1.1", "8.8.8.8", "dns"], "dns"),
        (["default route"], "default_route"),
        (["vlan 10/20/30 dibuat di router", "vlan-id benar"], "router_vlans"),
        (["ip address tiap interface vlan", "vlsm", "prefix pada tabel"], "vlan_ips"),
        (["dhcp server"], "dhcp_servers"),
        (["pool dhcp", "pool-[divisi]"], "dhcp_pools"),
        (["nat-internet-access", "masquerade"], "nat"),
        (["fw-[fungsi]", "comment rule"], "fw_comments"),
        (["fw-block-guest-to-mgmt"], "fw_guest_mgmt"),
        (["fw-block-guest-to-staff"], "fw_guest_staff"),
        (["fw-block-staff-to-mgmt"], "fw_staff_mgmt"),
        (["fw-allow-winbox-mgmt"], "fw_winbox_allow"),
        (["fw-drop-winbox-others"], "fw_winbox_drop"),
        (["ukk[no_absen]", "user baru"], "user_ukk"),
        (["admin default"], "user_admin"),
        (["telnet", "ftp", "api-ssl"], "services"),
        (["queue-guest"], "queue_guest"),
        (["queue-mgmt-staff"], "queue_mgmt_staff"),
        (["trunk", "tagged"], "switch_vlan"),
        (["access port", "vlan 30"], "switch_vlan"),
        (["nd-guest", "wpa2", "max-station"], "wireless_ap"),
        ([".rsc", "export configuration"], "rsc_export"),
    ]
    for keywords, key in rules_map:
        if any(kw in t for kw in keywords):
            return check_by_key.get(key)
    return None


def curate_rsc(
    rsc_files: list[tuple[str, str]],
    units: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analisis 1 atau lebih file .rsc MikroTik dan petakan ke checklist & indikator soal."""
    all_commands: list[dict[str, Any]] = []
    file_names: list[str] = []
    for fname, content in rsc_files:
        file_names.append(fname)
        all_commands.extend(parse_rsc(content))

    checks: list[dict[str, Any]] = []

    # 1. Identity
    id_cmds = _find(all_commands, "/system identity")
    id_name = next((c["params"].get("name", "") for c in id_cmds if "name" in c["params"]), "")
    if id_name and re.match(r"^UKK_\d+_[A-Za-z0-9_]+$", id_name, re.I):
        checks.append(_make_check("identity", "Identity Router", "J.611000.011.02", "pass", 3, f"Identity sesuai format: {id_name}", id_cmds[0]["raw"]))
    elif id_name:
        checks.append(_make_check("identity", "Identity Router", "J.611000.011.02", "partial", 1, f"Identity diset ({id_name}), namun belum sesuai format UKK_[NO_ABSEN]_[NAMA].", id_cmds[0]["raw"]))
    else:
        checks.append(_make_check("identity", "Identity Router", "J.611000.011.02", "fail", 0, "Identity router belum dikonfigurasi."))

    # 2. Interface ether1-WAN & ether2-LAN
    eth_cmds = _find(all_commands, "/interface ethernet")
    eth_names = {c["params"].get("name", "") for c in eth_cmds}
    has_wan = "ether1-WAN" in eth_names
    has_lan = "ether2-LAN" in eth_names
    if has_wan and has_lan:
        checks.append(_make_check("interfaces", "Interface ether1-WAN & ether2-LAN", "J.611000.011.02", "pass", 3, "ether1-WAN dan ether2-LAN ditemukan.", "; ".join(c["raw"] for c in eth_cmds[:2])))
    elif has_wan or has_lan:
        checks.append(_make_check("interfaces", "Interface ether1-WAN & ether2-LAN", "J.611000.011.02", "partial", 1, f"Hanya sebagian interface ditemukan ({', '.join(sorted(eth_names)) or '-'})."))
    else:
        checks.append(_make_check("interfaces", "Interface ether1-WAN & ether2-LAN", "J.611000.011.02", "fail", 0, "Penamaan ether1-WAN dan ether2-LAN tidak ditemukan."))

    # 3. IP Address WAN & VLAN
    ip_cmds = _find(all_commands, "/ip address")
    wan_ips = [c for c in ip_cmds if c["params"].get("address", "").startswith("192.168.205.") and "/24" in c["params"].get("address", "")]
    if wan_ips:
        checks.append(_make_check("wan_ip", "IP WAN Static (192.168.205.x/24)", "J.611000.011.02", "pass", 3, f"IP WAN ditemukan: {wan_ips[0]['params'].get('address')}", wan_ips[0]["raw"]))
    else:
        checks.append(_make_check("wan_ip", "IP WAN Static (192.168.205.x/24)", "J.611000.011.02", "fail", 0, "IP WAN 192.168.205.x/24 tidak ditemukan di /ip address."))

    # 4. DNS
    dns_cmds = _find(all_commands, "/ip dns")
    dns_servers = " ".join(c["params"].get("servers", "") for c in dns_cmds)
    if "1.1.1.1" in dns_servers and "8.8.8.8" in dns_servers:
        checks.append(_make_check("dns", "DNS 1.1.1.1 & 8.8.8.8", "J.611000.011.02", "pass", 3, f"DNS sesuai: {dns_servers}", dns_cmds[0]["raw"]))
    elif "1.1.1.1" in dns_servers or "8.8.8.8" in dns_servers:
        checks.append(_make_check("dns", "DNS 1.1.1.1 & 8.8.8.8", "J.611000.011.02", "partial", 2, f"DNS baru sebagian: {dns_servers}", dns_cmds[0]["raw"]))
    else:
        checks.append(_make_check("dns", "DNS 1.1.1.1 & 8.8.8.8", "J.611000.011.02", "fail", 0, "DNS 1.1.1.1 dan 8.8.8.8 belum diset."))

    # 5. Default Route
    route_cmds = _find(all_commands, "/ip route")
    def_routes = [c for c in route_cmds if c["params"].get("gateway", "").startswith("192.168.205.1")]
    if def_routes:
        checks.append(_make_check("default_route", "Default Route ke Gateway ISP", "J.611000.011.02", "pass", 3, "Default route ke 192.168.205.1 ditemukan.", def_routes[0]["raw"]))
    else:
        checks.append(_make_check("default_route", "Default Route ke Gateway ISP", "J.611000.011.02", "fail", 0, "Default route ke gateway 192.168.205.1 tidak ditemukan."))

    # 6. VLAN Router
    vlan_cmds = _find(all_commands, "/interface vlan")
    vlan_ids = {c["params"].get("vlan-id"): c["params"].get("name", "") for c in vlan_cmds}
    found_v = [vid for vid in ("10", "20", "30") if vid in vlan_ids]
    if len(found_v) == 3:
        checks.append(_make_check("router_vlans", "VLAN 10/20/30 di Router", "J.611000.011.02", "pass", 3, f"Ketiga VLAN ditemukan: {', '.join(vlan_ids[v] for v in found_v)}.", "; ".join(c["raw"] for c in vlan_cmds[:3])))
    elif found_v:
        checks.append(_make_check("router_vlans", "VLAN 10/20/30 di Router", "J.611000.011.02", "partial", 1, f"Baru {len(found_v)}/3 VLAN ditemukan (ID: {', '.join(found_v)})."))
    else:
        checks.append(_make_check("router_vlans", "VLAN 10/20/30 di Router", "J.611000.011.02", "fail", 0, "VLAN 10/20/30 tidak ditemukan di /interface vlan."))

    # 7. IP VLAN (VLSM)
    ip_strs = {c["params"].get("address", "") for c in ip_cmds}
    expected_vlsm = {"192.168.10.1/28", "192.168.20.1/26", "192.168.30.1/27"}
    matched_vlsm = expected_vlsm & ip_strs
    if len(matched_vlsm) == 3:
        checks.append(_make_check("vlan_ips", "IP Address VLAN (VLSM)", "J.611000.011.02", "pass", 3, "Seluruh IP VLSM (/28, /26, /27) sesuai tabel.", ", ".join(sorted(matched_vlsm))))
    elif matched_vlsm:
        checks.append(_make_check("vlan_ips", "IP Address VLAN (VLSM)", "J.611000.011.02", "partial", 1, f"Baru {len(matched_vlsm)}/3 IP VLSM sesuai: {', '.join(sorted(matched_vlsm))}."))
    else:
        checks.append(_make_check("vlan_ips", "IP Address VLAN (VLSM)", "J.611000.011.02", "fail", 0, "IP VLAN sesuai prefix VLSM (/28, /26, /27) tidak ditemukan."))

    # 8. DHCP Pool & Server
    pool_cmds = _find(all_commands, "/ip pool")
    pool_ranges = {c["params"].get("name", "").upper(): c["params"].get("ranges", "") for c in pool_cmds}
    expected_pools = {
        "POOL-MANAGEMENT": "192.168.10.5-192.168.10.14",
        "POOL-STAFF": "192.168.20.10-192.168.20.62",
        "POOL-GUEST": "192.168.30.5-192.168.30.30",
    }
    pool_ok = [name for name, rng in expected_pools.items() if rng in pool_ranges.get(name, "")]
    if len(pool_ok) == 3:
        checks.append(_make_check("dhcp_pools", "DHCP Pool (POOL-[DIVISI])", "J.611000.011.02", "pass", 3, "Ketiga IP Pool sesuai range tabel VLSM."))
    elif pool_ok or pool_cmds:
        checks.append(_make_check("dhcp_pools", "DHCP Pool (POOL-[DIVISI])", "J.611000.011.02", "partial", 1, f"Pool ditemukan: {', '.join(pool_ranges.keys()) or '-'} (sesuai range: {len(pool_ok)}/3)."))
    else:
        checks.append(_make_check("dhcp_pools", "DHCP Pool (POOL-[DIVISI])", "J.611000.011.02", "fail", 0, "DHCP Pool tidak ditemukan."))

    dhcp_cmds = _find(all_commands, "/ip dhcp-server")
    dhcp_names = {c["params"].get("name", "").upper() for c in dhcp_cmds}
    dhcp_ok = {"DHCP-MANAGEMENT", "DHCP-STAFF", "DHCP-GUEST"} & dhcp_names
    if len(dhcp_ok) == 3:
        checks.append(_make_check("dhcp_servers", "DHCP Server (3 VLAN)", "J.611000.011.02", "pass", 3, "Ketiga DHCP Server (MANAGEMENT, STAFF, GUEST) aktif."))
    elif dhcp_cmds:
        checks.append(_make_check("dhcp_servers", "DHCP Server (3 VLAN)", "J.611000.011.02", "partial", 1, f"DHCP Server ditemukan: {', '.join(sorted(dhcp_names))}."))
    else:
        checks.append(_make_check("dhcp_servers", "DHCP Server (3 VLAN)", "J.611000.011.02", "fail", 0, "DHCP Server tidak ditemukan."))

    # 9. NAT Masquerade
    nat_cmds = _find(all_commands, "/ip firewall nat")
    nat_ok = [c for c in nat_cmds if c["params"].get("action") == "masquerade"]
    nat_comment = [c for c in nat_ok if c["params"].get("comment", "").upper() == "NAT-INTERNET-ACCESS"]
    if nat_comment:
        checks.append(_make_check("nat", "NAT Masquerade (NAT-INTERNET-ACCESS)", "J.611000.011.02", "pass", 3, "NAT Masquerade dengan comment NAT-INTERNET-ACCESS ditemukan.", nat_comment[0]["raw"]))
    elif nat_ok:
        checks.append(_make_check("nat", "NAT Masquerade (NAT-INTERNET-ACCESS)", "J.611000.011.02", "partial", 2, "NAT Masquerade ada, namun comment belum NAT-INTERNET-ACCESS.", nat_ok[0]["raw"]))
    else:
        checks.append(_make_check("nat", "NAT Masquerade (NAT-INTERNET-ACCESS)", "J.611000.011.02", "fail", 0, "Rule NAT Masquerade tidak ditemukan."))

    # 10. Firewall Rules
    fw_cmds = _find(all_commands, "/ip firewall filter")
    fw_by_comment = {c["params"].get("comment", "").upper(): c for c in fw_cmds if c["params"].get("comment")}
    fw_specs = [
        ("fw_guest_mgmt", "FW-BLOCK-GUEST-TO-MGMT", "drop"),
        ("fw_guest_staff", "FW-BLOCK-GUEST-TO-STAFF", "drop"),
        ("fw_staff_mgmt", "FW-BLOCK-STAFF-TO-MGMT", "drop"),
        ("fw_winbox_allow", "FW-ALLOW-WINBOX-MGMT", "accept"),
        ("fw_winbox_drop", "FW-DROP-WINBOX-OTHERS", "drop"),
    ]
    fw_matched = 0
    for key, cname, expected_act in fw_specs:
        rule = fw_by_comment.get(cname)
        if rule and rule["params"].get("action", "accept") == expected_act:
            fw_matched += 1
            checks.append(_make_check(key, f"Firewall {cname}", "J.611000.006.01", "pass", 3, f"Rule {cname} (action={expected_act}) ditemukan.", rule["raw"]))
        elif rule:
            checks.append(_make_check(key, f"Firewall {cname}", "J.611000.006.01", "partial", 1, f"Rule {cname} ada, tetapi action={rule['params'].get('action')} (seharusnya {expected_act}).", rule["raw"]))
        else:
            checks.append(_make_check(key, f"Firewall {cname}", "J.611000.006.01", "fail", 0, f"Rule {cname} tidak ditemukan."))
    checks.append(
        _make_check(
            "fw_comments",
            "Format Comment FW-[FUNGSI]",
            "J.611000.006.01",
            "pass" if fw_matched == 5 else ("partial" if fw_matched > 0 else "fail"),
            3 if fw_matched == 5 else (1 if fw_matched > 0 else 0),
            f"{fw_matched}/5 rule firewall memakai comment FW-[FUNGSI] sesuai ketentuan.",
        )
    )

    # 11. Router Security: User & Service
    user_cmds = _find(all_commands, "/user")
    ukk_users = [c for c in user_cmds if re.match(r"^UKK\d+$", c["params"].get("name", ""), re.I)]
    if ukk_users:
        checks.append(_make_check("user_ukk", "User Baru UKK[NO_ABSEN]", "J.611000.006.01", "pass", 3, f"User baru ditemukan: {ukk_users[0]['params'].get('name')}", ukk_users[0]["raw"]))
    else:
        checks.append(_make_check("user_ukk", "User Baru UKK[NO_ABSEN]", "J.611000.006.01", "fail", 0, "User UKK[NO_ABSEN] tidak ditemukan di /user."))

    admin_disabled = any(
        (c["params"].get("name") == "admin" or c["params"].get("_positional") == "admin" or "admin" in c["params"].get("_target", ""))
        and c["params"].get("disabled") == "yes"
        for c in user_cmds
    )
    admin_present = any(c["params"].get("name") == "admin" for c in user_cmds)
    if admin_disabled or (user_cmds and not admin_present):
        checks.append(_make_check("user_admin", "User admin default diamankan", "J.611000.006.01", "pass", 3, "User admin default dinonaktifkan atau dihapus."))
    else:
        checks.append(_make_check("user_admin", "User admin default diamankan", "J.611000.006.01", "partial", 1, "Pastikan password user admin default telah diganti jika tidak dinonaktifkan."))

    svc_cmds = _find(all_commands, "/ip service")
    disabled_svcs = set()
    for c in svc_cmds:
        if c["params"].get("disabled") == "yes":
            sname = c["params"].get("name") or c["params"].get("_positional") or ""
            if not sname and "name=" in c["params"].get("_target", ""):
                m_svc = re.search(r"name=([^\s]+)", c["params"]["_target"])
                if m_svc:
                    sname = m_svc.group(1)
            if sname:
                disabled_svcs.add(sname.strip())
    must_disable = {"telnet", "ftp", "www", "api", "api-ssl"}
    still_missing = sorted(must_disable - disabled_svcs)
    if not still_missing:
        checks.append(_make_check("services", "Disable Service Tidak Terpakai", "J.611000.006.01", "pass", 3, "telnet, ftp, www, api, api-ssl semuanya disabled."))
    elif len(still_missing) < len(must_disable):
        checks.append(_make_check("services", "Disable Service Tidak Terpakai", "J.611000.006.01", "partial", 1, f"Service yang belum disabled: {', '.join(still_missing)}."))
    else:
        checks.append(_make_check("services", "Disable Service Tidak Terpakai", "J.611000.006.01", "fail", 0, "Service tidak terpakai (telnet, ftp, www, api, api-ssl) belum dinonaktifkan."))

    # 12. Bandwidth Management (/queue simple)
    q_cmds = _find(all_commands, "/queue simple")
    q_by_name = {c["params"].get("name", "").upper(): c for c in q_cmds}
    qg = q_by_name.get("QUEUE-GUEST")
    if qg and _norm_limit(qg["params"].get("max-limit", "")) == "2m/2m":
        checks.append(_make_check("queue_guest", "QUEUE-GUEST (2M/2M)", "J.611000.020.01", "pass", 3, "QUEUE-GUEST max-limit 2M/2M sesuai.", qg["raw"]))
    elif qg:
        checks.append(_make_check("queue_guest", "QUEUE-GUEST (2M/2M)", "J.611000.020.01", "partial", 1, f"QUEUE-GUEST ditemukan, max-limit={qg['params'].get('max-limit')}.", qg["raw"]))
    else:
        checks.append(_make_check("queue_guest", "QUEUE-GUEST (2M/2M)", "J.611000.020.01", "fail", 0, "QUEUE-GUEST tidak ditemukan di /queue simple."))

    qm = q_by_name.get("QUEUE-MGMT-STAFF")
    if qm and _norm_limit(qm["params"].get("max-limit", "")) == "8m/8m":
        checks.append(_make_check("queue_mgmt_staff", "QUEUE-MGMT-STAFF (8M/8M)", "J.611000.020.01", "pass", 3, "QUEUE-MGMT-STAFF max-limit 8M/8M sesuai.", qm["raw"]))
    elif qm:
        checks.append(_make_check("queue_mgmt_staff", "QUEUE-MGMT-STAFF (8M/8M)", "J.611000.020.01", "partial", 1, f"QUEUE-MGMT-STAFF ditemukan, max-limit={qm['params'].get('max-limit')}.", qm["raw"]))
    else:
        checks.append(_make_check("queue_mgmt_staff", "QUEUE-MGMT-STAFF (8M/8M)", "J.611000.020.01", "fail", 0, "QUEUE-MGMT-STAFF tidak ditemukan di /queue simple."))

    # 13. Switch MikroTik & Wireless AP (opsional bila file .rsc switch/AP ikut diupload)
    sw_cmds = _find(all_commands, "/interface bridge vlan") + _find(all_commands, "/interface ethernet switch vlan")
    if sw_cmds:
        sw_raw = " ".join(c["raw"] for c in sw_cmds)
        has_all_sw = all(v in sw_raw for v in ("10", "20", "30"))
        checks.append(_make_check("switch_vlan", "Switch VLAN 10/20/30 (MikroTik)", "J.611000.012.02", "pass" if has_all_sw else "partial", 3 if has_all_sw else 1, "Konfigurasi VLAN switch MikroTik terdeteksi.", sw_cmds[0]["raw"]))

    ap_cmds = _find(all_commands, "/interface wireless") + _find(all_commands, "/interface wifi") + _find(all_commands, "/interface wireless security-profiles")
    if ap_cmds:
        ap_raw = " ".join(c["raw"] for c in ap_cmds)
        has_ssid = "ND-GUEST" in ap_raw
        has_max = "max-station-count=15" in ap_raw
        if has_ssid and has_max:
            checks.append(_make_check("wireless_ap", "Wireless AP ND-GUEST (max-station 15)", "J.611000.010.02", "pass", 3, "SSID ND-GUEST dan max-station-count=15 ditemukan.", ap_cmds[0]["raw"]))
        elif has_ssid:
            checks.append(_make_check("wireless_ap", "Wireless AP ND-GUEST (max-station 15)", "J.611000.010.02", "partial", 2, "SSID ND-GUEST ditemukan; cek ulang WPA2-PSK dan max-station-count=15.", ap_cmds[0]["raw"]))

    # 14. Export .rsc ada & nama file sesuai format
    rsc_name_ok = any(re.match(r"^UKK_\d+_.+_BACKUP\.rsc$", fn, re.I) for fn in file_names)
    checks.append(
        _make_check(
            "rsc_export",
            "File Export .rsc",
            "J.611000.022.01",
            "pass" if rsc_name_ok else "partial",
            3 if rsc_name_ok else 2,
            f"File .rsc diunggah ({', '.join(file_names)})." + ("" if rsc_name_ok else " Disarankan format nama UKK_[NO_ABSEN]_[NAMA]_BACKUP.rsc."),
        )
    )

    check_by_key = {item["key"]: item for item in checks}
    suggested_scores: dict[str, dict[str, Any]] = {}
    for unit in units or []:
        ukode = str(unit.get("kode") or "")
        for ind in unit.get("indicators") or []:
            matched = _match_indicator(ukode, ind.get("teks", ""), check_by_key)
            if matched is not None:
                suggested_scores[ind["kode"]] = {
                    "score": matched["recommended_score"],
                    "note": matched["detail"],
                    "check_key": matched["key"],
                    "status": matched["status"],
                }

    passed = sum(1 for c in checks if c["status"] == "pass")
    partial = sum(1 for c in checks if c["status"] == "partial")
    failed = sum(1 for c in checks if c["status"] == "fail")
    total = len(checks)
    match_percent = round(((passed + partial * 0.5) / total) * 100, 1) if total else 0.0

    return {
        "files": file_names,
        "summary": {
            "total_checks": total,
            "passed": passed,
            "partial": partial,
            "failed": failed,
            "match_percent": match_percent,
            "suggested_indicators": len(suggested_scores),
        },
        "checks": checks,
        "suggested_scores": suggested_scores,
    }
