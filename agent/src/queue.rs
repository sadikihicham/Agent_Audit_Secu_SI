/// File offline : liste JSON des MetricSample non encore envoyés.
/// Écriture atomique (write + rename) pour éviter la corruption.
use anyhow::Result;
use std::path::Path;

use crate::collector::MetricSample;

pub fn load(path: &Path) -> Vec<MetricSample> {
    if !path.exists() {
        return vec![];
    }
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save(path: &Path, samples: &[MetricSample]) -> Result<()> {
    if samples.is_empty() {
        clear(path);
        return Ok(());
    }
    // Écriture atomique via fichier temporaire + rename.
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, serde_json::to_string(samples)?)?;
    std::fs::rename(&tmp, path)?;
    Ok(())
}

pub fn clear(path: &Path) {
    let _ = std::fs::remove_file(path);
}
