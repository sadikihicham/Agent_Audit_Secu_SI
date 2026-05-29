mod collector;
mod config;
mod queue;
mod state;
mod transport;

use std::path::PathBuf;
use std::time::Duration;

use anyhow::Result;
use tokio::time;
use tracing::{error, info, warn};

use collector::Collector;
use config::Config;
use state::AgentState;

#[tokio::main]
async fn main() -> Result<()> {
    // Logging : RUST_LOG=debug pour le verbose, défaut = info.
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "guardianops_agent=info".parse().unwrap()),
        )
        .init();

    let config_path = PathBuf::from("agent.toml");
    let state_path = PathBuf::from("agent_state.toml");
    let queue_path = PathBuf::from("queue.json");

    let config = Config::load(&config_path)?;
    info!("Config chargée : api_url={} interval={}s", config.api_url, config.interval_secs);

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()?;

    // ── Enrôlement ──────────────────────────────────────────────────────────
    let state = match AgentState::load(&state_path)? {
        Some(s) => {
            info!("Déjà enrôlé : machine_id={}", s.machine_id);
            s
        }
        None => {
            let enroll_token = config.enroll_token.as_deref().ok_or_else(|| {
                anyhow::anyhow!(
                    "Pas encore enrôlé.\n\
                     Ajoutez 'enroll_token = \"<token>\"' dans agent.toml\n\
                     (le token est généré via POST /machines dans l'API)."
                )
            })?;

            info!("Enrôlement en cours…");
            let (hostname, os) = collector::system_info();
            let resp = transport::enroll(&client, &config, enroll_token, hostname, os).await?;
            let s = AgentState {
                machine_id: resp.machine_id,
                agent_token: resp.agent_token,
            };
            s.save(&state_path)?;
            info!("Enrôlé avec succès : machine_id={}", s.machine_id);
            s
        }
    };

    // ── Heartbeat initial ───────────────────────────────────────────────────
    if let Err(e) = transport::send_heartbeat(&client, &config, &state).await {
        warn!("Heartbeat initial échoué : {}", e);
    } else {
        info!("Heartbeat initial envoyé");
    }

    // ── Boucle principale ───────────────────────────────────────────────────
    let mut collector = Collector::new();
    let mut interval = time::interval(Duration::from_secs(config.interval_secs));
    interval.set_missed_tick_behavior(time::MissedTickBehavior::Delay);

    info!(
        "Agent démarré (machine_id={}, interval={}s)",
        state.machine_id, config.interval_secs
    );

    loop {
        interval.tick().await;

        let sample = collector.collect();
        info!(
            "Collecte : cpu={:.1}% mem={:.1}% disk={:.1}% uptime={}s",
            sample.cpu_pct, sample.mem_pct, sample.disk_pct, sample.uptime_s
        );

        // Charger la file locale + ajouter l'échantillon courant.
        let mut batch = queue::load(&queue_path);
        if batch.len() >= config.max_queue_size {
            let drop = batch.len() - config.max_queue_size + 1;
            warn!("File offline pleine — suppression de {} échantillon(s) ancien(s)", drop);
            batch.drain(..drop);
        }
        batch.push(sample);

        match transport::send_metrics(&client, &config, &state, &batch).await {
            Ok(()) => {
                info!("Envoi OK ({} échantillon(s))", batch.len());
                queue::clear(&queue_path);
            }
            Err(e) => {
                error!(
                    "Envoi échoué : {} — {} échantillon(s) mis en file",
                    e,
                    batch.len()
                );
                if let Err(qe) = queue::save(&queue_path, &batch) {
                    error!("Impossible d'écrire la file offline : {}", qe);
                }
            }
        }
    }
}
