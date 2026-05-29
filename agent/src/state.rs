use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::Path;

/// Persisté après enrôlement — ne jamais committer ce fichier.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AgentState {
    pub machine_id: u64,
    pub agent_token: String,
}

impl AgentState {
    pub fn load(path: &Path) -> Result<Option<Self>> {
        if !path.exists() {
            return Ok(None);
        }
        let src = std::fs::read_to_string(path)?;
        Ok(Some(toml::from_str(&src)?))
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        std::fs::write(path, toml::to_string(self)?)?;
        Ok(())
    }
}
