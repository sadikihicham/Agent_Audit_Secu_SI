//! Enrichissement SNMP des appareils découverts — v2c (communauté) **et v3** (USM
//! auth/priv), via la crate `snmp2` (async tokio).
//!
//! Après le scan TCP, on interroge en UDP 161 chaque appareil pour récupérer :
//!  - le **groupe système** (MIB-II) : sysDescr, sysName, sysUpTime, sysLocation,
//!    sysContact — infos fiables que le scan TCP ne peut que deviner ;
//!  - en option, la **table des interfaces** (ifTable) : nom, statut, débit,
//!    octets in/out par interface réseau.
//!
//! Opt-in (`[snmp] enabled = true`) et best-effort : un appareil injoignable est
//! laissé tel quel (`snmp_reachable = false`). En v3, l'engine ID est découvert
//! automatiquement (`init`), et un `Error::AuthUpdated` (resynchro horloge USM)
//! provoque une nouvelle tentative.

use std::collections::{BTreeMap, BTreeSet};
use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

use snmp2::{v3, AsyncSession, Error as SnmpError, Oid, Value};
use tokio::sync::Semaphore;
use tokio::time::timeout;
use tracing::debug;

use crate::config::SnmpConfig;
use crate::netscan::{ScanDevice, ScanInterface};

// ── Groupe système (MIB-II, scalaires : suffixe .0) ──────────────────────────
const OID_SYS_DESCR: &[u64] = &[1, 3, 6, 1, 2, 1, 1, 1, 0];
const OID_SYS_UPTIME: &[u64] = &[1, 3, 6, 1, 2, 1, 1, 3, 0];
const OID_SYS_CONTACT: &[u64] = &[1, 3, 6, 1, 2, 1, 1, 4, 0];
const OID_SYS_NAME: &[u64] = &[1, 3, 6, 1, 2, 1, 1, 5, 0];
const OID_SYS_LOCATION: &[u64] = &[1, 3, 6, 1, 2, 1, 1, 6, 0];

// ── Colonnes ifTable (préfixes pour getbulk ; dernier sous-id = ifIndex) ──────
const OID_IF_DESCR: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 2];
const OID_IF_MTU: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 4];
const OID_IF_SPEED: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 5];
const OID_IF_PHYS: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 6];
const OID_IF_ADMIN: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 7];
const OID_IF_OPER: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 8];
const OID_IF_IN_OCTETS: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 10];
const OID_IF_OUT_OCTETS: &[u64] = &[1, 3, 6, 1, 2, 1, 2, 2, 1, 16];

/// Borne haute du getbulk par colonne (nb d'interfaces couvertes en une requête).
const BULK_MAX_REPETITIONS: u32 = 64;

/// Valeur SNMP extraite et possédée (détachée du buffer emprunté du PDU).
enum OwnedValue {
    Int(i64),
    Bytes(Vec<u8>),
}

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
        "SNMP ({}) : {} appareil(s) joignable(s) sur {}",
        cfg.version,
        reachable,
        devices.len()
    );
}

/// Applique les infos SNMP : SNMP fait autorité quand le scan TCP n'a rien de mieux.
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

/// Ouvre une session (v2c ou v3) ; pour v3, découverte d'engine ID via `init`.
async fn open_session(ip: &str, cfg: &SnmpConfig, dur: Duration) -> Option<AsyncSession> {
    let addr: IpAddr = ip.parse().ok()?;
    let target = SocketAddr::new(addr, cfg.port);

    if cfg.version.eq_ignore_ascii_case("v3") {
        let security = build_security(cfg);
        let mut sess = AsyncSession::new_v3(target, 0, security).await.ok()?;
        // Découverte d'engine ID + resynchro USM (best-effort).
        let _ = timeout(dur, sess.init()).await;
        Some(sess)
    } else {
        AsyncSession::new_v2c(target, cfg.community.as_bytes(), 0)
            .await
            .ok()
    }
}

/// Construit les paramètres de sécurité USM v3 à partir de la config.
fn build_security(cfg: &SnmpConfig) -> v3::Security {
    let auth_proto = match cfg.auth_protocol.to_ascii_lowercase().as_str() {
        "md5" => v3::AuthProtocol::Md5,
        "sha224" => v3::AuthProtocol::Sha224,
        "sha256" => v3::AuthProtocol::Sha256,
        "sha384" => v3::AuthProtocol::Sha384,
        "sha512" => v3::AuthProtocol::Sha512,
        _ => v3::AuthProtocol::Sha1,
    };
    let cipher = match cfg.cipher.to_ascii_lowercase().as_str() {
        "des" => v3::Cipher::Des,
        _ => v3::Cipher::Aes128,
    };

    let security = v3::Security::new(cfg.security_name.as_bytes(), cfg.auth_pass.as_bytes())
        .with_auth_protocol(auth_proto);

    if cfg.auth_pass.is_empty() {
        security.with_auth(v3::Auth::NoAuthNoPriv)
    } else if cfg.priv_pass.is_empty() {
        security.with_auth(v3::Auth::AuthNoPriv)
    } else {
        security.with_auth(v3::Auth::AuthPriv {
            cipher,
            privacy_password: cfg.priv_pass.clone().into_bytes(),
        })
    }
}

/// Interroge un appareil ; `None` s'il ne répond pas (sysDescr sert de sonde).
async fn query_device(ip: &str, cfg: &SnmpConfig) -> Option<SnmpInfo> {
    let dur = Duration::from_millis(cfg.timeout_ms.max(100));
    let mut sess = open_session(ip, cfg, dur).await?;

    // sysDescr = sonde de joignabilité : échec ⇒ on abandonne cet appareil.
    let sys_descr = get_string(&mut sess, OID_SYS_DESCR, dur, cfg.retries).await?;

    let sys_name = get_string(&mut sess, OID_SYS_NAME, dur, cfg.retries).await;
    let sys_location = get_string(&mut sess, OID_SYS_LOCATION, dur, cfg.retries).await;
    let sys_contact = get_string(&mut sess, OID_SYS_CONTACT, dur, cfg.retries).await;
    let sys_uptime_secs = get_uptime_secs(&mut sess, dur, cfg.retries).await;

    let interfaces = if cfg.collect_interfaces {
        collect_interfaces(&mut sess, dur).await
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

/// GET scalaire → valeur possédée, avec timeout + une nouvelle tentative sur
/// `AuthUpdated` (resynchro USM v3). `None` si absent/timeout/type inattendu.
async fn get_scalar(
    sess: &mut AsyncSession,
    oid_comps: &[u64],
    dur: Duration,
    retries: usize,
) -> Option<OwnedValue> {
    let oid = Oid::from(oid_comps).ok()?;
    for _ in 0..=retries.max(1) {
        match timeout(dur, sess.get(&oid)).await {
            Ok(Ok(mut pdu)) => return pdu.varbinds.next().map(|(_o, v)| to_owned(&v)),
            Ok(Err(SnmpError::AuthUpdated)) => continue, // resynchro v3 → on rejoue
            _ => return None,
        }
    }
    None
}

async fn get_string(
    sess: &mut AsyncSession,
    oid_comps: &[u64],
    dur: Duration,
    retries: usize,
) -> Option<String> {
    match get_scalar(sess, oid_comps, dur, retries).await? {
        OwnedValue::Bytes(b) => {
            let s = String::from_utf8_lossy(&b).trim().to_string();
            if s.is_empty() {
                None
            } else {
                Some(s)
            }
        }
        OwnedValue::Int(_) => None,
    }
}

/// sysUpTime (TimeTicks = centièmes de seconde) → secondes.
async fn get_uptime_secs(sess: &mut AsyncSession, dur: Duration, retries: usize) -> Option<i64> {
    match get_scalar(sess, OID_SYS_UPTIME, dur, retries).await? {
        OwnedValue::Int(t) => Some(t / 100),
        OwnedValue::Bytes(_) => None,
    }
}

/// Parcourt l'ifTable (un getbulk par colonne) et reconstruit les interfaces.
async fn collect_interfaces(sess: &mut AsyncSession, dur: Duration) -> Vec<ScanInterface> {
    let descr = walk_column(sess, OID_IF_DESCR, dur).await;
    let mtu = walk_column(sess, OID_IF_MTU, dur).await;
    let speed = walk_column(sess, OID_IF_SPEED, dur).await;
    let phys = walk_column(sess, OID_IF_PHYS, dur).await;
    let admin = walk_column(sess, OID_IF_ADMIN, dur).await;
    let oper = walk_column(sess, OID_IF_OPER, dur).await;
    let in_oct = walk_column(sess, OID_IF_IN_OCTETS, dur).await;
    let out_oct = walk_column(sess, OID_IF_OUT_OCTETS, dur).await;

    let mut indices: BTreeSet<i64> = BTreeSet::new();
    for m in [
        &descr, &mtu, &speed, &phys, &admin, &oper, &in_oct, &out_oct,
    ] {
        indices.extend(m.keys().copied());
    }

    indices
        .into_iter()
        .map(|idx| ScanInterface {
            if_index: idx as i32,
            name: descr.get(&idx).and_then(as_string),
            mac: phys.get(&idx).and_then(as_mac),
            admin_up: admin.get(&idx).and_then(as_i64).map(|n| n == 1),
            oper_up: oper.get(&idx).and_then(as_i64).map(|n| n == 1),
            speed_bps: speed.get(&idx).and_then(as_i64),
            mtu: mtu.get(&idx).and_then(as_i64).map(|n| n as i32),
            in_octets: in_oct.get(&idx).and_then(as_i64),
            out_octets: out_oct.get(&idx).and_then(as_i64),
        })
        .collect()
}

/// getbulk d'une colonne ifTable → map ifIndex (dernier sous-id) → valeur possédée.
async fn walk_column(
    sess: &mut AsyncSession,
    base_comps: &[u64],
    dur: Duration,
) -> BTreeMap<i64, OwnedValue> {
    let mut out = BTreeMap::new();
    let Ok(base) = Oid::from(base_comps) else {
        return out;
    };
    let pdu = match timeout(dur, sess.getbulk(&[&base], 0, BULK_MAX_REPETITIONS)).await {
        Ok(Ok(p)) => p,
        _ => return out,
    };
    for (oid, val) in pdu.varbinds {
        // Composants numériques de l'OID renvoyé.
        let Some(comps) = oid.iter().map(|it| it.collect::<Vec<u64>>()) else {
            continue;
        };
        // Hors du sous-arbre de la colonne → ignorer (getbulk déborde sur la suivante).
        if !comps.starts_with(base_comps) {
            continue;
        }
        if let Some(&idx) = comps.last() {
            out.insert(idx as i64, to_owned(&val));
        }
    }
    out
}

// ── Conversions de valeurs ────────────────────────────────────────────────────

fn to_owned(v: &Value) -> OwnedValue {
    match v {
        Value::Integer(i) => OwnedValue::Int(*i),
        Value::Counter32(u) | Value::Unsigned32(u) | Value::Timeticks(u) => {
            OwnedValue::Int(*u as i64)
        }
        Value::Counter64(u) => OwnedValue::Int(*u as i64),
        Value::OctetString(b) => OwnedValue::Bytes(b.to_vec()),
        Value::Opaque(b) => OwnedValue::Bytes(b.to_vec()),
        _ => OwnedValue::Bytes(Vec::new()),
    }
}

fn as_i64(v: &OwnedValue) -> Option<i64> {
    match v {
        OwnedValue::Int(i) => Some(*i),
        OwnedValue::Bytes(_) => None,
    }
}

fn as_string(v: &OwnedValue) -> Option<String> {
    match v {
        OwnedValue::Bytes(b) if !b.is_empty() => {
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
fn as_mac(v: &OwnedValue) -> Option<String> {
    match v {
        OwnedValue::Bytes(b) if b.len() == 6 => Some(
            b.iter()
                .map(|x| format!("{:02X}", x))
                .collect::<Vec<_>>()
                .join(":"),
        ),
        _ => None,
    }
}
