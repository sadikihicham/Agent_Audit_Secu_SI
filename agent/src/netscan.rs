//! Scan réseau léger (Phase A) : découverte d'appareils sur le LAN local.
//!
//! Périmètre sûr : on ne scanne que les CIDR de l'allowlist *qui recoupent un
//! sous-réseau local de l'hôte* (auto-détection des interfaces). Tout le reste
//! est refusé par défaut.
//!
//! Méthode (sans privilège root) :
//!  1. balayage TCP-connect d'un petit jeu de ports (présence + indice de type) ;
//!  2. lecture de la table ARP (`/proc/net/arp`, Linux) → IP↔MAC pour les hôtes
//!     ayant répondu au niveau 2 même si tous leurs ports sont fermés ;
//!  3. reverse-DNS pour le nom d'hôte, OUI MAC pour le constructeur ;
//!  4. heuristique type/OS à partir des ports ouverts + constructeur.
//!
//! Les ports détaillés et les vulnérabilités arrivent en Phase B.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

use ipnet::{IpNet, Ipv4Net};
use serde::Serialize;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::sync::Semaphore;
use tokio::time::timeout;
use tracing::{debug, info, warn};

use crate::config::ScanConfig;

/// Un port ouvert découvert sur un appareil (Phase B).
#[derive(Debug, Clone, Serialize)]
pub struct ScanPort {
    pub port: u16,
    pub protocol: String,
    pub service_name: Option<String>,
    pub service_version: Option<String>,
    pub banner: Option<String>,
}

/// Une interface réseau d'un appareil, relevée par SNMP (ifTable).
#[derive(Debug, Clone, Serialize)]
pub struct ScanInterface {
    pub if_index: i32,
    pub name: Option<String>,
    pub mac: Option<String>,
    pub admin_up: Option<bool>,
    pub oper_up: Option<bool>,
    pub speed_bps: Option<i64>,
    pub mtu: Option<i32>,
    pub in_octets: Option<i64>,
    pub out_octets: Option<i64>,
}

/// Un appareil découvert, prêt à être envoyé à `POST /ingest/scan`.
#[derive(Debug, Clone, Serialize)]
pub struct ScanDevice {
    pub ip: String,
    pub mac: Option<String>,
    pub hostname: Option<String>,
    pub vendor: Option<String>,
    pub device_type: String,
    pub os_guess: Option<String>,
    pub is_gateway: bool,
    pub status: String,
    pub ports: Vec<ScanPort>,
    // Enrichissement SNMP (rempli ultérieurement par le module `snmp` ; valeurs
    // par défaut si SNMP désactivé ou appareil injoignable).
    pub sys_descr: Option<String>,
    pub sys_name: Option<String>,
    pub sys_uptime_secs: Option<i64>,
    pub sys_location: Option<String>,
    pub sys_contact: Option<String>,
    pub snmp_reachable: bool,
    pub interfaces: Vec<ScanInterface>,
}

/// Exécute un scan complet du périmètre autorisé et renvoie les appareils vivants.
pub async fn run_scan(cfg: &ScanConfig) -> Vec<ScanDevice> {
    let local_nets = local_ipv4_networks();
    if local_nets.is_empty() {
        warn!("Aucun sous-réseau IPv4 local détecté — scan ignoré");
        return vec![];
    }

    // Cibles = allowlist ∩ sous-réseaux locaux (refus par défaut hors LAN local).
    let mut targets: Vec<Ipv4Addr> = Vec::new();
    for cidr in &cfg.allowlist {
        match cidr.parse::<IpNet>() {
            Ok(IpNet::V4(net)) => {
                let overlaps = local_nets
                    .iter()
                    .any(|(_, lnet)| lnet.contains(&net) || net.contains(lnet));
                if !overlaps {
                    warn!(
                        "CIDR {} hors des sous-réseaux locaux — ignoré (refus par défaut)",
                        cidr
                    );
                    continue;
                }
                for host in net.hosts() {
                    targets.push(host);
                }
            }
            Ok(IpNet::V6(_)) => warn!("CIDR IPv6 non supporté en Phase A : {}", cidr),
            Err(e) => warn!("CIDR invalide '{}' : {}", cidr, e),
        }
    }
    targets.sort();
    targets.dedup();
    if targets.is_empty() {
        warn!("Aucune cible (allowlist vide ou hors sous-réseau local) — scan ignoré");
        return vec![];
    }
    info!("Scan réseau : {} hôte(s) cible(s)", targets.len());

    let target_set: HashSet<Ipv4Addr> = targets.iter().copied().collect();
    let own_ips: HashSet<Ipv4Addr> = local_nets.iter().map(|(ip, _)| *ip).collect();
    let arp = read_arp_table();
    let gateway = default_gateway();

    // Balayage TCP-connect concurrent (plafonné par un sémaphore).
    let sem = Arc::new(Semaphore::new(cfg.concurrency.max(1)));
    let ports = Arc::new(cfg.probe_ports.clone());
    let timeout_dur = Duration::from_millis(cfg.timeout_ms.max(50));
    let mut handles = Vec::with_capacity(targets.len());
    for ip in targets {
        let sem = sem.clone();
        let ports = ports.clone();
        handles.push(tokio::spawn(async move {
            let _permit = sem.acquire_owned().await.ok()?;
            let mut open = Vec::new();
            for &p in ports.iter() {
                let addr = SocketAddr::from((ip, p));
                if let Ok(Ok(_)) = timeout(timeout_dur, TcpStream::connect(addr)).await {
                    open.push(p);
                }
            }
            Some((ip, open))
        }));
    }

    let mut open_map: BTreeMap<Ipv4Addr, Vec<u16>> = BTreeMap::new();
    for h in handles {
        if let Ok(Some((ip, open))) = h.await {
            if !open.is_empty() {
                open_map.insert(ip, open);
            }
        }
    }

    // Vivants = port ouvert OU présent dans la table ARP (dans le périmètre).
    let mut live: BTreeSet<Ipv4Addr> = open_map.keys().copied().collect();
    for ip in arp.keys() {
        if target_set.contains(ip) {
            live.insert(*ip);
        }
    }
    for own in &own_ips {
        live.remove(own); // ne pas se lister soi-même
    }
    info!(
        "{} h\u{f4}te(s) vivant(s) — scan d\u{e9}taill\u{e9} des ports",
        live.len()
    );

    // ── Passe 2 : scan détaillé des ports + bannières sur les hôtes vivants ──
    let scan_ports = Arc::new(cfg.scan_ports.clone());
    let mut detail_handles = Vec::new();
    for &ip in &live {
        for &port in scan_ports.iter() {
            let sem = sem.clone();
            detail_handles.push(tokio::spawn(async move {
                let _permit = sem.acquire_owned().await.ok()?;
                probe_and_grab(ip, port, timeout_dur)
                    .await
                    .map(|sp| (ip, sp))
            }));
        }
    }
    let mut ports_by_ip: HashMap<Ipv4Addr, Vec<ScanPort>> = HashMap::new();
    for h in detail_handles {
        if let Ok(Some((ip, sp))) = h.await {
            ports_by_ip.entry(ip).or_default().push(sp);
        }
    }

    let mut devices: Vec<ScanDevice> = Vec::new();
    for ip in live {
        let mac = arp.get(&ip).cloned();
        let vendor = mac.as_deref().and_then(oui_vendor);
        let mut ports = ports_by_ip.remove(&ip).unwrap_or_default();
        ports.sort_by_key(|p| p.port);
        // Numéros de ports ouverts pour la classification (détail sinon liveness).
        let open: Vec<u16> = if ports.is_empty() {
            open_map.get(&ip).cloned().unwrap_or_default()
        } else {
            ports.iter().map(|p| p.port).collect()
        };
        let is_gateway = gateway == Some(ip);
        let (device_type, os_guess) = classify(&open, vendor.as_deref(), is_gateway);
        debug!(
            "Appareil {} mac={:?} vendor={:?} ports={:?} type={}",
            ip, mac, vendor, open, device_type
        );
        devices.push(ScanDevice {
            ip: ip.to_string(),
            mac,
            hostname: None,
            vendor,
            device_type,
            os_guess,
            is_gateway,
            status: "up".to_string(),
            ports,
            sys_descr: None,
            sys_name: None,
            sys_uptime_secs: None,
            sys_location: None,
            sys_contact: None,
            snmp_reachable: false,
            interfaces: Vec::new(),
        });
    }

    resolve_hostnames(&mut devices).await;
    devices
}

/// Connecte un port ; s'il est ouvert, tente une capture de bannière.
async fn probe_and_grab(ip: Ipv4Addr, port: u16, timeout_dur: Duration) -> Option<ScanPort> {
    let addr = SocketAddr::from((ip, port));
    let stream = match timeout(timeout_dur, TcpStream::connect(addr)).await {
        Ok(Ok(s)) => s,
        _ => return None,
    };
    let (banner, version) = grab_banner(stream, port, timeout_dur).await;
    Some(ScanPort {
        port,
        protocol: "tcp".to_string(),
        service_name: None, // renseigné côté API d'après le numéro de port
        service_version: version,
        banner,
    })
}

/// Capture de bannière best-effort : HEAD HTTP pour les ports web, lecture de la
/// salutation sinon. Renvoie (bannière brute, version extraite).
async fn grab_banner(
    mut stream: TcpStream,
    port: u16,
    timeout_dur: Duration,
) -> (Option<String>, Option<String>) {
    let is_http = matches!(port, 80 | 591 | 8000 | 8008 | 8080 | 8888);
    if is_http {
        let req = b"HEAD / HTTP/1.0\r\nHost: scan\r\nUser-Agent: GuardianOps\r\n\r\n";
        let _ = timeout(timeout_dur, stream.write_all(req)).await;
    }
    let mut buf = vec![0u8; 1024];
    let n = match timeout(timeout_dur, stream.read(&mut buf)).await {
        Ok(Ok(n)) if n > 0 => n,
        _ => return (None, None),
    };
    let banner = String::from_utf8_lossy(&buf[..n]).trim().to_string();
    if banner.is_empty() {
        return (None, None);
    }
    let version = extract_version(&banner);
    let banner_capped: String = banner.chars().take(2000).collect();
    (Some(banner_capped), version)
}

/// Extrait une version de service : en-tête HTTP `Server:` sinon 1ʳᵉ ligne.
fn extract_version(banner: &str) -> Option<String> {
    for line in banner.lines() {
        if line.to_ascii_lowercase().starts_with("server:") {
            let val = line[7..].trim();
            if !val.is_empty() {
                return Some(val.chars().take(128).collect());
            }
        }
    }
    banner
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .map(|l| l.chars().take(128).collect())
}

/// Remplit `hostname` via reverse-DNS, en parallèle (lookups bloquants).
async fn resolve_hostnames(devices: &mut [ScanDevice]) {
    let mut handles = Vec::with_capacity(devices.len());
    for d in devices.iter() {
        let ip: Option<IpAddr> = d.ip.parse().ok();
        handles.push(tokio::task::spawn_blocking(move || {
            ip.and_then(|ip| dns_lookup::lookup_addr(&ip).ok())
        }));
    }
    for (d, h) in devices.iter_mut().zip(handles) {
        if let Ok(Some(name)) = h.await {
            if !name.is_empty() && name != d.ip {
                d.hostname = Some(name);
            }
        }
    }
}

/// Sous-réseaux IPv4 locaux (hors loopback) : (ip de l'interface, réseau tronqué).
fn local_ipv4_networks() -> Vec<(Ipv4Addr, Ipv4Net)> {
    let mut out = Vec::new();
    match if_addrs::get_if_addrs() {
        Ok(ifaces) => {
            for iface in ifaces {
                if iface.is_loopback() {
                    continue;
                }
                if let if_addrs::IfAddr::V4(v4) = iface.addr {
                    let prefix = ipnet::ipv4_mask_to_prefix(v4.netmask).unwrap_or(24);
                    if let Ok(net) = Ipv4Net::new(v4.ip, prefix) {
                        out.push((v4.ip, net.trunc()));
                    }
                }
            }
        }
        Err(e) => warn!("Détection des interfaces locales impossible : {}", e),
    }
    out
}

/// Table ARP (Linux) : IP → MAC (uppercase). Vide hors Linux.
fn read_arp_table() -> HashMap<Ipv4Addr, String> {
    let mut map = HashMap::new();
    let Ok(content) = std::fs::read_to_string("/proc/net/arp") else {
        return map;
    };
    // En-tête : IP address  HW type  Flags  HW address  Mask  Device
    for line in content.lines().skip(1) {
        let cols: Vec<&str> = line.split_whitespace().collect();
        if cols.len() < 4 {
            continue;
        }
        let Ok(ip) = cols[0].parse::<Ipv4Addr>() else {
            continue;
        };
        let mac = cols[3].to_uppercase();
        if mac != "00:00:00:00:00:00" && cols[2] != "0x0" {
            map.insert(ip, mac);
        }
    }
    map
}

/// Passerelle par défaut (Linux, `/proc/net/route`). None hors Linux / absente.
fn default_gateway() -> Option<Ipv4Addr> {
    let content = std::fs::read_to_string("/proc/net/route").ok()?;
    for line in content.lines().skip(1) {
        let cols: Vec<&str> = line.split_whitespace().collect();
        // Iface  Destination  Gateway  Flags ...
        if cols.len() >= 3 && cols[1] == "00000000" {
            if let Ok(raw) = u32::from_str_radix(cols[2], 16) {
                // Stocké en little-endian dans le fichier.
                return Some(Ipv4Addr::from(raw.to_le_bytes()));
            }
        }
    }
    None
}

/// Constructeur d'après le préfixe OUI du MAC (table embarquée, sous-ensemble).
fn oui_vendor(mac: &str) -> Option<String> {
    let prefix = mac.get(0..8)?.to_uppercase();
    OUI_TABLE
        .iter()
        .find(|(p, _)| *p == prefix)
        .map(|(_, v)| v.to_string())
}

/// Heuristique type d'appareil + OS d'après les ports ouverts et le constructeur.
fn classify(open: &[u16], vendor: Option<&str>, is_gateway: bool) -> (String, Option<String>) {
    let has = |p: u16| open.contains(&p);
    let v = vendor.unwrap_or("").to_lowercase();

    if has(9100)
        || has(515)
        || has(631)
        || v.contains("hewlett")
        || v.contains("canon")
        || v.contains("epson")
        || v.contains("brother")
    {
        return ("printer".to_string(), None);
    }
    if v.contains("synology") || v.contains("qnap") {
        return ("nas".to_string(), None);
    }
    if is_gateway
        || v.contains("cisco")
        || v.contains("tp-link")
        || v.contains("netgear")
        || v.contains("d-link")
        || v.contains("ubiquiti")
        || v.contains("mikrotik")
        || v.contains("zyxel")
    {
        return ("router".to_string(), None);
    }
    if v.contains("espressif")
        || v.contains("raspberry")
        || v.contains("sonos")
        || v.contains("amazon")
        || v.contains("google")
        || v.contains("xiaomi")
        || v.contains("tuya")
        || v.contains("nest")
    {
        return ("iot".to_string(), None);
    }
    if has(3389) || has(445) {
        return ("workstation".to_string(), Some("Windows".to_string()));
    }
    if v.contains("apple") || v.contains("samsung") {
        return ("phone".to_string(), None);
    }
    if has(22) && (has(80) || has(443)) {
        return ("server".to_string(), Some("Linux/Unix".to_string()));
    }
    if has(80) || has(443) || has(22) {
        return ("server".to_string(), None);
    }
    ("unknown".to_string(), None)
}

/// Sous-ensemble curé de préfixes OUI (IEEE) → constructeur.
/// Couverture partielle assumée (MVP) ; complétée si besoin en Phase B.
const OUI_TABLE: &[(&str, &str)] = &[
    ("00:1A:11", "Google"),
    ("3C:5A:B4", "Google"),
    ("F4:F5:E8", "Google"),
    ("44:65:0D", "Amazon"),
    ("FC:65:DE", "Amazon"),
    ("68:54:FD", "Amazon"),
    ("DC:A6:32", "Raspberry Pi"),
    ("B8:27:EB", "Raspberry Pi"),
    ("E4:5F:01", "Raspberry Pi"),
    ("24:0A:C4", "Espressif"),
    ("3C:61:05", "Espressif"),
    ("A4:CF:12", "Espressif"),
    ("EC:FA:BC", "Espressif"),
    ("00:17:88", "Philips Hue"),
    ("5C:CF:7F", "Espressif"),
    ("00:0C:29", "VMware"),
    ("00:50:56", "VMware"),
    ("00:1C:42", "Parallels"),
    ("08:00:27", "VirtualBox"),
    ("52:54:00", "QEMU/KVM"),
    ("00:15:5D", "Microsoft Hyper-V"),
    ("00:03:93", "Apple"),
    ("00:1E:C2", "Apple"),
    ("3C:07:54", "Apple"),
    ("A4:83:E7", "Apple"),
    ("F0:18:98", "Apple"),
    ("AC:DE:48", "Apple"),
    ("DC:A9:04", "Apple"),
    ("00:16:32", "Samsung"),
    ("8C:77:12", "Samsung"),
    ("5C:0A:5B", "Samsung"),
    ("00:1D:7E", "Cisco"),
    ("00:25:45", "Cisco"),
    ("00:1B:0D", "Cisco"),
    ("E0:55:3D", "Cisco Meraki"),
    ("50:C7:BF", "TP-Link"),
    ("AC:84:C6", "TP-Link"),
    ("C4:6E:1F", "TP-Link"),
    ("00:14:6C", "Netgear"),
    ("A0:40:A0", "Netgear"),
    ("00:1C:F0", "D-Link"),
    ("00:24:01", "D-Link"),
    ("44:D9:E7", "Ubiquiti"),
    ("FC:EC:DA", "Ubiquiti"),
    ("E8:DE:27", "Ubiquiti"),
    ("48:8F:5A", "MikroTik"),
    ("00:0C:42", "MikroTik"),
    ("00:09:6B", "Huawei"),
    ("00:E0:FC", "Huawei"),
    ("00:1E:10", "Huawei"),
    ("00:11:32", "Synology"),
    ("00:08:9B", "QNAP"),
    ("24:5E:BE", "QNAP"),
    ("00:21:5A", "Hewlett-Packard"),
    ("3C:D9:2B", "Hewlett-Packard"),
    ("00:1B:A9", "Brother"),
    ("00:00:48", "Epson"),
    ("00:00:85", "Canon"),
    ("00:26:AB", "Seiko Epson"),
    ("B0:0C:D1", "Xiaomi"),
    ("64:09:80", "Xiaomi"),
    ("00:0E:58", "Sonos"),
    ("5C:AA:FD", "Sonos"),
    ("18:B4:30", "Nest"),
];
