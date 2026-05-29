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
