//! Enrichissement SNMP v2c (lecture seule) des appareils découverts.
//!
//! Après le scan TCP, on interroge en UDP 161 chaque appareil pour récupérer :
//!  - le **groupe système** (MIB-II) : sysDescr, sysName, sysUpTime, sysLocation,
//!    sysContact — infos fiables que le scan TCP ne peut que deviner ;
//!  - en option, la **table des interfaces** (ifTable) : nom, statut, débit,
//!    octets in/out par interface réseau.
//!
//! Opt-in (`[snmp] enabled = true`) et best-effort : un appareil injoignable en
//! SNMP est simplement laissé tel quel (`snmp_reachable = false`).

use std::collections::{BTreeMap, BTreeSet};
use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

use csnmp::{ObjectIdentifier, ObjectValue, Snmp2cClient};
use tokio::sync::Semaphore;
use tracing::debug;

use crate::config::SnmpConfig;
use crate::netscan::{ScanDevice, ScanInterface};

// ── Groupe système (MIB-II, scalaires : suffixe .0) ──────────────────────────
const OID_SYS_DESCR: &str = "1.3.6.1.2.1.1.1.0";
const OID_SYS_UPTIME: &str = "1.3.6.1.2.1.1.3.0";
const OID_SYS_CONTACT: &str = "1.3.6.1.2.1.1.4.0";
const OID_SYS_NAME: &str = "1.3.6.1.2.1.1.5.0";
const OID_SYS_LOCATION: &str = "1.3.6.1.2.1.1.6.0";

// ── Colonnes ifTable (préfixes pour walk ; le dernier sous-id = ifIndex) ──────
const OID_IF_DESCR: &str = "1.3.6.1.2.1.2.2.1.2";
const OID_IF_MTU: &str = "1.3.6.1.2.1.2.2.1.4";
const OID_IF_SPEED: &str = "1.3.6.1.2.1.2.2.1.5";
const OID_IF_PHYS: &str = "1.3.6.1.2.1.2.2.1.6";
const OID_IF_ADMIN: &str = "1.3.6.1.2.1.2.2.1.7";
const OID_IF_OPER: &str = "1.3.6.1.2.1.2.2.1.8";
const OID_IF_IN_OCTETS: &str = "1.3.6.1.2.1.2.2.1.10";
const OID_IF_OUT_OCTETS: &str = "1.3.6.1.2.1.2.2.1.16";

/// Données SNMP collectées pour un appareil.
struct SnmpInfo {
    sys_descr: Option<String>,
    sys_name: Option<String>,
    sys_uptime_secs: Option<i64>,
    sys_location: Option<String>,
    sys_contact: Option<String>,
    interfaces: Vec<ScanInterface>,
}

/// Enrichit en place les appareils via SNMP (concurrence bornée par sémaphore).
pub async fn enrich(devices: &mut [ScanDevice], cfg: &SnmpConfig) {
    if devices.is_empty() {
        return;
    }
    let sem = Arc::new(Semaphore::new(cfg.concurrency.max(1)));
    let mut handles = Vec::with_capacity(devices.len());
    for d in devices.iter() {
        let ip = d.ip.clone();
        let cfg = cfg.clone();
        let sem = sem.clone();
        handles.push(tokio::spawn(async move {
            let _permit = sem.acquire_owned().await.ok()?;
            query_device(&ip, &cfg).await
        }));
    }

    let mut results = Vec::with_capacity(devices.len());
    for h in handles {
        results.push(h.await.ok().flatten());
    }

    let mut reachable = 0;
    for (d, res) in devices.iter_mut().zip(results) {
        if let Some(info) = res {
            apply(d, info);
            reachable += 1;
        }
    }
    debug!(
        "SNMP : {} appareil(s) joignable(s) sur {}",
        reachable,
        devices.len()
    );
}

/// Applique les infos SNMP à un appareil : SNMP fait autorité quand le scan TCP
/// n'a rien trouvé de mieux (hostname / os_guess).
fn apply(d: &mut ScanDevice, info: SnmpInfo) {
    d.snmp_reachable = true;
    if d.hostname.is_none() {
        d.hostname = info.sys_name.clone();
    }
    if d.os_guess.is_none() {
        d.os_guess = info.sys_descr.as_ref().map(|s| {
            s.lines()
                .next()
                .unwrap_or(s)
                .chars()
                .take(120)
                .collect::<String>()
        });
    }
    d.sys_descr = info.sys_descr;
    d.sys_name = info.sys_name;
    d.sys_uptime_secs = info.sys_uptime_secs;
    d.sys_location = info.sys_location;
    d.sys_contact = info.sys_contact;
    d.interfaces = info.interfaces;
}

/// Interroge un appareil ; `None` s'il ne répond pas (sysDescr sert de sonde).
async fn query_device(ip: &str, cfg: &SnmpConfig) -> Option<SnmpInfo> {
    let addr: IpAddr = ip.parse().ok()?;
    let target = SocketAddr::new(addr, cfg.port);
    let timeout = Duration::from_millis(cfg.timeout_ms.max(100));
    let client = Snmp2cClient::new(
        target,
        cfg.community.clone().into_bytes(),
        None,
        Some(timeout),
        cfg.retries,
    )
    .await
    .ok()?;

    // sysDescr = sonde de joignabilité : échec ⇒ on abandonne cet appareil.
    let sys_descr = get_string(&client, OID_SYS_DESCR).await?;

    let sys_name = get_string(&client, OID_SYS_NAME).await;
    let sys_location = get_string(&client, OID_SYS_LOCATION).await;
    let sys_contact = get_string(&client, OID_SYS_CONTACT).await;
    let sys_uptime_secs = get_uptime_secs(&client, OID_SYS_UPTIME).await;

    let interfaces = if cfg.collect_interfaces {
        collect_interfaces(&client).await
    } else {
        Vec::new()
    };

    Some(SnmpInfo {
        sys_descr: Some(sys_descr),
        sys_name,
        sys_uptime_secs,
        sys_location,
        sys_contact,
        interfaces,
    })
}

fn oid(s: &str) -> Option<ObjectIdentifier> {
    s.parse().ok()
}

/// GET d'une chaîne OCTET STRING ; `None` si absent ou type inattendu/vide.
async fn get_string(client: &Snmp2cClient, oid_str: &str) -> Option<String> {
    let o = oid(oid_str)?;
    val_string(&client.get(o).await.ok()?)
}

/// GET de sysUpTime (TimeTicks = centièmes de seconde) → secondes.
async fn get_uptime_secs(client: &Snmp2cClient, oid_str: &str) -> Option<i64> {
    let o = oid(oid_str)?;
    val_i64(&client.get(o).await.ok()?).map(|t| t / 100)
}

/// Parcourt l'ifTable (un walk par colonne) et reconstruit les interfaces.
async fn collect_interfaces(client: &Snmp2cClient) -> Vec<ScanInterface> {
    let descr = walk_column(client, OID_IF_DESCR).await;
    let mtu = walk_column(client, OID_IF_MTU).await;
    let speed = walk_column(client, OID_IF_SPEED).await;
    let phys = walk_column(client, OID_IF_PHYS).await;
    let admin = walk_column(client, OID_IF_ADMIN).await;
    let oper = walk_column(client, OID_IF_OPER).await;
    let in_oct = walk_column(client, OID_IF_IN_OCTETS).await;
    let out_oct = walk_column(client, OID_IF_OUT_OCTETS).await;

    let mut indices: BTreeSet<i32> = BTreeSet::new();
    for m in [
        &descr, &mtu, &speed, &phys, &admin, &oper, &in_oct, &out_oct,
    ] {
        indices.extend(m.keys().copied());
    }

    indices
        .into_iter()
        .map(|idx| ScanInterface {
            if_index: idx,
            name: descr.get(&idx).and_then(val_string),
            mac: phys.get(&idx).and_then(val_mac),
            admin_up: admin.get(&idx).and_then(val_i64).map(|n| n == 1),
            oper_up: oper.get(&idx).and_then(val_i64).map(|n| n == 1),
            speed_bps: speed.get(&idx).and_then(val_i64),
            mtu: mtu.get(&idx).and_then(val_i64).map(|n| n as i32),
            in_octets: in_oct.get(&idx).and_then(val_i64),
            out_octets: out_oct.get(&idx).and_then(val_i64),
        })
        .collect()
}

/// Walk d'une colonne ifTable → map indexée par ifIndex (dernier sous-id de l'OID).
async fn walk_column(client: &Snmp2cClient, base_str: &str) -> BTreeMap<i32, ObjectValue> {
    let mut out = BTreeMap::new();
    let Some(base) = oid(base_str) else {
        return out;
    };
    let Ok(map) = client.walk(base).await else {
        return out;
    };
    for (k, v) in map {
        if let Some(idx) = k.as_slice().last() {
            out.insert(*idx as i32, v);
        }
    }
    out
}

// ── Extracteurs de valeurs SNMP ───────────────────────────────────────────────

fn val_i64(v: &ObjectValue) -> Option<i64> {
    match v {
        ObjectValue::Integer(i) => Some(*i as i64),
        ObjectValue::Counter32(u) | ObjectValue::Unsigned32(u) | ObjectValue::TimeTicks(u) => {
            Some(*u as i64)
        }
        ObjectValue::Counter64(u) => Some(*u as i64),
        _ => None,
    }
}

fn val_string(v: &ObjectValue) -> Option<String> {
    match v {
        ObjectValue::String(b) => {
            let s = String::from_utf8_lossy(b).trim().to_string();
            if s.is_empty() {
                None
            } else {
                Some(s)
            }
        }
        _ => None,
    }
}

/// ifPhysAddress (6 octets) → MAC `AA:BB:CC:DD:EE:FF`.
fn val_mac(v: &ObjectValue) -> Option<String> {
    match v {
        ObjectValue::String(b) if b.len() == 6 => Some(
            b.iter()
                .map(|x| format!("{:02X}", x))
                .collect::<Vec<_>>()
                .join(":"),
        ),
        _ => None,
    }
}
