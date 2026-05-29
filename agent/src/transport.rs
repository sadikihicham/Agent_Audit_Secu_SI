use anyhow::{bail, Context, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::warn;

use crate::collector::MetricSample;
use crate::config::Config;
use crate::state::AgentState;

// ── Enrôlement ────────────────────────────────────────────────────────────────

#[derive(Serialize)]
struct EnrollRequest {
    enroll_token: String,
    hostname: String,
    os: Option<String>,
    agent_version: Option<String>,
}

#[derive(Deserialize)]
pub struct EnrollResponse {
    pub machine_id: u64,
    pub agent_token: String,
}

pub async fn enroll(
    client: &Client,
    config: &Config,
    enroll_token: &str,
    hostname: String,
    os: Option<String>,
) -> Result<EnrollResponse> {
    let body = EnrollRequest {
        enroll_token: enroll_token.to_owned(),
        hostname,
        os,
        agent_version: Some(env!("CARGO_PKG_VERSION").to_owned()),
    };
    let resp = client
        .post(format!("{}/agents/enroll", config.api_url))
        .json(&body)
        .send()
        .await
        .context("Requête d'enrôlement")?;

    if !resp.status().is_success() {
        bail!("Enrôlement refusé : HTTP {}", resp.status());
    }
    resp.json::<EnrollResponse>()
        .await
        .context("Parsing réponse enrôlement")
}

// ── Ingestion ─────────────────────────────────────────────────────────────────

#[derive(Serialize)]
struct IngestRequest<'a> {
    samples: &'a [MetricSample],
}

/// Envoie un batch de métriques avec retry exponentiel (3 tentatives max).
pub async fn send_metrics(
    client: &Client,
    config: &Config,
    state: &AgentState,
    samples: &[MetricSample],
) -> Result<()> {
    let body = IngestRequest { samples };
    let mut delay = Duration::from_secs(1);

    for attempt in 1..=3u32 {
        let resp = client
            .post(format!("{}/ingest/metrics", config.api_url))
            .bearer_auth(&state.agent_token)
            .json(&body)
            .send()
            .await;

        match resp {
            Ok(r) if r.status().is_success() => return Ok(()),
            Ok(r) => {
                let status = r.status();
                if attempt < 3 {
                    warn!("Tentative {}/3 : HTTP {} — retry dans {:?}", attempt, status, delay);
                    tokio::time::sleep(delay).await;
                    delay *= 2;
                } else {
                    bail!("Envoi métriques échoué après 3 tentatives : HTTP {}", status);
                }
            }
            Err(e) => {
                if attempt < 3 {
                    warn!("Tentative {}/3 : {} — retry dans {:?}", attempt, e, delay);
                    tokio::time::sleep(delay).await;
                    delay *= 2;
                } else {
                    return Err(e).context("Envoi métriques échoué après 3 tentatives");
                }
            }
        }
    }
    unreachable!()
}

/// Heartbeat simple (ne plante pas si le serveur est injoignable).
pub async fn send_heartbeat(
    client: &Client,
    config: &Config,
    state: &AgentState,
) -> Result<()> {
    let resp = client
        .post(format!("{}/ingest/heartbeat", config.api_url))
        .bearer_auth(&state.agent_token)
        .send()
        .await
        .context("Requête heartbeat")?;

    if !resp.status().is_success() {
        bail!("Heartbeat refusé : HTTP {}", resp.status());
    }
    Ok(())
}
