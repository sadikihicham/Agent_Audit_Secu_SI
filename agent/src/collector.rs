use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sysinfo::{Disks, System};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricSample {
    pub ts: DateTime<Utc>,
    /// Pourcentage CPU global (0-100).
    pub cpu_pct: f64,
    /// Pourcentage RAM utilisée (0-100).
    pub mem_pct: f64,
    /// Pourcentage espace disque utilisé — tous les volumes agrégés (0-100).
    pub disk_pct: f64,
    /// Uptime de la machine en secondes.
    pub uptime_s: u64,
}

pub struct Collector {
    sys: System,
}

impl Collector {
    /// Crée le collecteur et effectue une première lecture CPU pour établir la baseline.
    pub fn new() -> Self {
        let mut sys = System::new();
        sys.refresh_cpu_usage(); // baseline t=0 pour le calcul de delta
        Self { sys }
    }

    /// Collecte un échantillon. CPU = delta depuis la dernière lecture (précis si ≥ MINIMUM_CPU_UPDATE_INTERVAL).
    pub fn collect(&mut self) -> MetricSample {
        self.sys.refresh_cpu_usage();
        self.sys.refresh_memory();

        let cpu_pct = self.sys.global_cpu_usage() as f64;

        let total_mem = self.sys.total_memory();
        let mem_pct = if total_mem > 0 {
            (self.sys.used_memory() as f64 / total_mem as f64) * 100.0
        } else {
            0.0
        };

        let disks = Disks::new_with_refreshed_list();
        let total_disk: u64 = disks.iter().map(|d| d.total_space()).sum();
        let avail_disk: u64 = disks.iter().map(|d| d.available_space()).sum();
        let disk_pct = if total_disk > 0 {
            ((total_disk - avail_disk) as f64 / total_disk as f64) * 100.0
        } else {
            0.0
        };

        MetricSample {
            ts: Utc::now(),
            cpu_pct: (cpu_pct * 10.0).round() / 10.0,
            mem_pct: (mem_pct * 10.0).round() / 10.0,
            disk_pct: (disk_pct * 10.0).round() / 10.0,
            uptime_s: System::uptime(),
        }
    }
}

/// Collecte les métadonnées système pour l'enrôlement.
pub fn system_info() -> (String, Option<String>) {
    let hostname = System::host_name().unwrap_or_else(|| "unknown".to_string());
    let os = System::long_os_version()
        .or_else(System::name)
        .map(|s| s.trim().to_string());
    (hostname, os)
}
