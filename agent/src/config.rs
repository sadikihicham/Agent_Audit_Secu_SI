use anyhow::{Context, Result};
use serde::Deserialize;
use std::path::Path;

#[derive(Debug, Deserialize, Clone)]
pub struct Config {
    /// URL de l'API GuardianOps (sans slash final).
    #[serde(default = "default_api_url")]
    pub api_url: String,

    /// Token d'enrôlement (usage unique, fourni par l'admin via POST /machines).
    /// Supprimez-le du fichier après le premier enrôlement.
    pub enroll_token: Option<String>,

    /// Intervalle de collecte + envoi des métriques (secondes).
    #[serde(default = "default_interval")]
    pub interval_secs: u64,

    /// Nombre maximum d'échantillons conservés dans la file offline.
    #[serde(default = "default_max_queue")]
    pub max_queue_size: usize,

    /// Configuration du scan réseau (section [scan]).
    #[serde(default)]
    pub scan: ScanConfig,

    /// Configuration de l'enrichissement SNMP (section [snmp]).
    #[serde(default)]
    pub snmp: SnmpConfig,
}

/// Configuration de l'enrichissement SNMP (v2c, lecture seule).
///
/// Après le scan TCP, on interroge en UDP 161 les appareils découverts pour
/// récupérer le groupe système (sysDescr/sysName/sysUpTime/…) et, en option, la
/// table des interfaces (ifTable). Opt-in : désactivé par défaut.
#[derive(Debug, Deserialize, Clone)]
pub struct SnmpConfig {
    /// Active l'enrichissement SNMP après le scan (désactivé par défaut — opt-in).
    #[serde(default)]
    pub enabled: bool,

    /// Communauté SNMP v2c (lecture seule).
    #[serde(default = "default_snmp_community")]
    pub community: String,

    /// Port SNMP de l'agent distant.
    #[serde(default = "default_snmp_port")]
    pub port: u16,

    /// Timeout par requête SNMP (millisecondes).
    #[serde(default = "default_snmp_timeout_ms")]
    pub timeout_ms: u64,

    /// Nombre de tentatives supplémentaires en cas de non-réponse.
    #[serde(default = "default_snmp_retries")]
    pub retries: usize,

    /// Collecte aussi la table des interfaces (ifTable). Plus lourd.
    #[serde(default = "default_true")]
    pub collect_interfaces: bool,

    /// Nombre d'appareils interrogés en parallèle.
    #[serde(default = "default_snmp_concurrency")]
    pub concurrency: usize,
}

fn default_snmp_community() -> String {
    "public".to_string()
}
fn default_snmp_port() -> u16 {
    161
}
fn default_snmp_timeout_ms() -> u64 {
    1500
}
fn default_snmp_retries() -> usize {
    1
}
fn default_true() -> bool {
    true
}
fn default_snmp_concurrency() -> usize {
    16
}

impl Default for SnmpConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            community: default_snmp_community(),
            port: default_snmp_port(),
            timeout_ms: default_snmp_timeout_ms(),
            retries: default_snmp_retries(),
            collect_interfaces: true,
            concurrency: default_snmp_concurrency(),
        }
    }
}

/// Configuration du scan réseau (Phase A : découverte d'appareils).
#[derive(Debug, Deserialize, Clone)]
pub struct ScanConfig {
    /// Active le scan réseau périodique (désactivé par défaut — opt-in).
    #[serde(default)]
    pub enabled: bool,

    /// Plages autorisées (CIDR). Refus par défaut si vide ; seules les plages
    /// recoupant un sous-réseau local de l'hôte sont effectivement scannées.
    #[serde(default)]
    pub allowlist: Vec<String>,

    /// Intervalle entre deux scans complets (secondes).
    #[serde(default = "default_scan_interval")]
    pub interval_secs: u64,

    /// Ports sondés pour la présence + l'indice de type (Phase A : liveness léger).
    #[serde(default = "default_probe_ports")]
    pub probe_ports: Vec<u16>,

    /// Ports scannés en détail (avec bannière) sur les hôtes vivants (Phase B : top-100).
    #[serde(default = "default_scan_ports")]
    pub scan_ports: Vec<u16>,

    /// Timeout par tentative de connexion TCP (millisecondes).
    #[serde(default = "default_scan_timeout_ms")]
    pub timeout_ms: u64,

    /// Nombre de connexions simultanées maximum pendant le balayage.
    #[serde(default = "default_scan_concurrency")]
    pub concurrency: usize,
}

fn default_scan_interval() -> u64 {
    300
}
fn default_probe_ports() -> Vec<u16> {
    vec![22, 80, 443, 445, 3389, 53, 9100, 515, 631, 8080, 8443, 5353]
}
/// Top-100 ports TCP courants (inspiré de la liste nmap).
fn default_scan_ports() -> Vec<u16> {
    vec![
        7, 20, 21, 22, 23, 25, 26, 37, 53, 79, 80, 81, 88, 106, 110, 111, 113, 119, 135, 139, 143,
        144, 161, 179, 199, 389, 427, 443, 444, 445, 465, 513, 514, 515, 543, 544, 548, 554, 587,
        631, 646, 873, 990, 993, 995, 1025, 1026, 1027, 1433, 1521, 1720, 1723, 2000, 2049, 2121,
        2717, 3000, 3128, 3306, 3389, 3986, 5000, 5009, 5051, 5060, 5101, 5190, 5357, 5432, 5631,
        5666, 5800, 5900, 5901, 6000, 6001, 6379, 6646, 7070, 8000, 8008, 8009, 8080, 8081, 8443,
        8888, 9100, 9200, 9999, 10000, 11211, 27017, 32768, 49152, 49153, 49154, 49156, 49157,
    ]
}
fn default_scan_timeout_ms() -> u64 {
    400
}
fn default_scan_concurrency() -> usize {
    256
}

impl Default for ScanConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            allowlist: Vec::new(),
            interval_secs: default_scan_interval(),
            probe_ports: default_probe_ports(),
            scan_ports: default_scan_ports(),
            timeout_ms: default_scan_timeout_ms(),
            concurrency: default_scan_concurrency(),
        }
    }
}

fn default_api_url() -> String {
    "http://localhost:8800".to_string()
}
fn default_interval() -> u64 {
    30
}
fn default_max_queue() -> usize {
    1000
}

impl Default for Config {
    fn default() -> Self {
        Self {
            api_url: default_api_url(),
            enroll_token: None,
            interval_secs: default_interval(),
            max_queue_size: default_max_queue(),
            scan: ScanConfig::default(),
            snmp: SnmpConfig::default(),
        }
    }
}

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        if path.exists() {
            let src = std::fs::read_to_string(path)
                .with_context(|| format!("Lecture config {:?}", path))?;
            toml::from_str(&src).context("Parsing du fichier de config")
        } else {
            Ok(Self::default())
        }
    }
}
