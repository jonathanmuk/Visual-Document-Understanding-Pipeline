use ocr_producer_rust::{app, AppState};
use std::sync::Arc;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let redis_host = std::env::var("REDIS_HOST").unwrap_or_else(|_| "ocr-redis-service".to_string());
    let redis_port = std::env::var("REDIS_PORT").unwrap_or_else(|_| "6379".to_string());
    let redis_url = format!("redis://{}:{}", redis_host, redis_port);
    let redis_client = redis::Client::open(redis_url).expect("Failed to create Redis client");

    let state = Arc::new(AppState { redis_client });
    let router = app(state);

    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], 5000));
    println!("Rust Producer API listening on {}", addr);

    axum::Server::bind(&addr)
        .serve(router.into_make_service())
        .await
        .unwrap();
}
