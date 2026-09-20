use ocr_producer_rust::{app, redis_client_from_env, AppState};
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

    let state = Arc::new(AppState {
        redis_client: redis_client_from_env(),
    });
    let router = app(state);

    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], 5000));
    tracing::info!(%addr, "Rust Producer API listening");

    axum::Server::bind(&addr)
        .serve(router.into_make_service())
        .await
        .unwrap();
}
