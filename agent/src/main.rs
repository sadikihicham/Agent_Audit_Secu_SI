mod collector;
mod config;
mod flows;
mod netscan;
mod queue;
mod snmp;
mod state;
mod transport;

use std::path::PathBuf;
use std::time::Duration;

use anyhow::{Context, Result};
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
    info!(
        "Config chargée : api_url={} interval={}s",
        config.api_url, config.interval_secs
    );

    let mut client_builder = reqwest::Client::builder().timeout(Duration::from_secs(15));
    if let Some(ca_cert_path) = &config.ca_cert_path {
        let pem = std::fs::read(ca_cert_path)
            .with_context(|| format!("Lecture ca_cert_path {:?}", ca_cert_path))?;
        let cert = reqwest::Certificate::from_pem(&pem)
            .with_context(|| format!("Parsing PEM invalide dans ca_cert_path {:?}", ca_cert_path))?;
        client_builder = client_builder.add_root_certificate(cert);
        info!("CA supplémentaire chargée depuis {:?} (scopée à ce client HTTP)", ca_cert_path);
    }
    let client = client_builder.build()?;

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

    // ── Scan réseau (tâche de fond séparée, opt-in) ───────────────────────────
    if config.scan.enabled {
        info!(
            "Scan réseau activé (interval={}s, {} CIDR autorisé(s))",
            config.scan.interval_secs,
            config.scan.allowlist.len()
        );
        tokio::spawn(scan_loop(client.clone(), config.clone(), state.clone()));
    } else {
        info!("Scan réseau désactivé (scan.enabled=false)");
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
            warn!(
                "File offline pleine — suppression de {} échantillon(s) ancien(s)",
                drop
            );
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

/// Boucle de scan réseau périodique (premier scan immédiat, puis tous les
/// `scan.interval_secs`). Best-effort : un échec d'envoi est simplement loggé.
async fn scan_loop(client: reqwest::Client, config: Config, state: AgentState) {
    let mut interval = time::interval(Duration::from_secs(config.scan.interval_secs.max(30)));
    interval.set_missed_tick_behavior(time::MissedTickBehavior::Delay);

    loop {
        interval.tick().await;

        let mut devices = netscan::run_scan(&config.scan).await;
        info!(
            "Scan réseau terminé : {} appareil(s) découvert(s)",
            devices.len()
        );

        // Enrichissement SNMP (opt-in) : groupe système + interfaces (ifTable).
        if config.snmp.enabled {
            snmp::enrich(&mut devices, &config.snmp).await;
        }

        let cidr = if config.scan.allowlist.is_empty() {
            None
        } else {
            Some(config.scan.allowlist.join(","))
        };

        if let Err(e) = transport::send_scan(&client, &config, &state, &devices, cidr).await {
            warn!("Envoi scan échoué : {}", e);
        }

        // Surveillance « out » : flux sortants de l'hôte → détection d'intrusion.
        let host_flows = flows::collect_flows();
        info!("{} flux sortant(s) collecté(s)", host_flows.len());
        if let Err(e) = transport::send_flows(&client, &config, &state, &host_flows).await {
            warn!("Envoi flux échoué : {}", e);
        }
    }
}
