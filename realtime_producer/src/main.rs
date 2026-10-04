use ocr_producer_rust::{app, redis_client_from_env, AppState, Config};
use std::sync::Arc;

#[tokio::main]
async fn main() {
    let json_logs = std::env::var("LOG_FORMAT")
        .map(|v| v.eq_ignore_ascii_case("json"))
        .unwrap_or(false);
    if json_logs {
        tracing_subscriber::fmt().json().init();
    } else {
        tracing_subscriber::fmt().init();
    }

    let config = Config::from_env();
    tracing::info!(?config, "configuration");
    let state = Arc::new(AppState::new(redis_client_from_env(), config));
    let router = app(state);

    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], 5000));
    tracing::info!(%addr, "Rust Producer API listening");

    axum::Server::bind(&addr)
        .serve(router.into_make_service())
        .await
        .unwrap();
}
